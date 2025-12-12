"""
Serializers for Poses App
"""

from rest_framework import serializers
from poses.models import SceneTemplate, TryonPoses


class SceneTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for SceneTemplate model.
    Includes BunnyCDN URL for sample image.
    """
    user_email = serializers.EmailField(source='user.email', read_only=True)
    sample_image_url = serializers.URLField(read_only=True)

    class Meta:
        model = SceneTemplate
        fields = [
            'id',
            'user',
            'user_email',
            'name',
            'prompt',
            'sample_image',
            'sample_image_url',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'user', 'sample_image_url', 'created_at', 'updated_at']


class SceneGenerationRequestSerializer(serializers.Serializer):
    """
    Serializer for scene generation request.
    """
    scene_template_id = serializers.IntegerField(required=True, help_text="ID of the scene template")
    tryon_id = serializers.IntegerField(required=True, help_text="ID of the try-on request")


class TryonPosesSerializer(serializers.ModelSerializer):
    """Serializer for TryonPoses model."""
    scene_template_name = serializers.CharField(source='scene_template.name', read_only=True)
    tryon_id = serializers.IntegerField(source='tryon.id', read_only=True)
    
    class Meta:
        model = TryonPoses
        fields = '__all__'
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']
