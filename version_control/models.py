"""
Version Control Models

Manages app version requirements and force update settings.
"""

from django.db import models
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


class AppVersion(models.Model):
    """
    App Version Control Model
    
    Manages app version requirements and force update settings.
    When the app checks its version against this model, it can determine
    if an update is required or if the app should be blocked.
    """
    
    # Version information (semantic versioning: major.minor.patch)
    version_number = models.CharField(
        max_length=20,
        unique=True,
        help_text="Current app version (e.g., '1.0.0', '1.2.3')"
    )
    
    # Minimum required version - apps below this version will be blocked
    minimum_required_version = models.CharField(
        max_length=20,
        help_text="Minimum app version required to use the app (e.g., '1.0.0')"
    )
    
    # Force update flag - if True, all apps must update regardless of version
    force_update = models.BooleanField(
        default=False,
        help_text="If True, all apps must update (blocks all versions below current)"
    )
    
    # Version status
    is_active = models.BooleanField(
        default=True,
        help_text="If False, this version configuration is disabled"
    )
    
    # Release information
    release_date = models.DateTimeField(
        default=timezone.now,
        help_text="When this version was released"
    )
    
    release_notes = models.TextField(
        blank=True,
        help_text="Release notes or changelog for this version"
    )
    
    # Update information
    update_url = models.URLField(
        blank=True,
        help_text="URL where users can download/update the app (App Store, Play Store, etc.)"
    )
    
    update_message = models.TextField(
        blank=True,
        default="A new version of the app is available. Please update to continue using the app.",
        help_text="Message shown to users when update is required"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-release_date', '-version_number']
        verbose_name = 'App Version'
        verbose_name_plural = 'App Versions'
    
    def __str__(self):
        return f"Version {self.version_number} (Min: {self.minimum_required_version})"
    
    @classmethod
    def get_current_version(cls):
        """
        Get the currently active version configuration.
        Returns the most recent active version.
        """
        try:
            return cls.objects.filter(is_active=True).latest('release_date')
        except cls.DoesNotExist:
            # Return a default version if none exists
            return cls.objects.create(
                version_number='1.0.0',
                minimum_required_version='1.0.0',
                force_update=False,
                is_active=True,
                release_notes='Initial version'
            )
    
    def compare_version(self, app_version):
        """
        Compare app version with current version.
        
        Args:
            app_version: Version string from the app (e.g., '1.0.0')
        
        Returns:
            dict with keys:
                - is_valid: bool - Can the app be used?
                - requires_update: bool - Does the app need to update?
                - is_blocked: bool - Is the app blocked from use?
                - message: str - Message to show to user
        """
        try:
            app_parts = [int(x) for x in app_version.split('.')]
            min_parts = [int(x) for x in self.minimum_required_version.split('.')]
            current_parts = [int(x) for x in self.version_number.split('.')]
        except (ValueError, AttributeError):
            # Invalid version format - assume update required
            return {
                'is_valid': False,
                'requires_update': True,
                'is_blocked': True,
                'message': 'Invalid app version format. Please update the app.',
                'current_version': self.version_number,
                'minimum_version': self.minimum_required_version
            }
        
        # Compare version numbers
        def version_less_than(v1, v2):
            """Check if v1 < v2"""
            for i in range(max(len(v1), len(v2))):
                v1_val = v1[i] if i < len(v1) else 0
                v2_val = v2[i] if i < len(v2) else 0
                if v1_val < v2_val:
                    return True
                elif v1_val > v2_val:
                    return False
            return False
        
        # Check if app version is below minimum required
        is_below_minimum = version_less_than(app_parts, min_parts)
        
        # Check if force update is enabled
        if self.force_update:
            is_below_current = version_less_than(app_parts, current_parts)
            if is_below_current:
                return {
                    'is_valid': False,
                    'requires_update': True,
                    'is_blocked': True,
                    'message': self.update_message or 'A new version is required. Please update the app.',
                    'current_version': self.version_number,
                    'minimum_version': self.minimum_required_version,
                    'update_url': self.update_url
                }
        
        # Check if app version is below minimum required
        if is_below_minimum:
            return {
                'is_valid': False,
                'requires_update': True,
                'is_blocked': True,
                'message': self.update_message or f'App version {app_version} is no longer supported. Please update to version {self.minimum_required_version} or higher.',
                'current_version': self.version_number,
                'minimum_version': self.minimum_required_version,
                'update_url': self.update_url
            }
        
        # App version is valid
        return {
            'is_valid': True,
            'requires_update': False,
            'is_blocked': False,
            'message': 'App version is up to date.',
            'current_version': self.version_number,
            'minimum_version': self.minimum_required_version
        }
