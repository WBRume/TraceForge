"""Validation and encoding for cropped profile photos."""

from io import BytesIO

from PIL import Image

AVATAR_MAX_SIDE = 512
# Allow a 512x512 RGBA PNG even when its pixels compress poorly.
AVATAR_MAX_UPLOAD_BYTES = 1100 * 1024
AVATAR_MAX_ANIMATION_FRAMES = 120
AVATAR_MAX_ANIMATION_PIXELS = 8_388_608
AVATAR_UPLOAD_FORMATS = {"image/webp": "WEBP", "image/png": "PNG", "image/apng": "PNG"}


class AvatarImageTooLargeError(ValueError):
    """The encoded avatar exceeds the storage size limit."""


def encode_avatar_image(raw: bytes, media_type: str) -> bytes:
    """Encode a square avatar crop as metadata-free, lossless WebP."""
    try:
        with Image.open(BytesIO(raw), formats=[AVATAR_UPLOAD_FORMATS[media_type]]) as image:
            if image.width != image.height or image.width > AVATAR_MAX_SIDE:
                raise ValueError("Expected a square avatar image up to 512 pixels per side")
            if media_type == "image/apng":
                return _encode_avatar_animation(image)
            if getattr(image, "is_animated", False):
                raise ValueError("Animated crops must use image/apng")
            image.load()
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            with image.convert("RGBA" if has_alpha else "RGB") as normalized:
                normalized.info.clear()
                output = BytesIO()
                normalized.save(output, format="WEBP", lossless=True, exact=True)
                return output.getvalue()
    except (Image.DecompressionBombError, EOFError, OSError, SyntaxError) as exc:
        raise ValueError("Invalid avatar image") from exc


def _encode_avatar_animation(image: Image.Image) -> bytes:
    # APNG may include a separate poster image before the animated frames.
    first = int(bool(image.info.get("default_image")))
    frame_count = getattr(image, "n_frames", 1) - first
    if (
        not 2 <= frame_count <= AVATAR_MAX_ANIMATION_FRAMES
        or frame_count * image.width * image.height > AVATAR_MAX_ANIMATION_PIXELS
    ):
        raise ValueError("Animated avatar exceeds the frame or pixel limit")

    loop = min(image.info.get("loop", 0), 65_535)
    frames = []
    durations = []
    for index in range(first, first + frame_count):
        image.seek(index)
        frame = image.convert("RGBA")
        frame.info.clear()
        frames.append(frame)
        durations.append(round(image.info.get("duration", 100)))

    output = BytesIO()
    frames[0].save(
        output,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        lossless=True,
        method=2,
        loop=loop,
        duration=durations,
    )
    if output.tell() > AVATAR_MAX_UPLOAD_BYTES:
        raise AvatarImageTooLargeError("Encoded animated avatar exceeds the size limit")
    return output.getvalue()
