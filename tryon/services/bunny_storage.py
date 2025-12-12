"""
BunnyCDN Storage Service for uploading images to BunnyCDN storage.
"""

import logging
from typing import Optional
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class BunnyStorageService:
    """
    Service for uploading files to BunnyCDN Storage.
    
    Uses BunnyCDN Storage API to upload files directly to storage zones.
    """
    
    def __init__(self):
        """Initialize BunnyCDN Storage service with credentials from Django settings."""
        self.storage_zone = getattr(settings, 'BUNNY_STORAGE_ZONE', '')
        self.access_key = getattr(settings, 'BUNNY_ACCESS_KEY', '')
        self.pull_zone = getattr(settings, 'BUNNY_PULL_ZONE', '')
        
        if not self.storage_zone or not self.access_key:
            logger.warning(
                "BunnyCDN credentials not configured. "
                "Set BUNNY_STORAGE_ZONE and BUNNY_ACCESS_KEY in environment variables or .env file."
            )
    
    def upload_file(
        self,
        file_path: str,
        remote_path: str,
        content_type: Optional[str] = None
    ) -> Optional[str]:
        """
        Upload a file to BunnyCDN Storage.
        
        Args:
            file_path: Local path to the file to upload
            remote_path: Path in BunnyCDN storage (e.g., 'tryon/person_images/image.jpg')
            content_type: MIME type of the file (optional, will be auto-detected)
        
        Returns:
            Full URL of the uploaded file if successful, None otherwise
        """
        if not self.storage_zone or not self.access_key:
            logger.error("BunnyCDN credentials not configured")
            return None
        
        # Construct the upload URL
        # Format: https://storage.bunnycdn.com/{storage_zone}/{remote_path}
        upload_url = f"https://storage.bunnycdn.com/{self.storage_zone}/{remote_path}"
        
        try:
            # Read file content
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Determine content type if not provided
            if not content_type:
                if file_path.lower().endswith('.jpg') or file_path.lower().endswith('.jpeg'):
                    content_type = 'image/jpeg'
                elif file_path.lower().endswith('.png'):
                    content_type = 'image/png'
                else:
                    content_type = 'application/octet-stream'
            
            # Upload to BunnyCDN
            headers = {
                'AccessKey': self.access_key,
                'Content-Type': content_type,
            }
            
            response = requests.put(upload_url, data=file_content, headers=headers, timeout=30)
            
            if response.status_code in [200, 201]:
                # Construct the public URL using pull zone
                if self.pull_zone:
                    # Remove protocol if present
                    pull_zone = self.pull_zone.replace('https://', '').replace('http://', '')
                    # Remove trailing slash
                    pull_zone = pull_zone.rstrip('/')
                    public_url = f"https://{pull_zone}/{remote_path}"
                else:
                    # Fallback: use storage URL format
                    public_url = f"https://storage.bunnycdn.com/{self.storage_zone}/{remote_path}"
                
                logger.info(
                    "Successfully uploaded file to BunnyCDN: %s -> %s",
                    file_path,
                    public_url
                )
                return public_url
            else:
                logger.error(
                    "Failed to upload file to BunnyCDN. Status: %d, Response: %s",
                    response.status_code,
                    response.text
                )
                return None
                
        except FileNotFoundError:
            logger.error("File not found: %s", file_path)
            return None
        except requests.RequestException as e:
            logger.error("Error uploading file to BunnyCDN: %s", str(e), exc_info=True)
            return None
        except Exception as e:
            logger.error("Unexpected error uploading file to BunnyCDN: %s", str(e), exc_info=True)
            return None
    
    def upload_file_from_bytes(
        self,
        file_bytes: bytes,
        remote_path: str,
        content_type: Optional[str] = None
    ) -> Optional[str]:
        """
        Upload file content from bytes to BunnyCDN Storage.
        
        Args:
            file_bytes: File content as bytes
            remote_path: Path in BunnyCDN storage (e.g., 'tryon/person_images/image.jpg')
            content_type: MIME type of the file (optional)
        
        Returns:
            Full URL of the uploaded file if successful, None otherwise
        """
        if not self.storage_zone or not self.access_key:
            logger.error("BunnyCDN credentials not configured")
            return None
        
        # Construct the upload URL
        upload_url = f"https://storage.bunnycdn.com/{self.storage_zone}/{remote_path}"
        
        try:
            # Determine content type if not provided
            if not content_type:
                if remote_path.lower().endswith('.jpg') or remote_path.lower().endswith('.jpeg'):
                    content_type = 'image/jpeg'
                elif remote_path.lower().endswith('.png'):
                    content_type = 'image/png'
                else:
                    content_type = 'application/octet-stream'
            
            # Upload to BunnyCDN
            headers = {
                'AccessKey': self.access_key,
                'Content-Type': content_type,
            }
            
            response = requests.put(upload_url, data=file_bytes, headers=headers, timeout=30)
            
            if response.status_code in [200, 201]:
                # Construct the public URL using pull zone
                if self.pull_zone:
                    # Remove protocol if present
                    pull_zone = self.pull_zone.replace('https://', '').replace('http://', '')
                    # Remove trailing slash
                    pull_zone = pull_zone.rstrip('/')
                    public_url = f"https://{pull_zone}/{remote_path}"
                else:
                    # Fallback: use storage URL format
                    public_url = f"https://storage.bunnycdn.com/{self.storage_zone}/{remote_path}"
                
                logger.info(
                    "Successfully uploaded file bytes to BunnyCDN: %s",
                    public_url
                )
                return public_url
            else:
                logger.error(
                    "Failed to upload file bytes to BunnyCDN. Status: %d, Response: %s",
                    response.status_code,
                    response.text
                )
                return None
                
        except requests.RequestException as e:
            logger.error("Error uploading file bytes to BunnyCDN: %s", str(e), exc_info=True)
            return None
        except Exception as e:
            logger.error("Unexpected error uploading file bytes to BunnyCDN: %s", str(e), exc_info=True)
            return None


# Singleton instance
_bunny_storage_service = None


def get_bunny_storage_service() -> BunnyStorageService:
    """Get or create the singleton BunnyCDN storage service instance."""
    global _bunny_storage_service
    if _bunny_storage_service is None:
        _bunny_storage_service = BunnyStorageService()
    return _bunny_storage_service

