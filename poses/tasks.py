"""
Celery tasks for pose generation operations
"""
import logging
import os
import tempfile
import uuid
from datetime import datetime

import requests
from celery import shared_task

from .models import TryonPoses
from .services.vertex_imagen_pose import generate_pose_image
from tryon.services.bunny_storage import get_bunny_storage_service

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_pose_async(self, tryon_pose_id):
    """
    Async task to generate pose images
    
    Args:
        tryon_pose_id: ID of TryonPoses
    
    Returns:
        dict with status and tryon_pose_id
    """
    logger.info(
        "[CELERY] Starting pose generation for TryonPoses %s (task_id=%s, retries=%s)",
        tryon_pose_id,
        self.request.id,
        self.request.retries
    )
    
    try:
        # Get try-on pose record
        logger.info("[CELERY] Fetching TryonPoses %s", tryon_pose_id)
        tryon_pose = TryonPoses.objects.get(id=tryon_pose_id)
        tryon_pose.status = 'processing'
        tryon_pose.save()
        logger.info("[CELERY] Updated TryonPoses %s status to 'processing'", tryon_pose_id)
        
        # Get try-on request and scene template
        tryon_request = tryon_pose.tryon
        scene_template = tryon_pose.scene_template
        
        # Check if generated_image_url exists
        if not tryon_request.generated_image_url:
            raise ValueError("Try-on request does not have a generated image URL")
        
        tryon_image_url = tryon_request.generated_image_url
        logger.info("[CELERY] Getting try-on image from Bunny CDN URL: %s", tryon_image_url)
        
        tryon_temp = None
        output_temp = None
        
        try:
            # Download image from Bunny CDN URL to temporary file
            logger.debug("[CELERY] Downloading try-on image from Bunny CDN")
            response = requests.get(tryon_image_url, timeout=30)
            response.raise_for_status()
            
            # Create temporary file for input image
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
                tmp_file.write(response.content)
                tryon_temp = tmp_file.name
            
            logger.info("[CELERY] Try-on image downloaded and saved to temporary file: %s", tryon_temp)
            
            # Create temporary file for output image
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
                output_temp = tmp_file.name
            
            # Generate pose image using Vertex AI Imagen
            logger.info("[CELERY] Generating pose image with scene prompt: %s", scene_template.prompt[:100])
            generate_pose_image(
                input_image_path=tryon_temp,
                scene_prompt=scene_template.prompt,
                output_path=output_temp
            )
            
            logger.info("[CELERY] Pose image generated successfully: %s", output_temp)
            
            # Upload generated image to BunnyCDN
            bunny_service = get_bunny_storage_service()
            
            # Generate unique filename
            unique_id = str(uuid.uuid4())[:8]
            date_path = datetime.now().strftime('%Y/%m/%d')
            remote_path = f'poses/pose_generated/{date_path}/pose_{tryon_pose.scene_template.id}_{tryon_pose.tryon.id}_{unique_id}.png'
            
            # Read generated image
            with open(output_temp, 'rb') as f:
                image_bytes = f.read()
            
            # Upload to BunnyCDN
            generated_image_url = bunny_service.upload_file_from_bytes(
                file_bytes=image_bytes,
                remote_path=remote_path,
                content_type='image/png'
            )
            
            if not generated_image_url:
                raise RuntimeError("Failed to upload generated image to BunnyCDN")
            
            logger.info("[CELERY] Generated image uploaded to BunnyCDN: %s", generated_image_url)
            
            # Update try-on pose with generated image URL
            tryon_pose.generated_image_url = generated_image_url
            tryon_pose.status = 'completed'
            tryon_pose.save()
            
            logger.info("[CELERY] ✓ Pose generation completed successfully for TryonPoses %s", tryon_pose_id)
            
            return {
                'status': 'completed',
                'tryon_pose_id': tryon_pose_id,
                'generated_image_url': generated_image_url
            }
            
        finally:
            # Clean up temporary files
            try:
                if tryon_temp and os.path.exists(tryon_temp):
                    os.unlink(tryon_temp)
                if output_temp and os.path.exists(output_temp):
                    os.unlink(output_temp)
            except Exception as cleanup_error:
                logger.warning("[CELERY] Error cleaning up temp files: %s", cleanup_error)
        
    except TryonPoses.DoesNotExist:
        error_msg = f"TryonPoses {tryon_pose_id} not found"
        logger.error(error_msg)
        raise
        
    except Exception as e:
        error_msg = str(e)
        logger.exception("Pose generation failed for TryonPoses %s: %s", tryon_pose_id, error_msg)
        
        # Update try-on pose with error
        try:
            tryon_pose = TryonPoses.objects.get(id=tryon_pose_id)
            tryon_pose.status = 'failed'
            tryon_pose.error_message = error_msg[:500]
            tryon_pose.save()
        except Exception as save_error:
            logger.error("Failed to update TryonPoses %s status: %s", tryon_pose_id, save_error)
        
        # Retry if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.warning("Retrying pose generation (attempt %s/%s)", self.request.retries + 1, self.max_retries)
            raise self.retry(exc=e)
        
        # Final failure
        logger.error("Pose generation failed permanently for TryonPoses %s after %s retries", tryon_pose_id, self.max_retries)
        raise

