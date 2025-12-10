"""
Admin configuration for Try-On App
"""

from django.contrib import admin
from tryon.models import TryonRequest
from django.contrib.auth import get_user_model
User = get_user_model()

@admin.register(TryonRequest)
class TryonRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'user_info', 'device_id', 'person_image_url', 'garment_image_url', 'generated_image_url', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__email', 'device_id']
    readonly_fields = ['created_at']

    def user_info(self, obj):
        if obj.user:
            return f"{obj.user.id} - {obj.user.email}"
        return "Anonymous"
    user_info.short_description = "User Information"