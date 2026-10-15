"""Frozen tasks remain downloadable without reopening their code for writes."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_collaboration import router, service
from app.domains.workspace_collaboration.schemas import DeliveryReceipt
from tests.workspace_collaboration.test_service import enabled, fence
from tests.workspace_collaboration.test_service import environment as repository_environment

environment = repository_environment
PATH = "/workspaces/w/tasks/t/collaboration"


@pytest.fixture
def frozen_client(environment, monkeypatch):
    db, task, _ = environment
    initial = enabled(environment)
    receipt = {
        **fence(initial),
        "operation_id": "receipt",
        "snapshot_id": initial["snapshot_id"],
        "local_scan_id": "scan",
        "repository_results": [
            {"task_repository_id": r["task_repository_id"], "status": "ALIGNED"} for r in initial["repositories"]
        ],
    }
    state = service.receipt(db, task, "u", DeliveryReceipt(**receipt))
    task.status = TaskStatus.BASELINED
    db.commit()
    user = SimpleNamespace(id="u")
    monkeypatch.setattr(router.workspace_service, "get_workspace_member", lambda *_: True)
    monkeypatch.setattr(router.workspace_service, "user_has_permission", lambda _db, _ws, uid, _p: uid == "u")
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, state, user, receipt


def test_frozen_snapshot_download_is_read_only_for_workspace_reader(environment, frozen_client):
    client, state, user, _ = frozen_client
    db, task, root = environment
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.glob("*/same.txt")}
    user.id = "reader"
    response = client.post(PATH + "/latest-snapshot", json={})
    assert response.status_code == 200, response.text
    assert response.json()["snapshot_id"] == state["snapshot_id"]
    assert len(response.json()["repositories"]) == 2
    assert {str(p.relative_to(root)): p.read_bytes() for p in root.glob("*/same.txt")} == before
    task = db.get(SddTask, "t")
    assert service.get_state(db, task) == state
    assert task.status == TaskStatus.BASELINED
    assert client.post(PATH + "/lease", json=fence(state)).status_code == 403


def test_frozen_existing_driver_can_renew_and_release_but_identity_is_still_fenced(frozen_client):
    client, state, _, receipt = frozen_client
    assert client.post(PATH + "/lease", json=fence(state)).status_code == 200
    replay = client.post(PATH + "/receipt", json=receipt)
    assert replay.status_code == 200, replay.text
    assert replay.json()["snapshot_id"] == state["snapshot_id"]
    invalid = {**fence(state), "instance_id": "other", "operation_id": "invalid-release"}
    assert client.post(PATH + "/release-driver", json=invalid).status_code == 409
    response = client.post(PATH + "/release-driver", json={**fence(state), "operation_id": "release"})
    assert response.status_code == 200, response.text
    assert response.json()["driver_connected"] is False
    assert response.json()["snapshot_id"] == state["snapshot_id"]
    assert client.post(PATH + "/lease", json=fence(state)).status_code == 409


@pytest.mark.parametrize("action", ["enable", "claim-driver", "recover-input", "recover-output"])
def test_frozen_task_rejects_new_driver_and_code_recovery(frozen_client, action):
    client, state, _, _ = frozen_client
    response = client.post(PATH + "/" + action, json={**fence(state), "operation_id": "forbidden"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Baselined task is read-only"


def test_frozen_task_rejects_upload_and_handoff_and_can_disconnect(environment, frozen_client):
    client, state, _, _ = frozen_client
    db, task, _ = environment
    upload = client.put(PATH + "/objects/" + "a" * 64, params=fence(state), content=b"forbidden")
    assert upload.status_code == 403
    manifest = service.get_snapshot(db, task.id, state["snapshot_id"])
    handoff = client.post(
        PATH + "/handoff",
        json={
            **fence(state),
            "operation_id": "forbidden",
            "manifest": manifest,
            "input_cut_seq": 1,
        },
    )
    assert handoff.status_code == 403
    response = client.post(PATH + "/disable", json={**fence(state), "operation_id": "disconnect"})
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert db.get(SddTask, "t").status == TaskStatus.BASELINED
