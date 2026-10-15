import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.api_mock.models.api_mock import ApiMockSourceType, SddApiMockProject, SddApiMockSourceVersion
from app.domains.api_mock.routers.api_mock import router
from app.domains.api_mock.services.api_mock.source_version_service import persist_source_version
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.task.models.task import SddTask

BASE = "/api/workspaces/w/api-mock/projects/t"
CASES = "/api/workspaces/w/api-mock"


@pytest.fixture
def editor(db, tmp_path):
    user = User(id="u", email="editor@test.local", hashed_password="unused", display_name="Editor")
    db.add(user)
    db.add(Workspace(id="w", name="Workspace", owner_id="u"))
    db.add(WorkspaceMember(workspace_id="w", user_id="u", role=WorkspaceRole.OWNER))
    db.add(SddTask(id="t", workspace_id="w", creator_id="u", name="Mock", project_path=str(tmp_path)))
    project = SddApiMockProject(
        id="p", workspace_id="w", task_id="t", creator_id="u", temp_workspace_path=str(tmp_path)
    )
    db.add(project)
    db.commit()
    source = persist_source_version(
        db,
        project,
        source_type=ApiMockSourceType.SWAGGER_IMPORT,
        source_name="original.json",
        raw_content="",
        normalized_oas={
            "openapi": "3.0.3",
            "info": {"title": "test", "version": "1"},
            "paths": {"/ping": {"get": {"summary": "original", "responses": {"200": {"description": "ok"}}}}},
        },
        creator_id="u",
        activate=True,
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, source.id


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def endpoint(client):
    return ok(client.get(BASE + "/endpoints"))["items"][0]


def test_endpoint_editor_renames_and_preserves_history_cases_and_scope(editor, db):
    client, original_id = editor
    original = copy.deepcopy(db.get(SddApiMockSourceVersion, original_id).normalized_oas_json)
    old = endpoint(client)
    entity = ok(
        client.post(
            BASE + "/entities", json={"name": "Payload", "schema_json": {"type": "object"}, "endpoint_id": old["id"]}
        )
    )
    old = endpoint(client)
    assert entity["endpoint_id"] == old["id"]
    case = ok(
        client.post(
            CASES + f"/endpoints/{old['id']}/mock-cases",
            json={"name": "response", "is_default": True, "static_body_json": {"ok": True}},
        )
    )
    payload = {"row_version": 1, "method": "POST", "path": "/renamed", "summary": "updated"}
    new = ok(client.put(BASE + f"/endpoints/{old['id']}", json=payload))
    assert (new["method"], new["path"], new["summary"]) == ("POST", "/renamed", "updated")
    assert new["id"] != old["id"]
    copied = ok(client.get(CASES + f"/endpoints/{new['id']}/mock-cases"))["items"]
    assert len(copied) == 1 and copied[0]["static_body_json"] == case["static_body_json"]
    assert ok(client.get(BASE + "/entities"))["items"][0]["endpoint_id"] == new["id"]
    count = db.query(SddApiMockSourceVersion).count()
    assert client.put(BASE + f"/endpoints/{old['id']}", json=payload).status_code == 409
    assert client.put(BASE + f"/endpoints/{new['id']}", json={**payload, "row_version": 99}).status_code == 409
    assert db.query(SddApiMockSourceVersion).count() == count
    db.expire_all()
    assert db.get(SddApiMockSourceVersion, original_id).normalized_oas_json == original
    assert db.get(SddApiMockSourceVersion, original_id).source_name == "original.json"


def test_entity_editor_scope_survives_commit_and_stale_write_rejected(editor, db):
    client, _ = editor
    old = endpoint(client)
    created = ok(
        client.post(
            BASE + "/entities", json={"name": "Scoped", "schema_json": {"type": "string"}, "endpoint_id": old["id"]}
        )
    )
    db.rollback()
    db.expire_all()
    assert ok(client.get(BASE + "/entities"))["items"][0]["endpoint_id"] == endpoint(client)["id"]
    update = {"row_version": 1, "name": "Renamed", "schema_json": {"type": "integer"}, "endpoint_id": None}
    revised = ok(client.put(BASE + f"/entities/{created['id']}", json=update))
    assert revised["name"] == "Renamed" and revised["schema_json"] == {"type": "integer"}
    assert revised["endpoint_id"] is None
    assert client.put(BASE + f"/entities/{created['id']}", json=update).status_code == 409
    assert client.delete(BASE + f"/entities/{created['id']}").status_code == 409
    assert client.post(BASE + "/entities", json={"name": "Stale", "endpoint_id": old["id"]}).status_code == 409
    ok(client.delete(BASE + f"/entities/{revised['id']}"))
    assert ok(client.get(BASE + "/entities"))["items"] == []


def test_mock_case_version_and_default_are_preserved(editor):
    client, _ = editor
    ep = endpoint(client)
    path = CASES + f"/endpoints/{ep['id']}/mock-cases"
    first = ok(client.post(path, json={"name": "first", "is_default": True}))
    second = ok(client.post(path, json={"name": "second", "is_default": True}))
    assert [row["id"] for row in ok(client.get(path))["items"] if row["is_default"]] == [second["id"]]
    update = {"row_version": 1, "name": "edited", "is_default": True, "static_body_json": {"version": 2}}
    target = CASES + f"/mock-cases/{first['id']}"
    assert ok(client.put(target, json=update))["row_version"] == 2
    assert client.put(target, json=update).status_code == 409
    assert [row["id"] for row in ok(client.get(path))["items"] if row["is_default"]] == [first["id"]]
