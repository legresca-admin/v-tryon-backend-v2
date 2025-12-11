"""
Celery tasks for try-on operations
"""
import logging
import os
import tempfile
import uuid
from datetime import datetime

from celery import shared_task
from django.conf import settings

from .models import TryonRequest
from .services.vertex_tryon import virtual_try_on
from .services.bunny_storage import get_bunny_storage_service

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_tryon_async(self, tryon_request_id):
    """
    Async task to generate virtual try-on images
    
    Args:
        tryon_request_id: ID of TryonRequest
    
    Returns:
        dict with status and tryon_request_id
    """
    logger.info(
        "[CELERY] Starting try-on generation for request %s (task_id=%s, retries=%s)",
        tryon_request_id,
        self.request.id,
        self.request.retries
    )
    
    try:
        # Get try-on request
        logger.info("[CELERY] Fetching TryonRequest %s", tryon_request_id)
        tryon_request = TryonRequest.objects.get(id=tryon_request_id)
        tryon_request.status = 'processing'
        tryon_request.save()
        logger.info("[CELERY] Updated request %s status to 'processing'", tryon_request_id)
        
        # Download images from BunnyCDN URLs
        import requests
        
        person_temp = None
        garment_temp = None
        result_temp = None
        
        try:
            # Download person image
            logger.info("[CELERY] Downloading person image from: %s", tryon_request.person_image_url)
            person_response = requests.get(tryon_request.person_image_url, timeout=30)
            person_response.raise_for_status()
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                tmp_file.write(person_response.content)
                person_temp = tmp_file.name
            
            logger.info("[CELERY] Person image downloaded to: %s", person_temp)
            
            # Download garment image
            logger.info("[CELERY] Downloading garment image from: %s", tryon_request.garment_image_url)
            garment_response = requests.get(tryon_request.garment_image_url, timeout=30)
            garment_response.raise_for_status()
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                tmp_file.write(garment_response.content)
                garment_temp = tmp_file.name
            
            logger.info("[CELERY] Garment image downloaded to: %s", garment_temp)
            
            # Call virtual try-on service
            logger.info("[CELERY] Calling virtual_try_on service")
            generated_images = virtual_try_on(
                person_image_path=person_temp,
                product_image_path=garment_temp,
                number_of_images=1,
                base_steps=None
            )
            
            if not generated_images or len(generated_images) == 0:
                raise RuntimeError("No images generated from virtual_try_on")
            
            logger.info("[CELERY] Vertex AI returned %s images", len(generated_images))
            
            # Get the first generated image
            gen_img = generated_images[0]
            
            # Save generated image to temporary file
            result_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
            gen_img.image.save(result_temp)
            logger.info("[CELERY] Generated image saved to: %s", result_temp)
            
            # Read the image data
            with open(result_temp, 'rb') as f:
                image_data = f.read()
            
            # Upload generated image to BunnyCDN
            bunny_storage = get_bunny_storage_service()
            now = datetime.now()
            date_path = now.strftime('%Y/%m/%d')
            unique_id = str(uuid.uuid4())[:8]
            generated_remote_path = f'tryon/{date_path}/generated_{tryon_request_id}_{unique_id}.png'
            
            logger.info("[CELERY] Uploading generated image to BunnyCDN: %s", generated_remote_path)
            generated_image_url = bunny_storage.upload_file_from_bytes(
                image_data,
                generated_remote_path,
                'image/png'
            )
            
            if not generated_image_url:
                raise RuntimeError("Failed to upload generated image to BunnyCDN")
            
            logger.info("[CELERY] Generated image uploaded to BunnyCDN: %s", generated_image_url)
            
            # Update try-on request with generated image URL
            tryon_request.generated_image_url = generated_image_url
            tryon_request.status = 'completed'
            tryon_request.save()
            
            logger.info("[CELERY] ✓ Try-on generation completed successfully for request %s", tryon_request_id)
            
            return {
                'status': 'completed',
                'tryon_request_id': tryon_request_id,
                'generated_image_url': generated_image_url
            }
            
        finally:
            # Clean up temporary files
            try:
                if person_temp and os.path.exists(person_temp):
                    os.unlink(person_temp)
                if garment_temp and os.path.exists(garment_temp):
                    os.unlink(garment_temp)
                if result_temp and os.path.exists(result_temp):
                    os.unlink(result_temp)
            except Exception as cleanup_error:
                logger.warning("[CELERY] Error cleaning up temp files: %s", cleanup_error)
        
    except TryonRequest.DoesNotExist:
        error_msg = f"TryonRequest {tryon_request_id} not found"
        logger.error(error_msg)
        raise
        
    except Exception as e:
        error_msg = str(e)
        logger.exception("Try-on generation failed for request %s: %s", tryon_request_id, error_msg)
        
        # Update request with error
        try:
            tryon_request = TryonRequest.objects.get(id=tryon_request_id)
            tryon_request.status = 'failed'
            tryon_request.error_message = error_msg[:500]
            tryon_request.save()
        except Exception as save_error:
            logger.error("Failed to update request %s status: %s", tryon_request_id, save_error)
        
        # Retry if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.warning("Retrying try-on generation (attempt %s/%s)", self.request.retries + 1, self.max_retries)
            raise self.retry(exc=e)
        
        # Final failure
        logger.error("Try-on generation failed permanently for request %s after %s retries", tryon_request_id, self.max_retries)
        raise

