"""
User Rate Limit Models
"""

from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class UserRateLimit(models.Model):
    """
    Rate limit configuration for users.
    Admin can set a custom limit for each user.
    Once the limit is reached, user cannot generate more images until admin resets.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='rate_limit',
        unique=True
    )
    limit = models.PositiveIntegerField(
        default=0,
        help_text='Maximum number of try-on requests allowed for this user. Set to 0 for unlimited.'
    )
    used_count = models.PositiveIntegerField(
        default=0,
        help_text='Current number of try-on requests used by this user'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Rate Limit'
        verbose_name_plural = 'User Rate Limits'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.used_count}/{self.limit if self.limit > 0 else '∞'}"

    def is_limit_exceeded(self):
        """Check if user has exceeded their rate limit."""
        if self.limit == 0:
            return False  # Unlimited
        return self.used_count >= self.limit

    def get_remaining(self):
        """Get remaining requests for this user."""
        if self.limit == 0:
            return None  # Unlimited
        return max(0, self.limit - self.used_count)

    def increment_usage(self):
        """Increment the usage count."""
        self.used_count += 1
        self.save(update_fields=['used_count', 'updated_at'])

    def reset_usage(self):
        """Reset the usage count to 0."""
        self.used_count = 0
        self.save(update_fields=['used_count', 'updated_at'])
