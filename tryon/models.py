"""
Models for Try-On App
"""

# Version control models have been moved to version_control app
# models.py
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class TryonRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tryon_requests')
    device_id = models.CharField(max_length=255)
    person_image_url = models.URLField(max_length=500)
    garment_image_url = models.URLField(max_length=500)
    generated_image_url = models.URLField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"TryonRequest #{self.id} | User: {self.user.id} - {self.user.email} | Device: {self.device_id}"

