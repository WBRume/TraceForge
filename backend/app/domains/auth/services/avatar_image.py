"""Validation and encoding for cropped profile photos."""

from io import BytesIO

from PIL import Image

AVATAR_MAX_SIDE = 512
# Allow a 512x512 RGBA PNG when the browser's canvas cannot encode WebP.
AVATAR_MAX_UPLOAD_BYTES = 1100 * 1024
AVATAR_UPLOAD_FORMATS = {"image/webp": "WEBP", "image/png": "PNG"}


def encode_avatar_image(raw: bytes, media_type: str) -> bytes:
    """Convert a small, static, square crop to metadata-free WebP."""
    try:
        with Image.open(BytesIO(raw), formats=[AVATAR_UPLOAD_FORMATS[media_type]]) as image:
            if image.width != image.height or image.width > AVATAR_MAX_SIDE or getattr(image, "is_animated", False):
                raise ValueError("Expected a square avatar image up to 512 pixels per side")
            image.load()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            with image.convert("RGBA" if has_alpha else "RGB") as normalized:
                normalized.info.clear()
                output = BytesIO()
                normalized.save(output, format="WEBP", quality=86)
                return output.getvalue()
    except (Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise ValueError("Invalid avatar image") from exc
