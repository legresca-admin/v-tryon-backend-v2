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
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from .services.vertex_tryon import virtual_try_on
from .utils import get_client_ip, get_rate_limit_status, check_rate_limit, increment_rate_limit_count
from .utils import (
    get_rate_limit_status_device,
    check_rate_limit_device,
    increment_rate_limit_count_device
)
from .utils import (
    get_user_rate_limit_status,
    check_user_rate_limit,
    increment_user_rate_limit
)

from .models import TryonRequest
from .serializers import TryonRequestSerializer
from rest_framework.permissions import IsAuthenticated
from .services.bunny_storage import get_bunny_storage_service
from version_control.models import AppVersion
from version_control.serializers import VersionCheckResponseSerializer

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def tryon_v2(request):
    """
    Authenticated API v2 endpoint for virtual try-on.
    
    Requires authentication - user must be authenticated.
    
    Accepts:
    - deviceId: Device identifier (optional, for tracking purposes)
    - person_image: Image file of the person
    - garment_image: Image file of the garment
    
    Returns:
    - JSON response with BunnyCDN URLs and record ID:
      {
        "success": true,
        "id": 123,
        "image_url": "https://your-pull-zone.b-cdn.net/tryon/2025/12/08/generated_abc123.png",
        "person_image_url": "https://your-pull-zone.b-cdn.net/tryon/2025/12/08/person_abc123.jpg",
        "garment_image_url": "https://your-pull-zone.b-cdn.net/tryon/2025/12/08/garment_abc123.jpg",
        "generated_image_url": "https://your-pull-zone.b-cdn.net/tryon/2025/12/08/generated_abc123.png",
        "message": "Try-on image generated successfully",
        "rate_limit": {...}
      }
    
    All images (person, garment, and generated) are uploaded to BunnyCDN storage
    and their URLs are stored in the database. The record ID is returned in the response.
    
    Rate Limits:
    - Rate limit is managed per user by admin
    - Admin can set custom limits for each user via Django admin
    - Once limit is reached, user cannot generate more images until admin resets
    """
    # Get authenticated user from request
    user = request.user
    logger.info(f"Authenticated user: {user.username} (ID: {user.id})")
    
    # Get deviceId if provided (optional, for tracking purposes)
    deviceId = request.data.get('deviceId', '')
    if deviceId:
        deviceId = str(deviceId).strip()
    
    logger.info("API v2 try-on request received from user=%s (ID: %d)", user.username, user.id)
    
    # Rate limiting: Check BEFORE incrementing to prevent exceeding limits
    rate_limit_check = check_user_rate_limit(user)
    rate_limit_status = rate_limit_check['status']
    
    # Check if rate limit is not set by admin
    if not rate_limit_status.get('exists', True):
        logger.warning(
            "API v2: No rate limit set for user=%s (ID: %d) - admin must set rate limit first",
            user.username, user.id
        )
        return Response(
            {
                'error': 'Rate limit not configured',
                'message': 'You cannot generate images. Please contact admin to set your rate limit.',
                'rate_limit': {
                    'limit': 0,
                    'remaining': 0,
                    'used': 0,
                    'is_unlimited': False,
                    'exists': False
                },
                'user_name': user.username,
                'user_id': user.id
            },
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Check if limit is exceeded
    if not rate_limit_check['allowed']:
        logger.warning(
            "API v2: Rate limit exceeded for user=%s (ID: %d) - Current: %d/%d",
            user.username, user.id, rate_limit_status['current_count'], rate_limit_status['limit']
        )
        return Response(
            {
                'error': 'Rate limit exceeded',
                'message': 'You cannot generate image now. You have reached your rate limit.',
                'rate_limit': {
                    'limit': rate_limit_status['limit'],
                    'remaining': rate_limit_status['remaining'],
                    'used': rate_limit_status['current_count'],
                    'is_unlimited': rate_limit_status['is_unlimited']
                },
                'user_name': user.username,
                'user_id': user.id
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    
    # Rate limit check passed - now increment counter
    # Only increment if the request is allowed (we've already checked above)
    increment_user_rate_limit(user)
    
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
    
    # Initialize BunnyCDN storage service
    bunny_storage = get_bunny_storage_service()
    
    # Create temporary files
    person_temp = None
    garment_temp = None
    result_temp = None
    
    # Variables to store BunnyCDN URLs
    person_image_url = None
    garment_image_url = None
    generated_image_url = None
    saved_record = None
    
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
        
        # Upload person_image to BunnyCDN
        now = datetime.now()
        date_path = now.strftime('%Y/%m/%d')
        unique_id = str(uuid.uuid4())[:8]
        person_remote_path = f'tryon/{date_path}/person_{unique_id}.jpg'
        
        logger.info("API v2: Uploading person_image to BunnyCDN: %s", person_remote_path)
        person_image_url = bunny_storage.upload_file(person_temp, person_remote_path, 'image/jpeg')
        
        if not person_image_url:
            logger.error("API v2: Failed to upload person_image to BunnyCDN")
            return Response(
                {'error': 'Failed to upload person image to storage'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        logger.info("API v2: Person image uploaded to BunnyCDN: %s", person_image_url)
        
        # Upload garment_image to BunnyCDN
        garment_remote_path = f'tryon/{date_path}/garment_{unique_id}.jpg'
        
        logger.info("API v2: Uploading garment_image to BunnyCDN: %s", garment_remote_path)
        garment_image_url = bunny_storage.upload_file(garment_temp, garment_remote_path, 'image/jpeg')
        
        if not garment_image_url:
            logger.error("API v2: Failed to upload garment_image to BunnyCDN")
            return Response(
                {'error': 'Failed to upload garment image to storage'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        logger.info("API v2: Garment image uploaded to BunnyCDN: %s", garment_image_url)
        
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
        
        # Upload generated image to BunnyCDN
        generated_remote_path = f'tryon/{date_path}/generated_{unique_id}.png'
        
        logger.info("API v2: Uploading generated image to BunnyCDN: %s", generated_remote_path)
        generated_image_url = bunny_storage.upload_file_from_bytes(
            image_data,
            generated_remote_path,
            'image/png'
        )
        
        if not generated_image_url:
            logger.error("API v2: Failed to upload generated image to BunnyCDN")
            return Response(
                {'error': 'Failed to upload generated image to storage'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        logger.info("API v2: Generated image uploaded to BunnyCDN: %s", generated_image_url)
      
        # Save record to database with BunnyCDN URLs
        try:
            serializer = TryonRequestSerializer(
                data={
                    'device_id': deviceId,
                    'person_image_url': person_image_url,
                    'garment_image_url': garment_image_url,
                    'generated_image_url': generated_image_url,
                },
                context={'user': user}
            )

            if serializer.is_valid():
                saved_record = serializer.save()
                logger.info(
                    "TryonRequest saved -> ID: %d, User: %s, Person: %s, Garment: %s, Generated: %s",
                    saved_record.id,
                    user.username,
                    person_image_url,
                    garment_image_url,
                    generated_image_url
                )
            else:
                logger.warning(f"Serializer validation failed: {serializer.errors}")
                return Response(
                    {'error': 'Failed to save request to database', 'details': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            logger.error(f"Failed to save TryonRequest to DB: {e}", exc_info=True)
            return Response(
                {'error': 'Failed to save request to database'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
        rate_limit_status = get_user_rate_limit_status(user)
        
        # The count includes the current request
        used_count = rate_limit_status['current_count']
        limit = rate_limit_status['limit']
        remaining = rate_limit_status['remaining']
        
        logger.info(
            "API v2: Rate limit after request - user=%s (ID: %d), Used: %d/%d, Remaining: %s",
            user.username, user.id, used_count, limit, remaining if remaining is not None else 'Unlimited'
        )
        
        # Return JSON response with BunnyCDN URLs and record ID
        response_data = {
            'success': True,
            'id': saved_record.id if saved_record else None,
            'person_image_url': person_image_url,
            'garment_image_url': garment_image_url,
            'generated_image_url': generated_image_url,
            'message': 'Try-on image generated successfully',
            'rate_limit': {
                'limit': limit,
                'remaining': remaining,
                'used': used_count,
                'is_unlimited': rate_limit_status['is_unlimited']
            },
            'user_name': user.username,
            'user_id': user.id
        }
        
        response = Response(response_data, status=status.HTTP_200_OK)
        
        # Add rate limit headers for client information
        response['X-RateLimit-Limit'] = str(limit) if limit > 0 else 'Unlimited'
        response['X-RateLimit-Remaining'] = str(remaining) if remaining is not None else 'Unlimited'
        response['X-RateLimit-Used'] = str(used_count)
        
        logger.info(
            "API v2: Returning response for user=%s (ID: %d) - Record ID: %s, Generated URL: %s, Used: %d/%d",
            user.username,
            user.id,
            saved_record.id if saved_record else None,
            generated_image_url,
            used_count,
            limit if limit > 0 else 0
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
