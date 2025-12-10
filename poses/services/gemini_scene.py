"""
Gemini Scene Image Generation Service

Service for generating images based on scene template prompts and try-on images.
"""

import logging
import os
import time
import threading
import tempfile
from io import BytesIO

from google import genai
from google.genai.types import GenerateContentConfig, ImageConfig
from PIL import Image as PILImage
from django.conf import settings

logger = logging.getLogger(__name__)


def ensure_9_16_aspect_ratio(img: PILImage.Image) -> PILImage.Image:
    """
    Post-process image to ensure 9:16 aspect ratio.
    If image is not 9:16, crops/resizes to match.
    
    Args:
        img: PIL Image object
        
    Returns:
        PIL Image with 9:16 aspect ratio
    """
    current_width, current_height = img.size
    target_ratio = 9 / 16  # 0.5625
    current_ratio = current_width / current_height
    
    # Check if already close to 9:16 (within 2% tolerance)
    if abs(current_ratio - target_ratio) < 0.02:
        logger.debug("Image already has 9:16 aspect ratio (%sx%s)", current_width, current_height)
        return img
    
    logger.info(
        "Image aspect ratio is %s (current: %sx%s), adjusting to 9:16",
        f"{current_ratio:.3f}",
        current_width,
        current_height
    )
    
    # Calculate target dimensions maintaining quality
    if current_ratio > target_ratio:
        # Image is wider than 9:16 - crop width (center crop)
        target_height = current_height
        target_width = int(target_height * target_ratio)
        left = (current_width - target_width) // 2
        img = img.crop((left, 0, left + target_width, target_height))
        logger.info("Cropped width: %sx%s -> %sx%s", current_width, current_height, target_width, target_height)
    else:
        # Image is taller than 9:16 - crop height (center crop)
        target_width = current_width
        target_height = int(target_width / target_ratio)
        top = (current_height - target_height) // 2
        img = img.crop((0, top, target_width, top + target_height))
        logger.info("Cropped height: %sx%s -> %sx%s", current_width, current_height, target_width, target_height)
    
    return img


def create_gemini_client():
    """Create Gemini API client (not Vertex AI)"""
    api_key = getattr(settings, 'GEMINI_API_KEY', None)
    if not api_key:
        raise ValueError("GEMINI_API_KEY must be set in settings")

    # Log partial key for debugging – avoid full key in logs
    logger.debug("Using Gemini API key prefix=%s suffix=%s", api_key[:8], api_key[-4:])

    # Temporarily disable Vertex AI mode for Gemini API
    original_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI")
    if original_vertex:
        os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
    
    try:
        client = genai.Client(api_key=api_key)
        return client
    finally:
        # Restore Vertex AI setting
        if original_vertex:
            os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = original_vertex


def build_scene_prompt(scene_prompt: str) -> str:
    """
    Build a JSON prompt for scene generation based on scene template prompt.
    
    Args:
        scene_prompt: The scene template prompt text
        
    Returns:
        JSON string prompt for Gemini API
    """
    prompt = {
        "instruction": f"Transform this image to match the following scene: {scene_prompt}. "
                      f"Preserve the person's appearance, clothing, and body proportions exactly. "
                      f"Only change the background, lighting, and scene context to match the description. "
                      f"Keep the person in the same pose and position.",
        "style": {
            "scene": scene_prompt,
            "preserve": [
                "person's face and features",
                "clothing details and fit",
                "body proportions",
                "pose and position"
            ],
            "modify": [
                "background",
                "lighting",
                "scene context",
                "environmental elements"
            ]
        }
    }
    
    import json
    return json.dumps(prompt, indent=2, ensure_ascii=False)


