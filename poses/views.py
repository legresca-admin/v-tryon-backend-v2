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

from poses.models import SceneTemplate, TryonPoses
from poses.serializers import SceneTemplateSerializer, SceneGenerationRequestSerializer
from tryon.models import TryonRequest
from tryon.services.bunny_storage import get_bunny_storage_service
from poses.services.vertex_imagen_pose import generate_pose_image

logger = logging.getLogger(__name__)


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


class SceneGenerationView(APIView):
    """
    API view to generate a pose image based on scene template prompt and try-on generated image.
    
    """

    permission_classes = [IsAuthenticated]

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

        # Get try-on image from Bunny CDN URL
        tryon_image_url = tryon_request.generated_image_url
        logger.info("Getting try-on image from Bunny CDN URL: %s", tryon_image_url)
        
        # Vertex AI Imagen requires local file paths, not URLs
        # So we need to download from Bunny CDN URL to a temporary file
        tryon_temp = None
        output_temp = None
        
        try:
            # Vertex AI Imagen requires local file paths (Image.from_file expects a file path)
            # So we download from Bunny CDN URL to a temporary file
            logger.debug("Vertex AI Imagen requires local file path, downloading from Bunny CDN")
            
            # Download image from Bunny CDN URL to temporary file
            try:
                response = requests.get(tryon_image_url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as e:
                logger.error("Failed to download try-on image from Bunny CDN: %s", str(e))
                return Response(
                    {
                        'success': False,
                        'error': f'Failed to download try-on image from Bunny CDN: {str(e)}'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Create temporary file for input image
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
                tmp_file.write(response.content)
                tryon_temp = tmp_file.name

            logger.info("Try-on image downloaded and saved to temporary file: %s", tryon_temp)

            # Create temporary file for output image
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
                output_temp = tmp_file.name

            # Generate pose image using Vertex AI Imagen
            logger.info("Generating pose image with scene prompt: %s", scene_template.prompt[:100])
            generate_pose_image(
                input_image_path=tryon_temp,
                scene_prompt=scene_template.prompt,
                output_path=output_temp
            )

            logger.info("Pose image generated successfully: %s", output_temp)

            # Upload generated image to BunnyCDN
            bunny_service = get_bunny_storage_service()
            
            # Generate unique filename
            unique_id = str(uuid.uuid4())[:8]
            date_path = datetime.now().strftime('%Y/%m/%d')
            remote_path = f'poses/pose_generated/{date_path}/pose_{scene_template_id}_{tryon_id}_{unique_id}.png'
            
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
                logger.error("Failed to upload generated image to BunnyCDN")
                return Response(
                    {
                        'success': False,
                        'error': 'Failed to upload generated image to storage'
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            logger.info("Generated image uploaded to BunnyCDN: %s", generated_image_url)

            # Store generated image in database
            tryon_pose = TryonPoses.objects.create(
                user=request.user,
                tryon=tryon_request,
                scene_template=scene_template,
                generated_image_url=generated_image_url
            )
            logger.info(
                "Created TryonPoses record id=%s for user=%s tryon_id=%s scene_template_id=%s",
                tryon_pose.id,
                request.user.id,
                tryon_id,
                scene_template_id
            )

            return Response(
                {
                    'success': True,
                    'data': {
                        'id': tryon_pose.id,
                        'generated_image_url': generated_image_url,
                        'scene_template_id': scene_template_id,
                        'scene_template_name': scene_template.name,
                        'tryon_id': tryon_id,
                        'created_at': tryon_pose.created_at.isoformat()
                    }
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.exception("Error generating pose image: %s", str(e))
            return Response(
                {
                    'success': False,
                    'error': f'Failed to generate pose image: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            # Clean up temporary files
            try:
                if tryon_temp and os.path.exists(tryon_temp):
                    os.unlink(tryon_temp)
                if output_temp and os.path.exists(output_temp):
                    os.unlink(output_temp)
            except Exception as e:
                logger.warning("Failed to clean up temporary files: %s", str(e))


