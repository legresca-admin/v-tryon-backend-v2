"""
WebSocket Consumer for user-ID-based connections.

This consumer handles WebSocket connections where each user connects
using their user ID. All server events for a user are pushed through
this single WebSocket connection.
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from jwt import decode as jwt_decode
from django.conf import settings

User = get_user_model()
logger = logging.getLogger('v_tryon_backend_v2.consumer')


class UserWebSocketConsumer(AsyncWebsocketConsumer):
    """
    Global WebSocket consumer for user-ID-based connections.
    
    Each user connects with their user ID, and all server events
    for that user are pushed through this single connection.
    """

    async def connect(self):
        """Handle WebSocket connection with user authentication."""
        try:
            # Extract user ID from URL path
            self.user_id = self.scope['url_route']['kwargs'].get('user_id')
            path = self.scope.get('path', '')
            query_string = self.scope.get('query_string', b'').decode()
            
          
            logger.info(f"WebSocket connection attempt: user_id={self.user_id}")
            
            if not self.user_id:
                error_msg = "WebSocket connection rejected: No user ID provided"
         
                logger.warning(error_msg)
                await self.close(code=4001)
                return

            # Check if channel layer is available
            if not self.channel_layer:
                error_msg = "WebSocket connection rejected: Channel layer not configured"

                logger.error(error_msg)
                await self.close(code=4002)
                return

            # Authenticate user via JWT token from query parameters or headers
            user = await self.authenticate_user()
            
            if not user:
                error_msg = f"WebSocket connection rejected: Authentication failed for user ID {self.user_id}"
                logger.warning(error_msg)
                await self.close(code=4003)
                return
            
            if user.id != int(self.user_id):
                error_msg = f"WebSocket connection rejected: User ID mismatch. Token user ID: {user.id}, URL user ID: {self.user_id}"
                logger.warning(error_msg)
                await self.close(code=4004)
                return

            self.user = user
            self.room_group_name = f'user_{self.user_id}'

            # Join user-specific room group
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            await self.accept()
            success_msg = f"WebSocket connected: User ID {self.user_id}, Username: {user.username}"
            logger.info(success_msg)

            await self.send(text_data=json.dumps({
                'type': 'connection',
                'status': 'connected',
                'user_id': self.user_id,
                'message': 'WebSocket connection established'
            }))
        except Exception as e:
            import traceback
            error_msg = f"Error during WebSocket connection: {str(e)}"
            traceback_str = traceback.format_exc()
            logger.error(error_msg, exc_info=True)
            try:
                await self.close(code=4000)
            except:
                pass

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, 'room_group_name'):
            # Leave room group
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
            logger.info(f"WebSocket disconnected: User ID {self.user_id}")

    async def receive(self, text_data):
        """Handle messages received from WebSocket client."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'message')
            
            logger.debug(f"Received message from user {self.user_id}: {message_type}")
            
            # Echo back or handle different message types
            if message_type == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': data.get('timestamp')
                }))
            else:
                # Echo the message back (can be customized based on requirements)
                await self.send(text_data=json.dumps({
                    'type': 'echo',
                    'message': 'Message received',
                    'data': data
                }))
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received from user {self.user_id}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except Exception as e:
            logger.error(f"Error processing message from user {self.user_id}: {str(e)}", exc_info=True)
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Error processing message'
            }))

    async def send_message(self, event):
        """
        Handler for sending messages to the WebSocket.
        Called when a message is sent to the user's room group.
        """
        message = event.get('message', {})
        message_type = event.get('type', 'notification')
        
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': message_type,
            'data': message,
            'timestamp': event.get('timestamp')
        }))
    
    async def task_status_update(self, event):
        """
        Handler for task status updates.
        Called when a Celery task status update is sent to the user's room group.
        """
        task_type = event.get('task_type', 'unknown')
        task_data = event.get('data', {})
        timestamp = event.get('timestamp')
        
        logger.info(
            f"📨 Received task_status_update for user {self.user_id}: "
            f"type={task_type}, task_id={task_data.get('task_id')}, "
            f"status={task_data.get('status')}"
        )
        
        # Send task status update to WebSocket
        message = {
            'type': 'task_status',
            'task_type': task_type,
            'data': task_data,
            'timestamp': timestamp
        }
        
        await self.send(text_data=json.dumps(message))
        logger.info(
            f"✅ Sent task_status message to WebSocket for user {self.user_id}"
        )

    @database_sync_to_async
    def get_user_from_token(self, token):
        """Get user from JWT token."""
        try:
            # Decode token
            UntypedToken(token)
            decoded_data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = decoded_data.get('user_id')
            
            if user_id:
                return User.objects.get(id=user_id)
        except (InvalidToken, TokenError, User.DoesNotExist) as e:
            logger.error(f"Token validation error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error getting user from token: {str(e)}")
            return None

    async def authenticate_user(self):
        """Authenticate user from JWT token in query parameters or headers."""
        import urllib.parse
        
        token = None
        
        # Try to get token from query parameters
        query_string = self.scope.get('query_string', b'').decode()
        if query_string:
            # Parse query string properly (handles URL encoding)
            params = urllib.parse.parse_qs(query_string)
            # parse_qs returns a dict with lists as values
            token_list = params.get('token', [])
            if token_list:
                token = token_list[0]
        
        # If not in query, try Authorization header
        if not token:
            headers = dict(self.scope.get('headers', []))
            auth_header = headers.get(b'authorization', b'').decode()
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ', 1)[1]  # Use split with maxsplit to handle tokens with spaces
        
        if not token:
            error_msg = f"No authentication token provided for user ID {self.user_id}, query_string={query_string}"
            logger.warning(error_msg)
            return None
        
        # URL decode the token in case it was encoded
        token = urllib.parse.unquote(token)
        logger.debug(f"Token extracted for user {self.user_id}, token length: {len(token)}")
        
        user = await self.get_user_from_token(token)
        if not user:
            error_msg = f"Token validation failed for user ID {self.user_id}"
            logger.warning(error_msg)
        else:
            success_msg = f"Token validated successfully for user {user.id} ({user.username})"
            logger.debug(success_msg)
        
        return user
