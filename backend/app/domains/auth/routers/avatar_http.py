"""HTTP handling shared by profile and workspace avatar routes."""

from typing import Literal

from fastapi import HTTPException, Request, Response

from app.domains.auth.services import avatar_image, avatar_vector

AvatarExtension = Literal["webp", "svg"]


async def read_avatar_upload(request: Request) -> tuple[bytes, str]:
    """Read an editor-generated crop within the avatar upload limit."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in avatar_image.AVATAR_UPLOAD_FORMATS and media_type != avatar_vector.SVG_MIME:
        raise HTTPException(status_code=415, detail="Expected a PNG, WebP, APNG, or SVG avatar image")

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > avatar_image.AVATAR_MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Avatar image exceeds the upload limit")
        raw.extend(chunk)
    return bytes(raw), media_type


def avatar_image_response(image: bytes | None, extension: AvatarExtension) -> Response:
    """Serve an avatar to an image element and isolate SVG content."""
    if image is None:
        raise HTTPException(status_code=404, detail="Avatar image not found")

    headers = {"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"}
    if extension == "svg":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        return Response(image, media_type=avatar_vector.SVG_MIME, headers=headers)
    return Response(image, media_type="image/webp", headers=headers)
