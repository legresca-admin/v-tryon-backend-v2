"""
WebSocket URL routing for Django Channels.

This module defines the WebSocket URL patterns for the application.
"""

from django.urls import re_path
from .consumer import UserWebSocketConsumer

websocket_urlpatterns = [
    re_path(r'^ws/user/(?P<user_id>\d+)/$', UserWebSocketConsumer.as_asgi()),
]

