"""
Views for Poses App
"""

import logging
import os
import tempfile
import uuid
from datetime import datetime

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import FilterSet

from poses.models import SceneTemplate, TryonPoses
from poses.serializers import SceneTemplateSerializer, SceneGenerationRequestSerializer, TryonPosesSerializer
from tryon.models import TryonRequest
from tryon.services.bunny_storage import get_bunny_storage_service
from poses.services.vertex_imagen_pose import generate_pose_image
from celery.result import AsyncResult
from poses.tasks import generate_pose_async
from v_tryon_backend_v2.websocket_utils import send_websocket_status_update

logger = logging.getLogger(__name__)


class TryonPosesPagination(PageNumberPagination):
    """Pagination class for TryonPoses list."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class TryonPosesFilter(FilterSet):
    """FilterSet for TryonPoses with inline filtering."""
    
    class Meta:
        model = TryonPoses
        fields = ['status', 'tryon', 'scene_template']


class SceneTemplateListView(APIView):
    """
    API view to get a list of scene templates for the current logged-in user.
    
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Retrieve all scene templates for the current logged-in user.
        
        Returns:
            Response: List of scene templates for the current user with status 200.
        """
        scene_templates = SceneTemplate.objects.filter(user=request.user)
        serializer = SceneTemplateSerializer(
            scene_templates,
            many=True,
            context={'request': request, 'user': request.user}
        )
        return Response(
            {
                'success': True,
                'data': serializer.data,
                'count': len(serializer.data)
            },
            status=status.HTTP_200_OK
        )

class GenerateScenePoseView(APIView):
    """
    API view to generate a pose image based on scene template prompt and try-on generated image.
    Also provides GET endpoints to list and retrieve TryonPoses.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, tryon_pose_id=None):
        """
        Get list of try-on poses or a single try-on pose by ID.
        
        Query Parameters (for list):
        - status: Filter by status (pending, processing, completed, failed)
        - tryon: Filter by try-on request ID
        - scene_template: Filter by scene template ID
        - page: Page number (default: 1)
        - page_size: Items per page (default: 20, max: 100)
        
        Returns:
        - List of try-on poses with filtering and pagination, or
        - Single try-on pose details if ID is provided
        """
        user = request.user
        
        # If ID is provided in URL, return single object
        if tryon_pose_id is not None:
            try:
                tryon_pose = TryonPoses.objects.get(id=tryon_pose_id, user=user)
            except TryonPoses.DoesNotExist:
                return Response(
                    {
                        'success': False,
                        'error': 'Try-on pose not found or does not belong to you'
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
            
            serializer = TryonPosesSerializer(tryon_pose)
            return Response(
                {
                    'success': True,
                    'data': serializer.data
                },
                status=status.HTTP_200_OK
            )
        
        queryset = TryonPoses.objects.filter(user=user).order_by('-created_at')
        
        filterset = TryonPosesFilter(request.query_params, queryset=queryset)
        queryset = filterset.qs
        
        paginator = TryonPosesPagination()
        paginated_queryset = paginator.paginate_queryset(queryset, request)
        
        serializer = TryonPosesSerializer(paginated_queryset, many=True)
        
        response = paginator.get_paginated_response(serializer.data)
        paginated_data = response.data
        response.data = {
            'success': True,
            'data': paginated_data.get('results', serializer.data),
            'count': paginated_data.get('count', len(serializer.data)),
            'next': paginated_data.get('next'),
            'previous': paginated_data.get('previous')
        }
        return response

    def post(self, request):
        """
        Generate a pose image based on scene template prompt and try-on generated image.
        
        Returns:
            Response: Generated pose image URL with status 200.
        """
        serializer = SceneGenerationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    'success': False,
                    'error': 'Invalid request data',
                    'details': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        scene_template_id = serializer.validated_data['scene_template_id']
        tryon_id = serializer.validated_data['tryon_id']

        # Get scene template
        try:
            scene_template = SceneTemplate.objects.get(id=scene_template_id, user=request.user)
        except SceneTemplate.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'error': f'Scene template with id {scene_template_id} not found or does not belong to you'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # Get try-on request
        try:
            tryon_request = TryonRequest.objects.get(id=tryon_id, user=request.user)
        except TryonRequest.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'error': f'Try-on request with id {tryon_id} not found or does not belong to you'
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if generated_image_url exists
        if not tryon_request.generated_image_url:
            return Response(
                {
                    'success': False,
                    'error': 'Try-on request does not have a generated image URL'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create TryonPoses record with pending status
        tryon_pose = TryonPoses.objects.create(
            user=request.user,
            tryon=tryon_request,
            scene_template=scene_template,
            status='pending'
        )
        logger.info(
            "Created TryonPoses record id=%s for user=%s tryon_id=%s scene_template_id=%s (status: pending)",
            tryon_pose.id,
            request.user.id,
            tryon_id,
            scene_template_id
        )

        # Queue the async task
        # WebSocket updates are now sent directly from the generation task
        try:
            task = generate_pose_async.delay(tryon_pose.id)
            # Store task ID in database for monitoring
            tryon_pose.task_id = task.id
            tryon_pose.save(update_fields=['task_id'])
            logger.info("Pose generation task queued: tryon_pose_id=%s, task_id=%s", tryon_pose.id, task.id)
            
            # Send initial "pending" status via WebSocket immediately
            try:
                send_websocket_status_update(
                    user_id=request.user.id,
                    task_type='pose',
                    task_id=task.id,
                    status='pending',
                    tryon_pose_id=tryon_pose.id,
                    generated_image_url=None,
                    error_message=None,
                    tryon_id=tryon_id,
                    scene_template_id=scene_template_id
                )
                logger.info("Pose generation: Sent initial 'pending' status via WebSocket for tryon_pose_id=%s", tryon_pose.id)
            except Exception as ws_error:
                logger.warning(f"Pose generation: Failed to send initial WebSocket status: {ws_error}")

        except Exception as e:
            logger.error("Failed to queue pose generation task: %s", str(e), exc_info=True)
            # Update tryon_pose status to failed
            tryon_pose.status = 'failed'
            tryon_pose.error_message = f'Failed to queue task: {str(e)}'
            tryon_pose.save()
            return Response(
                {
                    'success': False,
                    'error': 'Failed to queue pose generation task'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                'success': True,
                'message': 'Pose generation started',
                'data': {
                    'id': tryon_pose.id,
                    'task_id': task.id,
                    'status': 'processing',
                    'scene_template_id': scene_template_id,
                    'scene_template_name': scene_template.name,
                    'tryon_id': tryon_id,
                    'estimated_time': '30-60 seconds',
                    'created_at': tryon_pose.created_at.isoformat()
                }
            },
            status=status.HTTP_202_ACCEPTED
        )

class GenerateScenePoseTaskStatusView(APIView):
    """
    API view to check status of pose generation task.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, tryon_pose_id):
        """
        Check status of async pose generation task.
        
        Args:
            tryon_pose_id: ID of TryonPoses
        
        Returns:
            Response with task status and pose details
        """
        
        try:
            tryon_pose = TryonPoses.objects.get(id=tryon_pose_id, user=request.user)
        except TryonPoses.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'error': 'Try-on pose not found or does not belong to you'
                },
                status=status.HTTP_404_NOT_FOUND
            )
        
        task_id = request.query_params.get('task_id')
        
        # Refresh from database to get latest status
        tryon_pose.refresh_from_db()
        
        if not task_id:
            # Return pose status only
            return Response({
                'success': True,
                'tryon_pose_id': tryon_pose.id,
                'status': tryon_pose.status,
                'error_message': tryon_pose.error_message if tryon_pose.status == 'failed' else None,
                'generated_image_url': tryon_pose.generated_image_url if tryon_pose.status == 'completed' else None
            })
        
        # Check Celery task status
        task_result = AsyncResult(task_id)
        
        # If task failed but pose is still processing, update pose
        if task_result.state == 'FAILURE' and tryon_pose.status == 'processing':
            error_msg = str(task_result.info) if task_result.info else 'Task failed'
            try:
                tryon_pose.status = 'failed'
                tryon_pose.error_message = error_msg[:500]
                tryon_pose.save()
                logger.warning("Updated tryon pose %s to failed based on task %s failure", tryon_pose_id, task_id)
            except Exception as e:
                logger.error("Failed to update tryon pose %s status: %s", tryon_pose_id, e)
            tryon_pose.refresh_from_db()
        
        # Build response
        response_data = {
            'success': True,
            'tryon_pose_id': tryon_pose.id,
            'task_id': task_id,
            'status': tryon_pose.status,
            'task_state': task_result.state,
        }
        
        if tryon_pose.status == 'failed':
            response_data['message'] = 'Generation failed'
            response_data['error'] = tryon_pose.error_message or (str(task_result.info) if task_result.state == 'FAILURE' else 'Unknown error')
        elif tryon_pose.status == 'completed':
            response_data['message'] = 'Generation completed successfully'
            response_data['generated_image_url'] = tryon_pose.generated_image_url
            response_data['scene_template_id'] = tryon_pose.scene_template.id
            response_data['scene_template_name'] = tryon_pose.scene_template.name
            response_data['tryon_id'] = tryon_pose.tryon.id
        elif task_result.state == 'PENDING':
            response_data['message'] = 'Task is waiting to be processed'
        elif task_result.state == 'STARTED':
            response_data['message'] = 'Task is currently processing'
        elif task_result.state == 'SUCCESS':
            response_data['message'] = 'Task completed successfully'
            response_data['result'] = task_result.result
            response_data['generated_image_url'] = tryon_pose.generated_image_url
        elif task_result.state == 'FAILURE':
            response_data['message'] = 'Task failed'
            response_data['error'] = str(task_result.info)
        elif task_result.state == 'RETRY':
            response_data['message'] = 'Task is being retried'
        else:
            response_data['message'] = f'Status: {tryon_pose.status}'
        
        return Response(response_data)


