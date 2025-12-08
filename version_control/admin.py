"""
Admin configuration for Version Control App
"""

from django.contrib import admin
from .models import AppVersion


@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    """Admin interface for App Version management"""
    
    list_display = [
        'version_number',
        'minimum_required_version',
        'force_update',
        'is_active',
        'release_date',
    ]
    
    list_filter = [
        'is_active',
        'force_update',
        'release_date',
    ]
    
    search_fields = [
        'version_number',
        'minimum_required_version',
        'release_notes',
    ]
    
    fieldsets = (
        ('Version Information', {
            'fields': (
                'version_number',
                'minimum_required_version',
                'is_active',
            )
        }),
        ('Update Settings', {
            'fields': (
                'force_update',
                'update_url',
                'update_message',
            )
        }),
        ('Release Information', {
            'fields': (
                'release_date',
                'release_notes',
            )
        }),
        ('Metadata', {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def get_readonly_fields(self, request, obj=None):
        """Make version_number readonly if object exists"""
        if obj:  # editing an existing object
            return self.readonly_fields + ['version_number']
        return self.readonly_fields
    
    actions = ['activate_versions', 'deactivate_versions']
    
    def activate_versions(self, request, queryset):
        """Activate selected versions"""
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} version(s) activated.')
    activate_versions.short_description = 'Activate selected versions'
    
    def deactivate_versions(self, request, queryset):
        """Deactivate selected versions"""
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} version(s) deactivated.')
    deactivate_versions.short_description = 'Deactivate selected versions'
