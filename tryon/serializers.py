"""
Serializers for Try-On App
"""
from rest_framework import serializers
from .models import TryonRequest


class TryonRequestSerializer(serializers.ModelSerializer):
    """Serializer for TryonRequest model with validation."""
    
    class Meta:
        model = TryonRequest
        fields = '__all__'
        read_only_fields = ['id', 'user', 'created_at']
    
    def validate_device_id(self, value):
        """Validate device_id is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("device_id cannot be empty")
        return value.strip()
    
    def validate_person_image_url(self, value):
        """Validate person_image_url is a valid URL."""
        if not value:
            raise serializers.ValidationError("person_image_url is required")
        return value
    
    def validate_garment_image_url(self, value):
        """Validate garment_image_url is a valid URL."""
        if not value:
            raise serializers.ValidationError("garment_image_url is required")
        return value
    
    def validate_generated_image_url(self, value):
        """Validate generated_image_url is a valid URL."""
        if not value:
            raise serializers.ValidationError("generated_image_url is required")
        return value
    
    def create(self, validated_data):
        """Create TryonRequest instance with user from context."""
        # Get user from context if available
        user = self.context.get('user')
        if not user:
            raise serializers.ValidationError("User is required")
        validated_data['user'] = user
        return super().create(validated_data)
