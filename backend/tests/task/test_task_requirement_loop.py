import pytest
from fastapi.testclient import TestClient

from app.domains.auth.models.user import Workspace
from app.domains.task.models.task import SddTask, TaskStatus, SddTaskFollower
from app.domains.task.routers.task import crud
from app.domains.task.schemas.task import TaskResponse
from app.domains.task.services import task_service
from app.domains.workspace_asset.models.workspace_asset import SddRequirement, SddTaskRequirement, SddRequirementAuditLog
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _build_app, _seed_workspace, _session


@pytest.fixture
def seeded():
    engine, sessions = _build_db()
    with _session(sessions) as db:
        user, workspace, task = _seed_workspace(db)
        db.add_all([
            SddRequirement(id="req-101", workspace_id=workspace.id, title="Payments", source_ref="REQ-101"),
            SddRequirement(id="req-102", workspace_id=workspace.id, title="Delivery"),
            Workspace(id="other-workspace", name="Other", owner_id=user.id),
            SddRequirement(id="foreign-req", workspace_id="other-workspace", title="Private"),
        ])
        db.commit()
    yield sessions, user, workspace, task
    engine.dispose()


def test_creation_binds_requirement_and_audit_in_one_transaction(seeded):
    sessions, user, workspace, _ = seeded
    with _session(sessions) as db:
        task = task_service.create_task_record_for_provision(db, user, workspace.id, "Implement", requirement_id="req-101")
        assert task.status == TaskStatus.PROVISIONING
        assert db.query(SddTaskRequirement).filter_by(task_id=task.id, requirement_id="req-101").count() == 1
        assert db.query(SddRequirementAuditLog).filter_by(task_id=task.id).one().after_json["task_id"] == task.id
        assert TaskResponse.model_validate(task).requirements[0].source_ref == "REQ-101"


def test_diagnosis_creation_cannot_link_requirement_before_closeout(seeded):
    sessions, user, workspace, _ = seeded
    with _session(sessions) as db:
        with pytest.raises(ValueError, match="when completed"):
            task_service.create_task_record_for_provision(db, user, workspace.id, "Diagnose", task_type="DIAGNOSIS", requirement_id="req-101")
        assert db.query(SddTaskRequirement).count() == 0


def test_task_create_api_accepts_requirement_and_detail_exposes_binding(seeded, monkeypatch):
    sessions, user, workspace, _ = seeded
    monkeypatch.setattr(crud.provision_job_service, "run_create_task_job", lambda job_id: None)
    app = _build_app(sessions, user)
    app.include_router(crud.router, prefix="/api")
    client = TestClient(app)
    response = client.post(f"/api/workspaces/{workspace.id}/tasks", json={"name":"Deliver requirement", "requirement_id":"req-101"})
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    detail = client.get(f"/api/workspaces/{workspace.id}/tasks/{task_id}").json()
    assert detail["requirements"][0]["id"] == "req-101"
    requirement = client.get(f"/api/workspaces/{workspace.id}/workspace-assets/requirements/req-101").json()
    assert requirement["linked_tasks"][0]["task_id"] == task_id
    assert requirement["linked_tasks"][0]["creator_name"] == "User"


def test_wrong_workspace_rejected_and_later_failure_rolls_back_binding(seeded, monkeypatch):
    sessions, user, workspace, _ = seeded
    with _session(sessions) as db:
        for requirement_id in ["foreign-req", "missing"]:
            with pytest.raises(ValueError, match="Requirement not found"):
                task_service.create_task_record_for_provision(db, user, workspace.id, "Invalid", requirement_id=requirement_id)

        def fail(*args, **kwargs):
            raise ValueError("repository snapshot failed")

        monkeypatch.setattr(task_service, "snapshot_workspace_repositories_into_task", fail)
        with pytest.raises(ValueError, match="snapshot failed"):
            task_service.create_task_record_for_provision(db, user, workspace.id, "Rollback", requirement_id="req-101")
        assert db.query(SddTask).count() == 1
        assert db.query(SddTaskRequirement).count() == 0
        assert db.query(SddRequirementAuditLog).count() == 0


