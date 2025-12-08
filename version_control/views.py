"""
Views for Version Control App
"""

import logging
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import AppVersion
from .serializers import VersionCheckResponseSerializer

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """
    Get the client IP address from the request.
    Handles proxy headers (X-Forwarded-For, X-Real-IP) for production deployments.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', 'unknown')
    return ip


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
    
    Example Request:
    GET /v2/current-version?app_version=1.0.0
    
    Example Response (when update required):
    {
        "current_version": "1.2.0",
        "minimum_required_version": "1.1.0",
        "force_update": false,
        "is_valid": false,
        "requires_update": true,
        "is_blocked": true,
        "message": "App version 1.0.0 is no longer supported. Please update to version 1.1.0 or higher.",
        "update_url": "https://play.google.com/store/apps/details?id=com.example.app",
        "release_notes": "Bug fixes and performance improvements"
    }
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
