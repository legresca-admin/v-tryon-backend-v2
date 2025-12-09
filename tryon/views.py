"""
Django REST Framework Views for Try-On App
"""

import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django_ratelimit.core import is_ratelimited
from django_ratelimit.exceptions import Ratelimited
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from .services.vertex_tryon import virtual_try_on
from .utils import get_client_ip, get_rate_limit_status, check_rate_limit, increment_rate_limit_count

logger = logging.getLogger(__name__)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def tryon_v2(request):
    """
    Public API v2 endpoint for virtual try-on.
    
    No authentication required - this is a public API.
    
    Accepts:
    - person_image: Image file of the person
    - garment_image: Image file of the garment
    
    Returns:
    - JSON response with image URL:
      {
        "success": true,
        "image_url": "http://your-domain.com/media/tryon/2025/12/08/tryon_abc123.png",
        "message": "Try-on image generated successfully"
      }
    
    The generated image is saved to the server's media directory and can be accessed via the returned URL.
    
    Rate Limits (per IP):
    - 10 requests per hour
    - 40 requests per day
    
    Rate limit is tracked by IP address. Each unique IP has its own limit counter.
    """
    client_ip = get_client_ip(request)
    logger.info("API v2 try-on request received from IP=%s", client_ip)
    
    # Rate limiting: Check BEFORE incrementing to prevent exceeding limits
    # This checks both hourly and daily limits without incrementing counters
    rate_limit_check = check_rate_limit(request)
    hourly_status = rate_limit_check['hourly_status']
    daily_status = rate_limit_check['daily_status']
    
    # Check if either limit is exceeded
    if not rate_limit_check['allowed']:
        # Determine which limit was exceeded
        hourly_exceeded = hourly_status['current_count'] >= hourly_status['limit']
        daily_exceeded = daily_status['current_count'] >= daily_status['limit']
        
        if hourly_exceeded:
            logger.warning(
                "API v2: Rate limit exceeded (hourly) for IP=%s - Current: %d/%d",
                client_ip, hourly_status['current_count'], hourly_status['limit']
            )
            return Response(
                {
                    'error': 'Rate limit exceeded',
                    'message': 'You have exceeded the hourly rate limit of 10 requests per hour. Please try again later.',
                    'rate_limit': {
                        'hourly': {
                            'limit': hourly_status['limit'],
                            'remaining': hourly_status['remaining'],
                            'used': hourly_status['current_count']
                        },
                        'daily': {
                            'limit': daily_status['limit'],
                            'remaining': daily_status['remaining'],
                            'used': daily_status['current_count']
                        }
                    }
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
        
        if daily_exceeded:
            logger.warning(
                "API v2: Rate limit exceeded (daily) for IP=%s - Current: %d/%d",
                client_ip, daily_status['current_count'], daily_status['limit']
            )
            return Response(
                {
                    'error': 'Rate limit exceeded',
                    'message': 'You have exceeded the daily rate limit of 40 requests per day. Please try again tomorrow.',
                    'rate_limit': {
                        'hourly': {
                            'limit': hourly_status['limit'],
                            'remaining': hourly_status['remaining'],
                            'used': hourly_status['current_count']
                        },
                        'daily': {
                            'limit': daily_status['limit'],
                            'remaining': daily_status['remaining'],
                            'used': daily_status['current_count']
                        }
                    }
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )
    
    # Rate limit check passed - now increment counters
    # Only increment if the request is allowed (we've already checked above)
    increment_rate_limit_count(request, 'hourly')
    increment_rate_limit_count(request, 'daily')
    
    # Check for required files
    if 'person_image' not in request.FILES:
        logger.warning("API v2: Missing person_image in request")
        return Response(
            {'error': 'person_image is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if 'garment_image' not in request.FILES:
        logger.warning("API v2: Missing garment_image in request")
        return Response(
            {'error': 'garment_image is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    person_file = request.FILES['person_image']
    garment_file = request.FILES['garment_image']
    
    # Create temporary files
    person_temp = None
    garment_temp = None
    result_temp = None
    
    try:
        # Save uploaded files to temporary locations
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as person_tmp:
            for chunk in person_file.chunks():
                person_tmp.write(chunk)
            person_temp = person_tmp.name
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as garment_tmp:
            for chunk in garment_file.chunks():
                garment_tmp.write(chunk)
            garment_temp = garment_tmp.name
        
        logger.info(
            "API v2: Saved temporary files person=%s garment=%s",
            person_temp,
            garment_temp
        )
        
        # Call virtual try-on service
        logger.info("API v2: Calling virtual_try_on service")
        generated_images = virtual_try_on(
            person_image_path=person_temp,
            product_image_path=garment_temp,
            number_of_images=1,  # Just return one image
            base_steps=None  # Use default
        )
        
        if not generated_images or len(generated_images) == 0:
            logger.error("API v2: No images generated from virtual_try_on")
            return Response(
                {'error': 'Failed to generate try-on image'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Get the first generated image
        gen_img = generated_images[0]
        
        # Save generated image to temporary file first
        result_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
        
        # Save the generated image to temp file
        # The gen_img.image object has a save method
        gen_img.image.save(result_temp)
        
        logger.info("API v2: Generated image saved to temp file %s", result_temp)
        
        # Read the image data
        with open(result_temp, 'rb') as f:
            image_data = f.read()
        
        # Generate unique filename with date-based directory structure
        # Format: tryon/YYYY/MM/DD/tryon_{uuid}.png
        now = datetime.now()
        date_path = now.strftime('%Y/%m/%d')
        unique_id = str(uuid.uuid4())[:8]
        filename = f'tryon_{unique_id}.png'
        media_path = f'tryon/{date_path}/{filename}'
        
        # Ensure media directory exists
        media_dir = Path(settings.MEDIA_ROOT) / 'tryon' / date_path
        media_dir.mkdir(parents=True, exist_ok=True)
        
        # Save image to media directory
        full_path = media_dir / filename
        with open(full_path, 'wb') as f:
            f.write(image_data)
        
        # Generate the URL for the saved image
        image_url = f"{settings.MEDIA_URL}{media_path}"
        # Make it absolute URL if request is available
        if request:
            # Get the scheme and host from request
            scheme = request.scheme
            host = request.get_host()
            image_url = f"{scheme}://{host}{settings.MEDIA_URL}{media_path}"
        
        logger.info(
            "API v2: Generated image saved to media directory: %s, URL: %s",
            full_path,
            image_url
        )
        
        # Clean up temporary files
        try:
            if person_temp and os.path.exists(person_temp):
                os.unlink(person_temp)
            if garment_temp and os.path.exists(garment_temp):
                os.unlink(garment_temp)
            if result_temp and os.path.exists(result_temp):
                os.unlink(result_temp)
        except Exception as cleanup_error:
            logger.warning("API v2: Error cleaning up temp files: %s", cleanup_error)
        
        # Get updated rate limit status (after increment)
        # The rate limit was incremented by is_ratelimited above, so we need to get the current count
        hourly_status = get_rate_limit_status(request, 'hourly')
        daily_status = get_rate_limit_status(request, 'daily')
        
        # The count includes the current request (was incremented by is_ratelimited)
        hourly_used = hourly_status['current_count']
        daily_used = daily_status['current_count']
        
        logger.info(
            "API v2: Rate limit after request - IP=%s, Hourly: %d/%d, Daily: %d/%d",
            client_ip, hourly_used, hourly_status['limit'], daily_used, daily_status['limit']
        )
        
        # Return JSON response with image URL
        # Note: hourly_used and daily_used already include the current request
        response_data = {
            'success': True,
            'image_url': image_url,
            'message': 'Try-on image generated successfully',
            'rate_limit': {
                'hourly': {
                    'limit': hourly_status['limit'],
                    'remaining': max(0, hourly_status['limit'] - hourly_used),
                    'used': hourly_used
                },
                'daily': {
                    'limit': daily_status['limit'],
                    'remaining': max(0, daily_status['limit'] - daily_used),
                    'used': daily_used
                }
            }
        }
        
        response = Response(response_data, status=status.HTTP_200_OK)
        
        # Add rate limit headers for client information
        response['X-RateLimit-Limit-Hourly'] = str(hourly_status['limit'])
        response['X-RateLimit-Remaining-Hourly'] = str(max(0, hourly_status['limit'] - hourly_used))
        response['X-RateLimit-Limit-Daily'] = str(daily_status['limit'])
        response['X-RateLimit-Remaining-Daily'] = str(max(0, daily_status['limit'] - daily_used))
        
        logger.info(
            "API v2: Returning image URL for IP=%s - URL: %s, Hourly: %d/%d, Daily: %d/%d",
            client_ip,
            image_url,
            hourly_status['current_count'], hourly_status['limit'],
            daily_status['current_count'], daily_status['limit']
        )
        return response
        
    except Exception as e:
        logger.error("API v2: Error processing try-on request: %s", str(e), exc_info=True)
        
        # Clean up temporary files on error
        try:
            if person_temp and os.path.exists(person_temp):
                os.unlink(person_temp)
            if garment_temp and os.path.exists(garment_temp):
                os.unlink(garment_temp)
            if result_temp and os.path.exists(result_temp):
                os.unlink(result_temp)
        except Exception:
            pass
        
        return Response(
            {'error': 'Internal server error while processing try-on request'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def current_version(request):
    """
    Get current app version information.
    
    This endpoint allows the mobile app to check if it needs to update.
    
    Query Parameters:
    - app_version (optional): The current app version (e.g., '1.0.0')
      If provided, the API will compare and return whether update is required.
    
    Returns:
    - current_version: Latest version number
    - minimum_required_version: Minimum version required
    - force_update: Whether force update is enabled
    - is_valid: Whether the provided app_version is valid (if app_version provided)
    - requires_update: Whether update is required (if app_version provided)
    - is_blocked: Whether app is blocked from use (if app_version provided)
    - message: Message for the user
    - update_url: URL to download/update the app
    - release_notes: Release notes for current version
    """
    app_version = request.query_params.get('app_version', None)
    
    # Get current version from database
    current_version_obj = AppVersion.get_current_version()
    
    # Prepare base response
    response_data = {
        'current_version': current_version_obj.version_number,
        'minimum_required_version': current_version_obj.minimum_required_version,
        'force_update': current_version_obj.force_update,
        'update_url': current_version_obj.update_url or '',
        'release_notes': current_version_obj.release_notes or '',
    }
    
    # If app_version is provided, compare and add validation info
    if app_version:
        comparison = current_version_obj.compare_version(app_version)
        response_data.update({
            'is_valid': comparison['is_valid'],
            'requires_update': comparison['requires_update'],
            'is_blocked': comparison['is_blocked'],
            'message': comparison['message'],
        })
        
        logger.info(
            "Version check for app_version=%s from IP=%s - is_valid=%s, is_blocked=%s",
            app_version,
            get_client_ip(request),
            comparison['is_valid'],
            comparison['is_blocked']
        )
    else:
        # No app_version provided, just return current version info
        response_data.update({
            'is_valid': True,
            'requires_update': False,
            'is_blocked': False,
            'message': f'Current app version: {current_version_obj.version_number}',
        })
    
    serializer = VersionCheckResponseSerializer(data=response_data)
    serializer.is_valid(raise_exception=True)
    
    return Response(serializer.validated_data, status=status.HTTP_200_OK)
