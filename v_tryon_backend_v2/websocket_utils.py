"""
WebSocket utility functions for sending status updates to clients.

This module provides helper functions for sending real-time status updates
via WebSocket to clients during image generation tasks.
"""

import logging
import time
from typing import Optional, Dict, Any
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)


def _send_websocket_message(
    channel_layer,
    user_id: int,
    task_type: str,
    data: Dict[str, Any]
):
    """
    Internal helper function to send WebSocket message to user.
    
    Args:
        channel_layer: Django Channels channel layer
        user_id: ID of the user to send message to
        task_type: Type of task ('tryon' or 'pose')
        data: Message data to send
    """
    try:
        room_group_name = f'user_{user_id}'
        
        # Send message to user's room group
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'task_status_update',
                'task_type': task_type,
                'data': data,
                'timestamp': time.time()
            }
        )
        
        # Get the appropriate ID field for logging
        record_id = data.get('tryon_request_id') or data.get('tryon_pose_id')
        logger.info(
            f"[WS] ✅ Sent WebSocket message to user_id={user_id}, "
            f"task_type={task_type}, status={data.get('status')}, "
            f"task_id={data.get('task_id')}, record_id={record_id}"
        )
        
    except Exception as e:
        logger.error(
            f"[WS] Failed to send WebSocket message to user_id={user_id}: {str(e)}",
            exc_info=True
        )


def send_websocket_status_update(
    user_id: int,
    task_type: str,
    task_id: str,
    status: str,
    tryon_request_id: Optional[int] = None,
    tryon_pose_id: Optional[int] = None,
    generated_image_url: Optional[str] = None,
    error_message: Optional[str] = None,
    tryon_id: Optional[int] = None,
    scene_template_id: Optional[int] = None
):
    """
    Send WebSocket status update to user.
    
    This function can be called synchronously from Django views or Celery tasks
    to send real-time status updates to clients via WebSocket.
    
    Args:
        user_id: ID of the user
        task_type: Type of task ('tryon' or 'pose')
        task_id: Celery task ID
        status: Current status ('pending', 'processing', 'completed', 'failed')
        tryon_request_id: TryonRequest ID (for tryon tasks)
        tryon_pose_id: TryonPoses ID (for pose tasks)
        generated_image_url: Optional generated image URL
        error_message: Optional error message
        tryon_id: Optional tryon ID (for pose tasks)
        scene_template_id: Optional scene template ID (for pose tasks)
    """
    try:
        channel_layer = get_channel_layer()
        if not channel_layer:
            logger.warning(f"[WS] Channel layer not configured, cannot send status update to user {user_id}")
            return
        
        message_data = {
            'task_id': task_id,
            'task_type': task_type,
            'status': status
        }
        
        # Add the appropriate ID field based on task type
        if task_type == 'tryon' and tryon_request_id is not None:
            message_data['tryon_request_id'] = tryon_request_id
        elif task_type == 'pose' and tryon_pose_id is not None:
            message_data['tryon_pose_id'] = tryon_pose_id
        
        if generated_image_url:
            message_data['generated_image_url'] = generated_image_url
        if error_message:
            message_data['error_message'] = error_message
        if tryon_id is not None:
            message_data['tryon_id'] = tryon_id
        if scene_template_id is not None:
            message_data['scene_template_id'] = scene_template_id
        
        if status in ['completed', 'failed']:
            message_data['final'] = True
        
        _send_websocket_message(channel_layer, user_id, task_type, message_data)
        
    except Exception as e:
        logger.error(
            f"[WS] Failed to send status update to user {user_id}: {str(e)}",
            exc_info=True
        )

