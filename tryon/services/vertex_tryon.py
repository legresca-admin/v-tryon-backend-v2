"""
Vertex AI Virtual Try-On Service

Based on prototype: /media/azazul/PRS/projects/video_generation/gemini/dress_trial/v-tryon_2.py
"""

import logging
import os
from typing import Tuple

import google.auth
from django.conf import settings
from google import genai
from google.auth.exceptions import DefaultCredentialsError
from google.genai.types import (
    Image as GenAIImage,
    ProductImage,
    RecontextImageConfig,
    RecontextImageSource,
)
from PIL import Image as PILImage


logger = logging.getLogger(__name__)


def check_credentials():
    """
    Check if Application Default Credentials are set up.
    Returns (credentials, project_id) if successful, None otherwise.
    """
    try:
        credentials, project_id = google.auth.default()
        logger.debug("Obtained ADC credentials for project_id=%s", project_id)
        return credentials, project_id
    except DefaultCredentialsError as e:
        logger.error("Application Default Credentials not found: %s", str(e))
        # Check if credentials file exists
        import os
        creds_file = os.path.expanduser('~/.config/gcloud/application_default_credentials.json')
        if os.path.exists(creds_file):
            logger.error("Credentials file exists at %s but cannot be loaded", creds_file)
        else:
            logger.error("Credentials file not found at %s", creds_file)
        return None, None
    except Exception as e:
        logger.error("Unexpected error checking credentials: %s", str(e), exc_info=True)
        return None, None


def create_vertex_client():
    """
    Create a Vertex-AI-backed Gen AI client.
    Requires:
      GOOGLE_GENAI_USE_VERTEXAI=true
      GOOGLE_CLOUD_PROJECT
      GOOGLE_CLOUD_LOCATION
      Application Default Credentials (ADC) set up
    """
    # Check required environment variables
    if not os.getenv("GOOGLE_GENAI_USE_VERTEXAI"):
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = settings.GOOGLE_GENAI_USE_VERTEXAI

    # If GOOGLE_APPLICATION_CREDENTIALS is set but empty, unset it to use ADC
    app_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if app_creds == "":
        logger.debug("GOOGLE_APPLICATION_CREDENTIALS is empty, unsetting to use ADC")
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    project = os.getenv("GOOGLE_CLOUD_PROJECT", settings.GOOGLE_CLOUD_PROJECT)
    location = os.getenv("GOOGLE_CLOUD_LOCATION", settings.GOOGLE_CLOUD_LOCATION)

    if not project or not location:
        logger.error(
            "Missing GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_LOCATION (project=%s, location=%s)",
            project,
            location,
        )
        raise ValueError("GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION must be set")

    # Check credentials
    creds, detected_project = check_credentials()
    if creds is None:
        error_msg = (
            "Authentication Error: Application Default Credentials not found.\n"
            f"Project configured: {project}\n"
            f"Location configured: {location}\n"
            "For local development:\n"
            "  1. Run: gcloud auth application-default login\n"
            "  2. Run: gcloud auth application-default set-quota-project <project-id>\n"
            "  3. Verify: gcloud config get-value project\n"
            "For server deployment:\n"
            "  Set GOOGLE_APPLICATION_CREDENTIALS to service account JSON key path."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    # Create the client
    client = genai.Client()
    logger.debug(
        "Created Vertex GenAI client for project=%s (detected_project=%s) location=%s",
        project,
        detected_project,
        location,
    )
    return client


def validate_and_preprocess_image(path: str) -> Tuple[str, Tuple[int, int]]:
    """
    Basic image validation / preprocessing hook.

    - Ensures image is loadable.
    - Converts to RGB if needed.
    - Optionally could resize/upscale in the future.

    Currently this function is intentionally conservative to avoid breaking
    existing behavior. It validates and normalizes mode, then saves back
    to the same path.
    """
    logger.debug("Validating image at path=%s", path)
    img = PILImage.open(path)
    if img.mode not in ("RGB", "RGBA"):
        logger.info("Converting image at %s from mode=%s to RGB", path, img.mode)
        img = img.convert("RGB")
        img.save(path)
    size = img.size
    logger.debug("Image %s validated with size=%sx%s", path, size[0], size[1])
    return path, size


def virtual_try_on(
    person_image_path: str,
    product_image_path: str,
    number_of_images: int = None,
    base_steps: int = None,
):
    """
    Call Vertex AI Virtual Try-On (virtual-try-on-preview-08-04).

    Args:
        person_image_path: local path to the person photo
        product_image_path: local path to the garment  / product photo
        number_of_images: number of images to generate (default from settings)
        base_steps: number of diffusion steps (default from settings)

    Returns:
        List of generated images
    """
    logger.info(
        "Starting virtual try-on person_image=%s product_image=%s requested_images=%s base_steps=%s",
        person_image_path,
        product_image_path,
        number_of_images,
        base_steps,
    )
    client = create_vertex_client()

    # Use config defaults if not provided
    if number_of_images is None:
        number_of_images = settings.TRYON_CONFIG['number_of_images']
    if base_steps is None:
        base_steps = settings.TRYON_CONFIG['base_steps']

    logger.debug(
        "Using virtual try-on config number_of_images=%s base_steps=%s",
        number_of_images,
        base_steps,
    )

    # Basic validation / preprocessing to guard against unreadable / odd formats
    person_image_path, _ = validate_and_preprocess_image(person_image_path)
    product_image_path, _ = validate_and_preprocess_image(product_image_path)

    # Build the request payload
    source = RecontextImageSource(
        person_image=GenAIImage.from_file(location=person_image_path),
        product_images=[
            ProductImage(
                product_image=GenAIImage.from_file(location=product_image_path)
            )
        ],
    )

    # Build configuration
    config_params = {}
    if number_of_images > 1:
        config_params["numberOfImages"] = number_of_images
    if base_steps is not None:
        config_params["baseSteps"] = base_steps
    # Disable watermark in generated images
    config_params["addWatermark"] = False

    config = RecontextImageConfig(**config_params) if config_params else None

    logger.info(
        "Calling Vertex virtual try-on model with numberOfImages=%s baseSteps=%s addWatermark=False",
        config_params.get("numberOfImages"),
        config_params.get("baseSteps"),
    )

    # Call the Virtual Try-On model
    response = client.models.recontext_image(
        model="virtual-try-on-preview-08-04",
        source=source,
        config=config,
    )

    generated = getattr(response, "generated_images", [])
    logger.info("Vertex virtual try-on completed, generated_images_count=%s", len(generated))

    # Return generated images
    return generated

