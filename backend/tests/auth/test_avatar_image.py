from io import BytesIO

import pytest
from conftest import auth_headers, make_user
from PIL import Image, PngImagePlugin
from sqlalchemy.orm import Session

from app.domains.auth.models.user import User
from app.domains.auth.services import auth_service
from app.domains.auth.services.avatar_image import AVATAR_MAX_UPLOAD_BYTES
from app.domains.task.services.avatar_service import build_default_avatar_svg

UPLOAD_PATH = "/api/auth/me/avatar/image"
PROFILE_PATH = "/api/auth/me"
PNG_HEADERS = {"Content-Type": "image/png"}


def _png(size: tuple[int, int] = (128, 128)) -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "original metadata")
    with Image.new("RGBA", size, (20, 100, 150, 128)) as image:
        stream = BytesIO()
        image.save(stream, "PNG", pnginfo=info)
        return stream.getvalue()


def test_avatar_crop_survives_profile_read_and_is_served_as_webp(db, full_client):
    user = make_user(db, password="")
    headers = auth_headers(user)
    assert full_client.get(PROFILE_PATH, headers=headers).json()["avatar_svg"]

    saved = full_client.put(UPLOAD_PATH, content=_png(), headers={**headers, **PNG_HEADERS})
    assert saved.status_code == 200
    profile = saved.json()
    assert profile["avatar_svg"] is None
    assert full_client.get(PROFILE_PATH, headers=headers).json()["avatar_url"] == profile["avatar_url"]
    assert auth_service.resolve_user_avatar_svg(user) is None

    photo = full_client.get(profile["avatar_url"])
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(photo.content)) as image:
        assert image.size == (128, 128)
        assert image.getpixel((64, 64))[3] == 128
        assert "Comment" not in image.info


def test_replacing_a_photo_or_saving_a_template_retires_the_previous_url(db, full_client):
    user = make_user(db, password="")
    headers = auth_headers(user)
    first = full_client.put(UPLOAD_PATH, content=_png(), headers={**headers, **PNG_HEADERS}).json()
    photo = full_client.get(first["avatar_url"]).content
    second = full_client.put(UPLOAD_PATH, content=photo, headers={**headers, "Content-Type": "image/webp"}).json()
    assert second["avatar_url"] != first["avatar_url"]
    assert full_client.get(first["avatar_url"]).status_code == 404
    assert full_client.get(second["avatar_url"]).status_code == 200

    svg = build_default_avatar_svg(user.display_name, user.email, user.id, style="soft")
    saved = full_client.put("/api/auth/me/avatar", json={"avatar_svg": svg}, headers=headers)
    assert saved.status_code == 200
    assert saved.json()["avatar_url"] is None
    assert saved.json()["avatar_svg"].startswith("<svg ")
    assert full_client.get(second["avatar_url"]).status_code == 404
    assert user.avatar_image is None


@pytest.mark.parametrize(
    ("content", "media_type", "expected"),
    [
        pytest.param(b"invalid image", "image/webp", 400, id="undecodable"),
        pytest.param(_png((128, 64)), "image/png", 400, id="non-square"),
        pytest.param(_png((513, 513)), "image/png", 400, id="dimensions"),
        pytest.param(_png(), "image/webp", 400, id="mismatched-format"),
        pytest.param(b"", "image/svg+xml", 415, id="unsupported-type"),
        pytest.param(b"x" * (AVATAR_MAX_UPLOAD_BYTES + 1), "image/png", 413, id="oversized-body"),
    ],
)
def test_rejected_upload_keeps_the_saved_avatar(db, full_client, content, media_type, expected):
    headers = auth_headers(make_user(db, password=""))
    existing = full_client.put(UPLOAD_PATH, content=_png(), headers={**headers, **PNG_HEADERS}).json()["avatar_url"]

    rejected = full_client.put(UPLOAD_PATH, content=content, headers={**headers, "Content-Type": media_type})
    assert rejected.status_code == expected
    assert full_client.get(PROFILE_PATH, headers=headers).json()["avatar_url"] == existing


def test_avatar_upload_requires_login(full_client):
    assert full_client.put(UPLOAD_PATH, content=_png(), headers=PNG_HEADERS).status_code == 401


def test_stale_profile_backfill_does_not_overwrite_a_saved_photo(db):
    user = make_user(db, password="")
    with Session(db.get_bind()) as reader:
        stale_user = reader.get(User, user.id)
        assert stale_user.avatar_svg is None
        saved = auth_service.update_user_avatar_image(db, user, _png(), "image/png")

        loaded = auth_service.ensure_user_avatar_svg(reader, stale_user)

        assert loaded.avatar_url == saved.avatar_url
        assert loaded.avatar_svg is None
