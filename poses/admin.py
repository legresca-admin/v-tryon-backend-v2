"""
Admin configuration for Poses App
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from poses.models import SceneTemplate, TryonPoses

User = get_user_model()


@admin.register(SceneTemplate)
class SceneTemplateAdmin(admin.ModelAdmin):
    """
    Admin interface for SceneTemplate model.
    """
    list_display = ['id', 'user_info', 'name', 'prompt_preview', 'sample_image', 'sample_image_url', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at', 'user']
    search_fields = ['name', 'prompt', 'user__email', 'user__username']
    readonly_fields = ['created_at', 'updated_at', 'sample_image_url']
    fields = ['user', 'name', 'prompt', 'sample_image', 'sample_image_url', 'created_at', 'updated_at']

    def user_info(self, obj):
        """
        Display user information in the list view.
        """
        if obj.user:
            return f"{obj.user.id} - {obj.user.email}"
        return "No User"
    user_info.short_description = "User Information"

    def prompt_preview(self, obj):
        """
        Display a truncated version of the prompt in the list view.
        """
        if obj.prompt:
            return obj.prompt[:100] + '...' if len(obj.prompt) > 100 else obj.prompt
        return '-'
    prompt_preview.short_description = 'Prompt Preview'


@admin.register(TryonPoses)
class TryonPosesAdmin(admin.ModelAdmin):
    """
    Admin interface for TryonPoses model.
    """
    list_display = [
        'id',
        'user_info',
        'tryon_info',
        'scene_template_info',
        'generated_image_url',
        'created_at',
        'updated_at'
    ]
    list_filter = ['created_at', 'updated_at', 'user', 'scene_template']
    search_fields = [
        'user__email',
        'user__username',
        'tryon__id',
        'scene_template__name',
        'generated_image_url'
    ]
    readonly_fields = ['created_at', 'updated_at']
    fields = [
        'user',
        'tryon',
        'scene_template',
        'generated_image_url',
        'created_at',
        'updated_at'
    ]

    def user_info(self, obj):
        """
        Display user information in the list view.
        """
        if obj.user:
            return f"{obj.user.id} - {obj.user.email}"
        return "No User"
    user_info.short_description = "User Information"

    def tryon_info(self, obj):
        """
        Display try-on request information in the list view.
        """
        if obj.tryon:
            return f"Tryon #{obj.tryon.id}"
        return "No Try-On"
    tryon_info.short_description = "Try-On Request"

    def scene_template_info(self, obj):
        """
        Display scene template information in the list view.
        """
        if obj.scene_template:
            return f"{obj.scene_template.name} (ID: {obj.scene_template.id})"
        return "No Scene Template"
    scene_template_info.short_description = "Scene Template"
