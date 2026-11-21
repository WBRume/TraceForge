"""Prepare versioned raster and vector avatars for storage."""

from uuid import uuid4

from app.domains.auth.services import avatar_image, avatar_vector


def encode_avatar_upload(raw: bytes, media_type: str, resource_path: str) -> tuple[str, bytes]:
    """Return the new avatar URL and the encoded image bytes."""
    path = f"{resource_path}/{uuid4()}"
    if media_type == avatar_vector.SVG_MIME:
        image, viewport = avatar_vector.encode_avatar_svg(raw)
        return f"{path}.svg{viewport}", image
    return f"{path}.webp", avatar_image.encode_avatar_image(raw, media_type)