def generate_scene_image(
    input_image_path: str,
    scene_prompt: str,
    output_path: str,
    model_name: str = None,
    image_quality: str = "1K",
    timeout: int = 240,
    max_retries: int = 3
) -> PILImage.Image:
    """
    Generate an image based on scene template prompt and try-on image using Gemini.

    Args:
        input_image_path: Path to the try-on generated image
        scene_prompt: Scene template prompt text
        output_path: Where to save the generated image
        model_name: Gemini model to use (default from settings)
        image_quality: "1K", "2K", or "4K" (default: "1K")
        timeout: Request timeout in seconds (default: 240)
        max_retries: Number of retry attempts (default: 3)

    Returns:
        PIL Image object
    """
    logger.info("Scene image generation started")
    logger.info("Input image=%s output_path=%s scene_prompt=%s", input_image_path, output_path, scene_prompt[:100])

    client = create_gemini_client()
    logger.debug("Gemini client created")

    # Use config defaults if not provided
    if model_name is None:
        model_name = getattr(settings, 'TRYON_CONFIG', {}).get('gemini_model', 'gemini-2.0-flash-exp')

    logger.info(
        "Gemini config model=%s quality=%s timeout=%ss max_retries=%s",
        model_name,
        image_quality,
        timeout,
        max_retries,
    )

    # Load input image
    logger.debug("Loading input image from %s", input_image_path)
    input_img = PILImage.open(input_image_path).convert("RGB")
    original_size = input_img.size
    logger.info("Image loaded width=%s height=%s", original_size[0], original_size[1])

    # Resize large images to prevent timeout
    MAX_SIZE = 1024
    if max(original_size) > MAX_SIZE:
        logger.warning("Image too large, resizing for faster processing (max=%s)", MAX_SIZE)
        ratio = MAX_SIZE / max(original_size)
        new_size = (int(original_size[0] * ratio), int(original_size[1] * ratio))
        input_img = input_img.resize(new_size, PILImage.Resampling.LANCZOS)
        logger.info(
            "Resized image to width=%s height=%s for faster API processing",
            input_img.size[0],
            input_img.size[1],
        )

    # Build prompt
    json_prompt = build_scene_prompt(scene_prompt)
    logger.debug("Prompt preview (first 200 chars): %s", json_prompt[:200])

    # Configure for high quality output
    config = GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=ImageConfig(
            aspect_ratio="9:16",
            image_size=image_quality,
        ),
    )
    logger.debug("Gemini content config created")

    # Retry logic with exponential backoff
    last_exception = None
    for attempt in range(1, max_retries + 1):
        logger.info("Gemini API attempt %s/%s started", attempt, max_retries)

        try:
            start_time = time.time()

            # Run API call in a thread with timeout handling
            logger.info("Calling Gemini API in background thread")
            result_container = {'response': None, 'exception': None, 'completed': False}
            
            def api_thread():
                """Thread target that actually calls Gemini."""
                try:
                    logger.debug(
                        "[thread] API thread started model=%s quality=%s prompt_len=%s img_size=%sx%s",
                        model_name,
                        image_quality,
                        len(json_prompt),
                        input_img.size[0],
                        input_img.size[1],
                    )
                    result_container['response'] = client.models.generate_content(
                        model=model_name,
                        contents=[json_prompt, input_img],
                        config=config,
                    )
                    logger.info("[thread] API call completed successfully")
                except Exception as e:
                    logger.exception("[thread] API call raised exception: %r", e)
                    result_container['exception'] = e
                finally:
                    result_container['completed'] = True
            
            # Start API call in separate thread
            api_thread_obj = threading.Thread(target=api_thread, daemon=True)
            api_thread_obj.start()
            logger.info(
                "Waiting for API response (timeout=%ss, thread_id=%s)",
                timeout,
                api_thread_obj.ident,
            )

            # Wait for completion or timeout
            check_interval = 15
            last_progress_time = 0
            waited_time = 0
            
            while api_thread_obj.is_alive() and waited_time < timeout:
                remaining = min(check_interval, timeout - waited_time)
                try:
                    api_thread_obj.join(timeout=remaining)
                except Exception as e:
                    logger.exception("Unexpected error during thread join: %r", e)
                    raise
                
                waited_time = time.time() - start_time

                # Check if thread completed
                if result_container['completed']:
                    logger.info(
                        "API thread completed at %.1fs alive=%s has_response=%s has_exception=%s",
                        waited_time,
                        api_thread_obj.is_alive(),
                        result_container["response"] is not None,
                        result_container["exception"] is not None,
                    )
                    break

                # Log progress every 30 seconds
                if api_thread_obj.is_alive() and waited_time < timeout:
                    if waited_time - last_progress_time >= 30:
                        logger.info(
                            "Gemini API still running: %.0fs / %ss elapsed",
                            waited_time,
                            timeout,
                        )
                        last_progress_time = waited_time

            elapsed_time = time.time() - start_time
            logger.info(
                "Post-wait state attempt=%s elapsed=%.1fs alive=%s completed=%s has_response=%s has_exception=%s",
                attempt,
                elapsed_time,
                api_thread_obj.is_alive(),
                result_container["completed"],
                result_container["response"] is not None,
                result_container["exception"] is not None,
            )

            # Check if there was an exception FIRST
            if result_container['exception']:
                logger.warning(
                    "Gemini API returned error after %.1fs: %r",
                    elapsed_time,
                    result_container["exception"],
                )
                raise result_container['exception']
            
            # Check if thread is still alive (timed out)
            if api_thread_obj.is_alive() and not result_container['completed']:
                logger.error("Gemini API TIMEOUT after %.1fs", elapsed_time)
                if attempt < max_retries:
                    backoff_delay = min(2 ** attempt, 10)
                    logger.info("Retrying Gemini API in %ss", backoff_delay)
                    time.sleep(backoff_delay)
                    continue
                else:
                    raise TimeoutError(f"Request timed out after {elapsed_time:.1f}s (timeout limit: {timeout}s)")
            
            # Get the response
            response = result_container['response']
            if response is None:
                raise RuntimeError("Gemini API call returned None")

            logger.info("Processing Gemini response (elapsed=%.1fs)", elapsed_time)

            # Extract generated image
            logger.debug("Extracting image from Gemini response")

            # Try response.parts first
            for part in response.parts:
                img = part.as_image()
                if img is not None:
                    logger.info("Image extracted from response.parts, saving to %s", output_path)
                    # Convert to PIL if needed
                    if not isinstance(img, PILImage.Image):
                        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                            tmp_path = tmp_file.name
                        try:
                            img.save(tmp_path)
                            img = PILImage.open(tmp_path)
                            os.unlink(tmp_path)
                        except Exception as e:
                            try:
                                if os.path.exists(tmp_path):
                                    os.unlink(tmp_path)
                                img_bytes = BytesIO()
                                img.save(img_bytes)
                                img_bytes.seek(0)
                                img = PILImage.open(img_bytes)
                            except Exception as e2:
                                logger.error("Failed to convert to PIL: %s, %s", e, e2)
                                raise
                    # Post-process to ensure 9:16 aspect ratio
                    img = ensure_9_16_aspect_ratio(img)
                    img.save(output_path)
                    logger.info("Image saved successfully")
                    logger.info("Scene image generation completed")
                    return img

            # Fallback: try the candidates pattern
            logger.warning("No image in response.parts, trying candidates fallback...")
            if hasattr(response, 'candidates') and len(response.candidates) > 0:
                for part in response.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and part.inline_data.data:
                        logger.info("Image found in candidates[0].content.parts")
                        img = PILImage.open(BytesIO(part.inline_data.data))
                        logger.info("Decoded image from candidates with size=%sx%s", img.size[0], img.size[1])
                        # Post-process to ensure 9:16 aspect ratio
                        img = ensure_9_16_aspect_ratio(img)
                        logger.info("Saving image to %s", output_path)
                        img.save(output_path)
                        logger.info("Image saved successfully, scene image generation completed")
                        return img

            raise RuntimeError("No image returned from model response")

        except Exception as e:
            last_exception = e
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0

            logger.exception("Error during Gemini scene generation: %s", e)
            logger.info("Time elapsed before error: %.1fs", elapsed_time)

            # Check error type
            error_str = str(e).lower()
            is_timeout = isinstance(e, TimeoutError) or 'timeout' in error_str or 'timed out' in error_str
            is_network = (
                'network' in error_str
                or 'connection' in error_str
                or 'unavailable' in error_str
                or '503' in error_str
                or '502' in error_str
            )
            is_rate_limit = (
                '429' in error_str
                or 'rate limit' in error_str
                or 'quota' in error_str
                or 'resource exhausted' in error_str
            )

            if attempt < max_retries:
                # Calculate backoff delay
                if is_rate_limit:
                    backoff_delay = min(60 * (2 ** (attempt - 1)), 300)
                    logger.warning("Rate limit detected, backing off for %ss (attempt=%s)", backoff_delay, attempt)
                else:
                    backoff_delay = min(2 ** attempt, 10)
                    logger.info("Retrying in %ss (attempt=%s)", backoff_delay, attempt)

                time.sleep(backoff_delay)
            else:
                # Last attempt failed
                logger.error("Scene generation failed after %s attempts. Last error=%s", max_retries, e)

                # Raise specific error types
                if is_timeout:
                    raise TimeoutError(f"Request timed out after {elapsed_time:.1f}s (timeout limit: {timeout}s). Last error: {e}")
                elif is_rate_limit:
                    raise RuntimeError(f"Rate limit exceeded after {elapsed_time:.1f}s. Please wait before retrying. Last error: {e}")
                elif is_network:
                    raise ConnectionError(f"Network error after {elapsed_time:.1f}s. Last error: {e}")
                else:
                    raise RuntimeError(f"Failed after {max_retries} attempts. Last error after {elapsed_time:.1f}s: {e}")

    # Should not reach here
    raise RuntimeError(f"Failed to generate image after {max_retries} attempts. Last error: {last_exception}")

