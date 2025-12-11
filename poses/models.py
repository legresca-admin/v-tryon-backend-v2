"""
Models for Poses App
"""

import logging
import uuid
from datetime import datetime
from io import BytesIO
from django.db import models
from django.contrib.auth import get_user_model
from PIL import Image
from tryon.services.bunny_storage import get_bunny_storage_service

User = get_user_model()
logger = logging.getLogger(__name__)


class SceneTemplate(models.Model):
    """
    Scene template model for storing scene configurations with prompts and sample images.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='scene_templates',
        help_text="User who created this scene template"
    )
    name = models.CharField(max_length=255, help_text="Name of the scene template")
    prompt = models.TextField(help_text="Prompt description for the scene")
    sample_image = models.ImageField(
        upload_to='poses/scene_templates/',
        null=True,
        blank=True,
        help_text="Sample image for the scene template (optional, local storage)"
    )
    sample_image_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="BunnyCDN URL for the sample image"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Scene Template'
        verbose_name_plural = 'Scene Templates'

    def __str__(self):
        return f"{self.name} (ID: {self.id}) | User: {self.user.id} - {self.user.email}"

    def _upload_image_to_bunny(self):
        """
        Upload sample_image to BunnyCDN if it exists and sample_image_url is not set.
        Called from save() method.
        """
        # Skip if no image
        if not self.sample_image:
            return
        
        # Skip if URL already exists (prevents re-uploading)
        if self.sample_image_url:
            return
        
        try:
            bunny_service = get_bunny_storage_service()
            
            # Read file content
            if hasattr(self.sample_image, 'read'):
                self.sample_image.seek(0)
                file_bytes = self.sample_image.read()
            else:
                # If it's a path, read from file system
                with open(self.sample_image.path, 'rb') as f:
                    file_bytes = f.read()
            
            # Detect image format from file content using PIL
            try:
                img = Image.open(BytesIO(file_bytes))
                pil_format = img.format
                if pil_format:
                    format_map = {
                        'JPEG': 'jpg',
                        'PNG': 'png',
                        'GIF': 'gif',
                        'WEBP': 'webp',
                        'JFIF': 'jpg',
                    }
                    file_extension = format_map.get(pil_format, 'jpg')
                else:
                    image_name = self.sample_image.name
                    file_extension = image_name.split('.')[-1].lower() if '.' in image_name else 'jpg'
                    if file_extension in ['jfif', 'jpe']:
                        file_extension = 'jpg'
            except Exception as img_error:
                logger.warning(
                    "Could not detect image format from content for SceneTemplate ID: %s - %s. Using filename.",
                    self.pk or 'new',
                    str(img_error)
                )
                image_name = self.sample_image.name
                file_extension = image_name.split('.')[-1].lower() if '.' in image_name else 'jpg'
                if file_extension in ['jfif', 'jpe']:
                    file_extension = 'jpg'
            
            # Generate unique filename
            unique_id = str(uuid.uuid4())[:8]
            template_id = self.pk or 'new'
            date_path = datetime.now().strftime('%Y/%m/%d')
            remote_path = f'poses/scene_templates/{date_path}/template_{template_id}_{unique_id}.{file_extension}'
            
            # Determine content type
            content_type = None
            if file_extension.lower() in ['jpg', 'jpeg']:
                content_type = 'image/jpeg'
            elif file_extension.lower() == 'png':
                content_type = 'image/png'
            elif file_extension.lower() == 'gif':
                content_type = 'image/gif'
            elif file_extension.lower() == 'webp':
                content_type = 'image/webp'
            else:
                content_type = 'image/jpeg'
            
            # Upload to BunnyCDN
            bunny_url = bunny_service.upload_file_from_bytes(
                file_bytes=file_bytes,
                remote_path=remote_path,
                content_type=content_type
            )
            
            if bunny_url:
                self.sample_image_url = bunny_url
                logger.info(
                    "Successfully uploaded image to BunnyCDN for SceneTemplate ID: %s -> %s",
                    template_id,
                    bunny_url
                )
            else:
                logger.error(
                    "Failed to upload image to BunnyCDN for SceneTemplate ID: %s",
                    template_id
                )
                
        except Exception as e:
            logger.error(
                "Error uploading image to BunnyCDN for SceneTemplate: %s",
                str(e),
                exc_info=True
            )

    def save(self, *args, **kwargs):
        """
        Override save to upload image to BunnyCDN after saving.
        Works for admin panel, API, and direct model saves.
        """
        # Check if image was changed (for updates)
        image_changed = False
        is_new = not self.pk
        
        if self.pk:
            try:
                old_instance = SceneTemplate.objects.get(pk=self.pk)
                if old_instance.sample_image != self.sample_image:
                    image_changed = True
                    # Clear old URL when image changes
                    self.sample_image_url = None
            except SceneTemplate.DoesNotExist:
                pass
        
        # Save first to get the ID
        super().save(*args, **kwargs)
        
        # Upload to BunnyCDN if image exists and URL is not set
        # For new instances or when image is changed
        if self.sample_image and (is_new or image_changed or not self.sample_image_url):
            self._upload_image_to_bunny()
            # Save again to update the URL
            if self.sample_image_url:
                super().save(update_fields=['sample_image_url'])


class TryonPoses(models.Model):
    """
    Model for storing generated pose images based on try-on requests and scene templates.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='tryon_poses',
        help_text="User who generated this pose image"
    )
    tryon = models.ForeignKey(
        'tryon.TryonRequest',
        on_delete=models.CASCADE,
        related_name='pose_images',
        help_text="The try-on request this pose image is based on"
    )
    scene_template = models.ForeignKey(
        SceneTemplate,
        on_delete=models.CASCADE,
        related_name='scene_template_poses',
        help_text="The scene template used to generate this pose image"
    )
    generated_image_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="BunnyCDN URL for the generated pose image"
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending',
        help_text="Status of pose generation"
    )
    error_message = models.TextField(blank=True, null=True, help_text="Error message if generation failed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'TryOn Pose'
        verbose_name_plural = 'TryOn Poses'
   

    def __str__(self):
        return (
            f"TryonPose #{self.id} | User: {self.user.id} - {self.user.email} | "
            f"Tryon: {self.tryon.id} | Scene: {self.scene_template.name}"
        )


