"""
Admin configuration for User Rate Limits
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from .models import UserRateLimit

User = get_user_model()


@admin.register(UserRateLimit)
class UserRateLimitAdmin(admin.ModelAdmin):
    """Admin interface for managing user rate limits."""
    
    list_display = ('user', 'username', 'email', 'limit', 'used_count', 'remaining', 'is_exceeded', 'updated_at')
    list_filter = ('limit', 'created_at', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('used_count', 'remaining_display', 'created_at', 'updated_at')
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Rate Limit Configuration', {
            'fields': ('limit', 'used_count', 'remaining_display')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def username(self, obj):
        """Display username."""
        return obj.user.username
    username.short_description = 'Username'
    
    def email(self, obj):
        """Display email."""
        return obj.user.email
    email.short_description = 'Email'
    
    def remaining(self, obj):
        """Display remaining requests."""
        remaining = obj.get_remaining()
        if remaining is None:
            return 'Unlimited'
        return remaining
    remaining.short_description = 'Remaining'
    
    def is_exceeded(self, obj):
        """Display if limit is exceeded."""
        return obj.is_limit_exceeded()
    is_exceeded.boolean = True
    is_exceeded.short_description = 'Limit Exceeded'
    
    def remaining_display(self, obj):
        """Display remaining requests in detail view."""
        remaining = obj.get_remaining()
        if remaining is None:
            return 'Unlimited'
        return f"{remaining} requests remaining"
    remaining_display.short_description = 'Remaining Requests'
    
    actions = ['reset_usage']
    
    def reset_usage(self, request, queryset):
        """Admin action to reset usage count for selected users."""
        count = 0
        for rate_limit in queryset:
            rate_limit.reset_usage()
            count += 1
        self.message_user(request, f'Reset usage count for {count} user(s).')
    reset_usage.short_description = 'Reset usage count for selected users'