def test_hierarchical_picker_and_creation_reject_parent_but_inherit_child_content(seeded, monkeypatch):
    sessions, user, workspace, _ = seeded
    with _session(sessions) as db:
        db.add(SddRequirement(id="child", workspace_id=workspace.id, parent_requirement_id="req-101",
                              title="Validate payment", body="# Payment specification\nReject invalid payments.",
                              source_metadata_json={"task_prompt": "Implement payment validation"}))
        db.commit()
    run_job = []
    monkeypatch.setattr(crud.provision_job_service, "run_create_task_job", lambda job_id: run_job.append(job_id))
    app = _build_app(sessions, user)
    app.include_router(crud.router, prefix="/api")
    client = TestClient(app)
    assets = f"/api/workspaces/{workspace.id}/workspace-assets"
    roots = client.get(f"{assets}/requirement-options", params={"scope": "roots"}).json()["items"]
    assert {item["id"] for item in roots} == {"req-101", "req-102"}
    parent = next(item for item in roots if item["id"] == "req-101")
    assert parent["child_count"] == 1 and parent["can_link_task"] is False
    children = client.get(f"{assets}/requirement-options", params={"scope": "children", "parent_id": "req-101"}).json()["items"]
    assert children[0]["id"] == "child" and children[0]["parent_title"] == "Payments"
    assert children[0]["can_link_task"] is True
    assert client.get(f"{assets}/requirement-options", params={"scope": "children", "parent_id": "foreign-req"}).json()["total"] == 0
    response = client.post(f"/api/workspaces/{workspace.id}/tasks", json={"name": "Invalid parent", "requirement_id": "req-101"})
    assert response.status_code == 400
    assert not run_job
    with _session(sessions) as db:
        assert db.query(SddTask).count() == 1
        assert db.query(SddTaskRequirement).count() == 0
    detail = client.get(f"{assets}/requirements/child").json()["requirement"]
    assert detail["body"] == "# Payment specification\nReject invalid payments."
    assert detail["source_metadata"]["task_prompt"] == "Implement payment validation"
    response = client.post(f"/api/workspaces/{workspace.id}/tasks", json={"name": detail["title"], "description": detail["source_metadata"]["task_prompt"], "requirement_id": "child"})
    assert response.status_code == 202
    with _session(sessions) as db:
        assert db.query(SddTask).filter_by(id=response.json()["task_id"]).one().description == "Implement payment validation"
        assert db.query(SddTaskRequirement).filter_by(task_id=response.json()["task_id"]).one().requirement_id == "child"


def test_views_use_real_links_and_current_user_favorites_with_sql_pagination(seeded):
    sessions, user, workspace, task = seeded
    with _session(sessions) as db:
        db.add_all([
            SddTask(id="solo", workspace_id=workspace.id, creator_id=user.id, name="Solo"),
            SddTask(id="linked", workspace_id=workspace.id, creator_id=user.id, name="Linked"),
            SddTaskRequirement(workspace_id=workspace.id, task_id=task.id, requirement_id="req-101"),
            SddTaskRequirement(workspace_id=workspace.id, task_id=task.id, requirement_id="req-102"),
            SddTaskRequirement(workspace_id=workspace.id, task_id="linked", requirement_id="req-101"),
            SddTaskFollower(workspace_id=workspace.id, task_id=task.id, user_id=user.id),
        ])
        db.commit()
    app = _build_app(sessions, user)
    app.include_router(crud.router, prefix="/api")
    client = TestClient(app)
    base = f"/api/workspaces/{workspace.id}/tasks"
    assert client.get(base).json()["total"] == 3
    solo = client.get(base, params={"independent": True}).json()
    assert [item["id"] for item in solo["items"]] == ["solo"]
    assert solo["items"][0]["requirements"] == []
    favorites = client.get(base, params={"following": True}).json()
    assert [item["id"] for item in favorites["items"]] == [task.id]
    assert favorites["items"][0]["is_following"] is True
    first = client.get(base, params={"requirement_id": "req-101", "page_size": 1}).json()
    second = client.get(base, params={"requirement_id": "req-101", "page_size": 1, "page": 2}).json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert client.get(base, params={"requirement_id": "foreign-req"}).json()["total"] == 0
    assert client.get(base, params={"following": True, "task_type": "DIAGNOSIS"}).json()["total"] == 0
    detail = client.get(f"{base}/{task.id}").json()
    assert {item["id"] for item in detail["requirements"]} == {"req-101", "req-102"}


def test_picker_searches_100_plus_requirements_without_loading_asset_trees(seeded):
    sessions, user, workspace, _ = seeded
    with _session(sessions) as db:
        db.add_all([SddRequirement(id=f"history-{i}", workspace_id=workspace.id, title=f"History {i}", source_ref=f"REQ-{i + 1000}") for i in range(120)])
        db.commit()
    client = TestClient(_build_app(sessions, user))
    base = f"/api/workspaces/{workspace.id}/workspace-assets/requirement-options"
    first = client.get(base, params={"page_size": 40}).json()
    second = client.get(base, params={"page_size": 40, "page": 2}).json()
    assert first["total"] == 122
    assert len(first["items"]) == len(second["items"]) == 40
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})
    assert set(first["items"][0]) == {"id", "title", "status", "source_ref", "parent_requirement_id", "parent_title", "child_count", "can_link_task"}
    assert client.get(base, params={"q": "REQ-1119"}).json()["items"][0]["id"] == "history-119"
    assert client.get(base, params={"q": "history-119"}).json()["total"] == 1
    assert client.get(base, params={"ids": "req-101,foreign-req"}).json()["total"] == 1
