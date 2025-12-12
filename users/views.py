"""
User Registration and Login Views with JWT Authentication
"""

import logging

from django.contrib.auth import get_user_model, authenticate
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegistrationSerializer, LoginSerializer

User = get_user_model()
logger = logging.getLogger(__name__)


def get_tokens_for_user(user):
    """Generate JWT tokens for user."""
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class RegisterUserView(APIView):
    """
    User registration endpoint.
    
    Accepts: username, email, password, confirm_password
    Returns: JWT tokens (access, refresh) and user data
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """Handle user registration."""
        try:
            serializer = RegistrationSerializer(data=request.data)
            
            if not serializer.is_valid():
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            user = serializer.save()
            tokens = get_tokens_for_user(user)
            
            logger.info(f"User registered successfully: {user.username}")
            
            return Response(
                {
                    'success': True,
                    'message': 'User registered successfully',
                    'data': {
                        'tokens': tokens,
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'email': user.email
                        }
                    }
                },
                status=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Registration error: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to register user. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LoginUserView(APIView):
    """
    User login endpoint.
    
    Accepts: username, password
    Returns: JWT tokens (access, refresh) and user data
    """
    permission_classes = [AllowAny]

    def post(self, request):
        """Handle user login."""
        try:
            serializer = LoginSerializer(data=request.data)
            
            if not serializer.is_valid():
                return Response(
                    {'error': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            
            # Use Django's built-in authenticate function
            user = authenticate(username=username, password=password)
            
            if user is None:
                logger.warning(f"Failed login attempt for username: {username}")
                return Response(
                    {'error': 'Invalid username or password'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            # Check if user is active (authenticate already checks this, but explicit check for clarity)
            if not user.is_active:
                logger.warning(f"Login attempt for inactive user: {username}")
                return Response(
                    {'error': 'User account is disabled'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            tokens = get_tokens_for_user(user)
            
            logger.info(f"User logged in successfully: {user.username}")
            
            return Response(
                {
                    'success': True,
                    'message': 'Login successful',
                    'data': {
                        'tokens': tokens,
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'email': user.email
                        }
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except Exception as e:
            logger.error(f"Login error: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Internal server error. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
