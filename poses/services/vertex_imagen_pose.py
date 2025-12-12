"""
Vertex AI Imagen 3 Pose Image Generation Service

Service for generating pose images based on scene template prompts and try-on images
using Vertex AI Imagen 3 with Subject Reference.
"""

import logging
from pathlib import Path
from typing import Optional

from django.conf import settings
from google import genai
from google.genai.types import (
    EditImageConfig,
    Image,
    SubjectReferenceConfig,
    SubjectReferenceImage,
    ControlReferenceConfig,
    ControlReferenceImage,
)

from tryon.services.vertex_tryon import create_vertex_client

logger = logging.getLogger(__name__)


def build_pose_prompt_from_scene(scene_prompt: str) -> str:
    """
    Build a prompt for pose generation from scene template prompt.
    
    Args:
        scene_prompt: The scene template prompt text
        
    Returns:
        Formatted prompt string for Vertex AI Imagen
    """
    base_identity = (
        "PERSON [1] in the reference image is the main subject. "
        "Keep PERSON [1]'s face, facial proportions, skin tone, hair, and "
        "clothing IDENTICAL to the reference image. Do NOT change their identity."
    )
    
    scene_block = (
        f"Scene and lighting around PERSON [1]: {scene_prompt}. "
        "Use cinematic, well-balanced lighting and composition that match this description, "
        "following the usual rules of professional photography. The background, environment, "
        "and lighting may change significantly, but PERSON [1] must remain unchanged."
    )
    
    garment_preservation = (
        "Garment preservation for PERSON [1]: Ensure all clothing and garments are properly "
        "worn and consistently displayed. Keep the exact same garment colors, patterns, "
        "and details as in the reference image. All garment details should appear as they "
        "would on a properly worn, real-world garment."
    )
    
    return (
        f"{base_identity}\n\n"
        f"{scene_block}\n\n"
        f"{garment_preservation}"
    )


def generate_pose_image(
    input_image_path: str,
    scene_prompt: str,
    output_path: str,
    *,
    model_name: Optional[str] = None,
) -> Path:
    """
    Generate a pose image using Vertex AI Imagen 3 with Subject Reference.

    Args:
        input_image_path: Path to the try-on generated image (subject reference).
        scene_prompt: Scene template prompt text.
        output_path: Where to save the generated image (PNG).
        model_name: Optional Imagen 3 model name; defaults to settings or
            "imagen-3.0-capability-001".

    Returns:
        Path to the generated image
    """
    logger.info(
        "Imagen 3 pose generation started input=%s output=%s",
        input_image_path,
        output_path,
    )

    input_path = Path(input_image_path)
    if not input_path.exists():
        logger.error("Input image does not exist at %s", input_path)
        raise FileNotFoundError(f"Input image not found: {input_path}")

    # Use the same Vertex-backed genai client as virtual_try_on
    client: genai.Client = create_vertex_client()

    imagen_model_name = model_name or getattr(
        settings,
        "IMAGEN_MODEL_NAME",
        "imagen-3.0-capability-001",
    )

    logger.debug("Using Imagen 3 model=%s", imagen_model_name)

    # Build prompt from scene template
    prompt = build_pose_prompt_from_scene(scene_prompt)
    
    # Build final prompt with explicit [1] subject reference
    final_prompt = (
        f"{prompt}\n\n"
        "PERSON [1] from the reference image is the main subject. "
        "Do not change PERSON [1]'s face or identity."
    )
    
    logger.info(
        "Imagen 3 prompt length=%s chars (with [1] subject reference)",
        len(final_prompt),
    )
    logger.debug("Imagen 3 prompt preview (first 500 chars): %s", final_prompt[:500])

    # Load local image as SubjectReferenceImage (identity anchor)
    logger.debug("Loading subject reference image from %s", input_path)
    ref_image = Image.from_file(location=str(input_path))

    subject_reference = SubjectReferenceImage(
        reference_id=1,
        reference_image=ref_image,
        config=SubjectReferenceConfig(
            subject_description="a photo of a person for virtual try-on",
            subject_type="SUBJECT_TYPE_PERSON",
        ),
    )

    # Additional face-lock: use a ControlReferenceImage with FACE_MESH to
    # strongly preserve facial geometry for PERSON [1].
    face_control_reference = ControlReferenceImage(
        reference_id=2,
        reference_image=ref_image,
        config=ControlReferenceConfig(
            control_type="CONTROL_TYPE_FACE_MESH",
        ),
    )

    logger.info(
        "Calling Imagen 3 edit_image with subject reference id=1 and "
        "face control reference id=2"
    )

    response = client.models.edit_image(
        model=imagen_model_name,
        prompt=final_prompt,
        reference_images=[subject_reference, face_control_reference],
        config=EditImageConfig(
            edit_mode="EDIT_MODE_DEFAULT",
            number_of_images=1,
            safety_filter_level="BLOCK_MEDIUM_AND_ABOVE",
            person_generation="ALLOW_ALL",
        ),
    )

    generated = getattr(response, "generated_images", [])
    if not generated:
        logger.error("Imagen 3 edit_image returned no generated_images")
        raise RuntimeError("No image generated by Imagen 3")

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    logger.debug("Saving Imagen 3 generated image to %s", output_path_obj)
    generated[0].image.save(location=str(output_path_obj))
    logger.info("Imagen 3 pose generation completed output=%s", output_path_obj)

    return output_path_obj

