from io import BytesIO
from xml.etree.ElementTree import canonicalize

import pytest
from conftest import auth_headers, make_user
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import sessionmaker

from app.dependencies import get_db
from app.domains.auth.models.user import Workspace, WorkspaceMember, WorkspaceRole
from app.domains.workspace.routers import workspace as workspace_router

PNG = {"Content-Type": "image/png"}


@pytest.fixture
def workspace_client(full_app, db):
    full_app.include_router(workspace_router.router, prefix="/api")
    sessions = sessionmaker(bind=db.get_bind())

    def get_test_db():
        with sessions() as session:
            yield session

    full_app.dependency_overrides[get_db] = get_test_db
    return TestClient(full_app)


@pytest.fixture
def workspace_avatar_setup(db):
    owner = make_user(db, password="", display_name="Workspace Owner")
    manager = make_user(db, email="manager@example.com", password="")
    viewer = make_user(db, email="viewer@example.com", password="")
    ws = Workspace(name="Test workspace", owner_id=owner.id)
    other = Workspace(name="Other workspace", owner_id=owner.id)
    db.add_all([ws, other])
    db.flush()
    db.add_all(
        [
            WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER),
            WorkspaceMember(workspace_id=other.id, user_id=owner.id, role=WorkspaceRole.OWNER),
            WorkspaceMember(
                workspace_id=ws.id,
                user_id=manager.id,
                role=WorkspaceRole.DEVELOPER,
                permissions_json='["MANAGE_MEMBERS"]',
            ),
            WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER),
        ]
    )
    db.commit()
    return (
        f"/api/workspaces/{ws.id}",
        f"/api/workspaces/{other.id}",
        [auth_headers(user) for user in (owner, manager, viewer)],
    )


def test_workspace_avatar_template_is_independent_and_uses_workspace_permissions(
    workspace_client, workspace_avatar_setup
):
    path, other, (owner, manager, viewer) = workspace_avatar_setup
    client = workspace_client
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64"/></svg>'
    personal_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="32"/></svg>'
    personal = client.put("/api/auth/me/avatar", json={"avatar_svg": personal_svg}, headers=owner)
    assert personal.status_code == 200
    personal_svg = personal.json()["avatar_svg"]

    assert client.get(path, headers=owner).json()["avatar_svg"] is None
    assert client.get(path, headers=manager).json()["can_edit_avatar"] is True
    assert client.get(path, headers=viewer).json()["can_edit_avatar"] is False
    assert client.put(f"{path}/avatar", json={"avatar_svg": svg}, headers=viewer).status_code == 403
    assert client.put(f"{path}/avatar/image", content=b"", headers={**viewer, **PNG}).status_code == 403
    assert client.put(f"{other}/avatar", json={"avatar_svg": svg}, headers=manager).status_code == 403

    response = client.put(f"{path}/avatar", json={"avatar_svg": svg}, headers=manager)
    assert response.status_code == 200
    saved = response.json()
    assert saved["avatar_svg"] and saved["avatar_url"] is None
    assert client.get(path, headers=viewer).json()["avatar_svg"] == saved["avatar_svg"]
    listed = {row["id"]: row for row in client.get("/api/workspaces", headers=owner).json()}
    assert listed[path.rsplit("/", 1)[1]]["avatar_svg"] == saved["avatar_svg"]
    assert listed[other.rsplit("/", 1)[1]]["avatar_svg"] is None
    assert canonicalize(client.get("/api/auth/me", headers=owner).json()["avatar_svg"]) == canonicalize(personal_svg)


def test_workspace_avatar_preserves_animation_and_releases_replaced_media(workspace_client, workspace_avatar_setup):
    path, _, (owner, _, viewer) = workspace_avatar_setup
    client = workspace_client
    content = BytesIO()
    with Image.new("RGBA", (32, 32), "red") as first, Image.new("RGBA", (32, 32), "blue") as second:
        first.save(content, "PNG", save_all=True, append_images=[second], duration=[80, 150], loop=3)

    uploaded = client.put(
        f"{path}/avatar/image", content=content.getvalue(), headers={**owner, "Content-Type": "image/apng"}
    )
    assert uploaded.status_code == 200
    saved_url = uploaded.json()["avatar_url"]
    assert client.get(path, headers=viewer).json()["avatar_url"] == saved_url
    response = client.get(saved_url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (32, 32)
        assert image.n_frames == 2
        assert image.info["loop"] == 3

    svg = b"""<svg xmlns="http://www.w3.org/2000/svg" data-avatar-crop="80 60 12 0 60">
      <svg width="80" height="60" viewBox="0 0 80 60">
        <rect width="80" height="60"><animate attributeName="opacity" values="1;.5" dur="1s"/></rect>
      </svg>
    </svg>"""
    uploaded = client.put(f"{path}/avatar/image", content=svg, headers={**owner, "Content-Type": "image/svg+xml"})
    assert uploaded.status_code == 200
    assert client.get(saved_url).status_code == 404
    svg_url, fragment = uploaded.json()["avatar_url"].split("#")
    assert fragment == "crop=80,60,12,0,60"
    response = client.get(svg_url)
    assert response.status_code == 200
    assert "sandbox" in response.headers["content-security-policy"]
    assert "animate" in response.text

    reset = client.put(f"{path}/avatar", json={"avatar_svg": None}, headers=owner)
    assert reset.status_code == 200
    assert reset.json() == {"avatar_url": None, "avatar_svg": None}
    assert client.get(path, headers=viewer).json()["avatar_url"] is None
    assert client.get(svg_url).status_code == 404
