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
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import FilterSet
from celery.result import AsyncResult

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
from v_tryon_backend_v2.websocket_utils import send_websocket_status_update

logger = logging.getLogger(__name__)


class TryonRequestPagination(PageNumberPagination):
    """Pagination class for TryonRequest list."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class TryonRequestFilter(FilterSet):
    """FilterSet for TryonRequest with inline filtering."""
    
    class Meta:
        model = TryonRequest
        fields = ['status', 'device_id']


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
      
        # Save record to database with BunnyCDN URLs (status will be 'pending')
        try:
            serializer = TryonRequestSerializer(
                data={
                    'device_id': deviceId,
                    'person_image_url': person_image_url,
                    'garment_image_url': garment_image_url,
                    'generated_image_url': '',  # Will be set by task
                    'status': 'pending',
                },
                context={'user': user}
            )

            if serializer.is_valid():
                saved_record = serializer.save()
                logger.info(
                    "TryonRequest saved -> ID: %d, User: %s, Person: %s, Garment: %s, Status: pending",
                    saved_record.id,
                    user.username,
                    person_image_url,
                    garment_image_url
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
        
        # Clean up temporary files (they're already uploaded to BunnyCDN)
        try:
            if person_temp and os.path.exists(person_temp):
                os.unlink(person_temp)
            if garment_temp and os.path.exists(garment_temp):
                os.unlink(garment_temp)
        except Exception as cleanup_error:
            logger.warning("API v2: Error cleaning up temp files: %s", cleanup_error)
        
        # Queue the async task
        from .tasks import generate_tryon_async
        # WebSocket updates are now sent directly from the generation task
        try:
            task = generate_tryon_async.delay(saved_record.id)
            # Store task ID in database for monitoring
            saved_record.task_id = task.id
            saved_record.save(update_fields=['task_id'])
            logger.info("API v2: Try-on task queued: request_id=%s, task_id=%s", saved_record.id, task.id)
            
            # Send initial "pending" status via WebSocket immediately
            try:
                send_websocket_status_update(
                    user_id=user.id,
                    task_type='tryon',
                    task_id=task.id,
                    status='pending',
                    tryon_request_id=saved_record.id,
                    generated_image_url=None,
                    error_message=None
                )
                logger.info("API v2: Sent initial 'pending' status via WebSocket for request_id=%s", saved_record.id)
            except Exception as ws_error:
                logger.warning(f"API v2: Failed to send initial WebSocket status: {ws_error}")
            
        except Exception as e:
            logger.error("API v2: Failed to queue task: %s", str(e), exc_info=True)
            # Update request status to failed
            saved_record.status = 'failed'
            saved_record.error_message = f'Failed to queue task: {str(e)}'
            saved_record.save()
            return Response(
                {'error': 'Failed to queue try-on generation task'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
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
        
        # Return JSON response with task info (202 Accepted)
        response_data = {
            'success': True,
            'message': 'Try-on generation started',
            'id': saved_record.id,
            'task_id': task.id,
            'status': 'processing',
            'person_image_url': person_image_url,
            'garment_image_url': garment_image_url,
            'estimated_time': '60-120 seconds',
            'rate_limit': {
                'limit': limit,
                'remaining': remaining,
                'used': used_count,
                'is_unlimited': rate_limit_status['is_unlimited']
            },
            'user_name': user.username,
            'user_id': user.id
        }
        
        response = Response(response_data, status=status.HTTP_202_ACCEPTED)
        
        # Add rate limit headers for client information
        response['X-RateLimit-Limit'] = str(limit) if limit > 0 else 'Unlimited'
        response['X-RateLimit-Remaining'] = str(remaining) if remaining is not None else 'Unlimited'
        response['X-RateLimit-Used'] = str(used_count)
        
        logger.info(
            "API v2: Returning response for user=%s (ID: %d) - Record ID: %s, Task ID: %s, Used: %d/%d",
            user.username,
            user.id,
            saved_record.id,
            task.id,
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
@permission_classes([IsAuthenticated])
def tryon_task_status(request, tryon_request_id):
    """
    Check status of async try-on generation task.
    
    Args:
        tryon_request_id: ID of TryonRequest
    
    Returns:
        Response with task status and try-on request details
    """
    
    try:
        tryon_request = TryonRequest.objects.get(id=tryon_request_id, user=request.user)
    except TryonRequest.DoesNotExist:
        return Response(
            {'error': 'Try-on request not found or does not belong to you'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    task_id = request.query_params.get('task_id')
    
    # Refresh from database to get latest status
    tryon_request.refresh_from_db()
    
    if not task_id:
        # Return request status only
        return Response({
            'tryon_request_id': tryon_request.id,
            'status': tryon_request.status,
            'error_message': tryon_request.error_message if tryon_request.status == 'failed' else None,
            'generated_image_url': tryon_request.generated_image_url if tryon_request.status == 'completed' else None
        })
    
    # Check Celery task status
    task_result = AsyncResult(task_id)
    
    # If task failed but request is still processing, update request
    if task_result.state == 'FAILURE' and tryon_request.status == 'processing':
        error_msg = str(task_result.info) if task_result.info else 'Task failed'
        try:
            tryon_request.status = 'failed'
            tryon_request.error_message = error_msg[:500]
            tryon_request.save()
            logger.warning("Updated tryon request %s to failed based on task %s failure", tryon_request_id, task_id)
        except Exception as e:
            logger.error("Failed to update tryon request %s status: %s", tryon_request_id, e)
        tryon_request.refresh_from_db()
    
    # Build response
    response_data = {
        'tryon_request_id': tryon_request.id,
        'task_id': task_id,
        'status': tryon_request.status,
        'task_state': task_result.state,
    }
    
    if tryon_request.status == 'failed':
        response_data['message'] = 'Generation failed'
        response_data['error'] = tryon_request.error_message or (str(task_result.info) if task_result.state == 'FAILURE' else 'Unknown error')
    elif tryon_request.status == 'completed':
        response_data['message'] = 'Generation completed successfully'
        response_data['generated_image_url'] = tryon_request.generated_image_url
    elif task_result.state == 'PENDING':
        response_data['message'] = 'Task is waiting to be processed'
    elif task_result.state == 'STARTED':
        response_data['message'] = 'Task is currently processing'
    elif task_result.state == 'SUCCESS':
        response_data['message'] = 'Task completed successfully'
        response_data['result'] = task_result.result
        response_data['generated_image_url'] = tryon_request.generated_image_url
    elif task_result.state == 'FAILURE':
        response_data['message'] = 'Task failed'
        response_data['error'] = str(task_result.info)
    elif task_result.state == 'RETRY':
        response_data['message'] = 'Task is being retried'
    else:
        response_data['message'] = f'Status: {tryon_request.status}'
    
    return Response(response_data)


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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tryon_list(request):
    """
    Get list of try-on requests with filtering and pagination.
    
    Query Parameters:
    - status: Filter by status (pending, processing, completed, failed)
    - device_id: Filter by device ID
    - created_at__gte: Filter by created date (greater than or equal) - format: YYYY-MM-DD
    - created_at__lte: Filter by created date (less than or equal) - format: YYYY-MM-DD
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20, max: 100)
    
    Returns:
    - Paginated list of try-on requests for the authenticated user
    """
    user = request.user
    
    # Base queryset - only user's own requests
    queryset = TryonRequest.objects.filter(user=user).order_by('-created_at')
    
    # Apply filters using DjangoFilterBackend FilterSet
    filterset = TryonRequestFilter(request.query_params, queryset=queryset)
    queryset = filterset.qs
    
    # Apply pagination
    paginator = TryonRequestPagination()
    paginated_queryset = paginator.paginate_queryset(queryset, request)
    
    # Serialize data
    serializer = TryonRequestSerializer(paginated_queryset, many=True)
    
    # Return paginated response
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tryon_detail(request, tryon_request_id):
    """
    Get a single try-on request by ID.
    
    Args:
        tryon_request_id: ID of TryonRequest
    
    Returns:
        Response with try-on request details
    """
    user = request.user
    
    try:
        tryon_request = TryonRequest.objects.get(id=tryon_request_id, user=user)
    except TryonRequest.DoesNotExist:
        return Response(
            {
                'error': 'Try-on request not found or does not belong to you'
            },
            status=status.HTTP_404_NOT_FOUND
        )
    
    serializer = TryonRequestSerializer(tryon_request)
    return Response(
        {
            'success': True,
            'data': serializer.data
        },
        status=status.HTTP_200_OK
    )
