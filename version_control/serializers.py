"""
Serializers for Version Control App
"""

from rest_framework import serializers
from .models import AppVersion


class AppVersionSerializer(serializers.ModelSerializer):
    """Serializer for App Version model"""
    
    class Meta:
        model = AppVersion
        fields = [
            'version_number',
            'minimum_required_version',
            'force_update',
            'release_date',
            'release_notes',
            'update_url',
            'update_message',
        ]


class VersionCheckResponseSerializer(serializers.Serializer):
    """Serializer for version check API response"""
    
    current_version = serializers.CharField()
    minimum_required_version = serializers.CharField()
    force_update = serializers.BooleanField()
    is_valid = serializers.BooleanField()
    requires_update = serializers.BooleanField()
    is_blocked = serializers.BooleanField()
    message = serializers.CharField()
    update_url = serializers.URLField(required=False, allow_blank=True)
    release_notes = serializers.CharField(required=False, allow_blank=True)

