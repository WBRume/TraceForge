from io import BytesIO

import pytest
from conftest import auth_headers, make_user
from PIL import Image, PngImagePlugin
from sqlalchemy.orm import Session

from app.domains.auth.models.user import User
from app.domains.auth.services import auth_service
from app.domains.auth.services.avatar_image import AVATAR_MAX_ANIMATION_FRAMES, AVATAR_MAX_UPLOAD_BYTES
from app.domains.task.services.avatar_service import build_default_avatar_svg

UPLOAD_PATH = "/api/auth/me/avatar/image"
PROFILE_PATH = "/api/auth/me"
PNG_HEADERS = {"Content-Type": "image/png"}
APNG_HEADERS = {"Content-Type": "image/apng"}


def _png(size: tuple[int, int] = (128, 128)) -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "original metadata")
    with Image.new("RGBA", size, (20, 100, 150, 128)) as image:
        image.paste((245, 10, 161, 255), (size[0] // 4, 0, size[0] // 4 + 1, size[1]))
        image.putpixel((0, 0), (33, 150, 100, 0))
        stream = BytesIO()
        image.save(stream, "PNG", pnginfo=info)
        return stream.getvalue()


def _apng(
    colors: list[tuple[int, int, int, int]], durations: list[int], size: tuple[int, int] = (12, 12), loop: int = 3
) -> bytes:
    frames = [Image.new("RGBA", size, color) for color in colors]
    stream = BytesIO()
    frames[0].save(
        stream,
        "PNG",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
    )
    return stream.getvalue()


def test_avatar_crop_survives_profile_read_and_is_served_without_pixel_loss(db, full_client):
    user = make_user(db, password="")
    headers = auth_headers(user)
    assert full_client.get(PROFILE_PATH, headers=headers).json()["avatar_svg"]

    submitted = _png()
    saved = full_client.put(UPLOAD_PATH, content=submitted, headers={**headers, **PNG_HEADERS})
    assert saved.status_code == 200
    profile = saved.json()
    assert profile["avatar_svg"] is None
    assert full_client.get(PROFILE_PATH, headers=headers).json()["avatar_url"] == profile["avatar_url"]
    assert auth_service.resolve_user_avatar_svg(user) is None

    photo = full_client.get(profile["avatar_url"])
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(photo.content)) as image, Image.open(BytesIO(submitted)) as original:
        assert image.size == original.size
        assert image.mode == original.mode
        assert image.tobytes() == original.tobytes()
        assert "Comment" not in image.info


def test_animated_crop_retains_frames_timing_transparency_and_loop_count(db, full_client):
    headers = auth_headers(make_user(db, password=""))
    colors = [(186, 43, 64, 255), (81, 160, 193, 128), (0, 0, 0, 0)]
    durations = [70, 150, 240]
    saved = full_client.put(UPLOAD_PATH, content=_apng(colors, durations), headers={**headers, **APNG_HEADERS})
    assert saved.status_code == 200
    profile = full_client.get(PROFILE_PATH, headers=headers).json()
    assert profile["avatar_url"] == saved.json()["avatar_url"]
    photo = full_client.get(profile["avatar_url"])
    assert photo.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(photo.content)) as image:
        assert image.n_frames == len(colors)
        assert image.info["loop"] == 3
        for index, color in enumerate(colors):
            image.seek(index)
            assert image.getpixel((6, 6)) == color
            assert image.info["duration"] == durations[index]


def test_vector_avatar_preserves_declarative_animation_and_is_served_in_isolation(db, full_client):
    headers = auth_headers(make_user(db, password=""))
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" data-avatar-crop="120 80 32 12 48">
      <svg width="120" height="80" viewBox="0 0 120 80" onload="ignored()">
        <style>@keyframes pulse { to { opacity: .5 } } rect { animation: pulse 1s infinite; }</style>
        <rect width="120" height="80" fill="#7399ae">
          <animate attributeName="fill" values="#7399ae;#e3b272" dur="1s" repeatCount="indefinite"/>
          <set attributeName="href" to="https://example.invalid/hidden"/>
        </rect>
        <g>
          <script>/* omitted from the avatar */</script>
          <image href="https://example.invalid/external.png"/>
        </g>
      </svg>
    </svg>"""
    saved = full_client.put(UPLOAD_PATH, content=svg, headers={**headers, "Content-Type": "image/svg+xml"})
    assert saved.status_code == 200
    profile = saved.json()
    assert profile["avatar_svg"] is None
    assert profile["avatar_url"].endswith(".svg#crop=120,80,32,12,48")
    path = profile["avatar_url"].partition("#")[0]
    response = full_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert "sandbox" in response.headers["content-security-policy"]
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "@keyframes pulse" in response.text
    assert 'attributeName="fill"' in response.text
    assert "onload" not in response.text
    assert "omitted from the avatar" not in response.text
    assert "example.invalid" not in response.text
    assert full_client.get(path.replace(".svg", ".webp")).status_code == 404


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
        pytest.param(_png(), "image/apng", 400, id="static-as-animation"),
        pytest.param(
            _apng(
                [(i, 0, 0, 255) for i in range(AVATAR_MAX_ANIMATION_FRAMES + 1)],
                [100] * (AVATAR_MAX_ANIMATION_FRAMES + 1),
            ),
            "image/apng",
            400,
            id="too-many-frames",
        ),
        pytest.param(b"", "image/tiff", 415, id="unsupported-type"),
        pytest.param(b"<svg/>", "image/svg+xml", 400, id="invalid-vector-crop"),
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
