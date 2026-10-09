"""Task document deltas, directory isolation and workspace configuration."""

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, Workspace
from app.domains.task.services import task_git_snapshot_store as snapshots
from app.domains.task.services.task_workspace import documents
from app.domains.workspace.routers.workspace import router

POLICY = {"excluded_dirs": ["node_modules"], "excluded_suffixes": [".pyc"]}


def write(root, relative, content):
    file = root / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    return file


def make_task(tmp_path, roots):
    root = tmp_path / "task"
    root.mkdir(exist_ok=True)
    return SimpleNamespace(
        id="task",
        project_path=str(root),
        execution_location="SERVER",
        workspace=SimpleNamespace(plan_doc_roots=roots),
        task_meta_json={"initial_workspace_checkpoint": str(tmp_path / "turn-initial")},
    )


def capture(task, tmp_path):
    snapshots.capture(task.project_path, [], str(tmp_path / "turn-initial"), str(tmp_path), POLICY)


def paths(task):
    payload = documents.list_plan_docs(task)
    return [item["relative_path"] for item in payload["plans"] + payload["specs"]]


def test_changes_use_original_content_not_timestamps_and_survive_refresh(tmp_path):
    task = make_task(tmp_path, ["archive", "archive/nested"])
    root = tmp_path / "task"
    old = write(root, "archive/old.md", "unchanged")
    changed = write(root, "archive/nested/changed.markdown", "original")
    write(root, "archive/specs/old.md", "old spec")
    capture(task, tmp_path)
    assert paths(task) == []
    os.utime(old, None)
    modified_time = changed.stat().st_mtime
    changed.write_text("modified", encoding="utf-8")
    os.utime(changed, (modified_time, modified_time))
    write(root, "archive/new.md", "new")
    write(root, "archive/specs/new.md", "new spec")
    write(root, "elsewhere/unrelated.md", "not configured")
    write(root, "archive/not-markdown.txt", "ignore")
    expected = ["archive/nested/changed.markdown", "archive/new.md", "archive/specs/new.md"]
    assert paths(task) == expected
    assert paths(task) == expected
    changed.write_text("original", encoding="utf-8")
    assert "archive/nested/changed.markdown" not in paths(task)


def test_roots_changed_after_task_started_still_exclude_existing_files(tmp_path):
    task = make_task(tmp_path, [])
    root = tmp_path / "task"
    write(root, "other/old.md", "old")
    capture(task, tmp_path)
    write(root, "other/new.md", "new")
    assert documents.list_plan_docs(task)["configured"] is False
    task.workspace.plan_doc_roots = ["other"]
    assert paths(task) == ["other/new.md"]
    task.workspace.plan_doc_roots = []
    assert paths(task) == []


def test_identical_names_in_different_roots_read_and_save_exact_file(tmp_path):
    task = make_task(tmp_path, ["a", "b"])
    capture(task, tmp_path)
    root = tmp_path / "task"
    write(root, "a/plans/design.md", "first")
    write(root, "b/plans/design.md", "second")
    assert len(paths(task)) == 2
    assert documents.read_plan_doc(task, "plans", path="b/plans/design.md")["content"] == "second"
    documents.save_plan_doc(task, "plans", "edited", path="b/plans/design.md")
    assert (root / "a/plans/design.md").read_text() == "first"
    assert (root / "b/plans/design.md").read_text() == "edited"
    for relative in ("../outside.md", "C:/outside.md", "/outside.md", "other/file.md", "b/../a/file.md"):
        with pytest.raises(ValueError):
            documents.save_plan_doc(task, "plans", "forbidden", path=relative)


def test_unconfigured_and_missing_baseline_do_not_expose_all_documents(tmp_path, monkeypatch):
    task = make_task(tmp_path, [])
    write(tmp_path / "task", "old.md", "old")
    task.execution_location = "LOCAL"
    from app.domains.local_resource import service

    monkeypatch.setattr(
        service, "task_operation", lambda *a, **kw: pytest.fail("Unconfigured local tasks must not scan")
    )
    assert documents.list_plan_docs(task)["configured"] is False
    task.execution_location = "SERVER"
    task.workspace.plan_doc_roots = ["."]
    payload = documents.list_plan_docs(task)
    assert payload["baseline_available"] is False
    assert payload["plans"] == []


def test_local_request_uses_workspace_roots_and_task_baseline(tmp_path, monkeypatch):
    from app.domains.local_resource import service
    from app.domains.local_resource import snapshots as remote

    task = make_task(tmp_path, ["archive"])
    task.execution_location = "LOCAL"
    task.task_meta_json = {"initial_workspace_checkpoint": remote.encode(task.id, "local/initial")}
    received = []
    monkeypatch.setattr(service, "task_operation", lambda *args: received.append(args) or {"plans": [], "specs": []})
    documents.list_plan_docs(task)
    assert received == [
        ("task", "documents", {"action": "list", "roots": ["archive"], "initial_checkpoint": "local/initial"})
    ]


def test_symlink_root_cannot_escape_task_directory(tmp_path):
    task = make_task(tmp_path, ["escape"])
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tmp_path / "task" / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError):
        documents.save_plan_doc(task, "plans", "forbidden", path="escape/doc.md")


def test_workspace_settings_permissions_isolation_and_path_validation(db):
    from app.domains.auth.models.user import WorkspaceMember, WorkspaceRole

    owner = User(id="owner", email="owner@example.com", hashed_password="x", display_name="Owner", is_admin=False)
    viewer = User(id="viewer", email="viewer@example.com", hashed_password="x", display_name="Viewer", is_admin=False)
    db.add_all([owner, viewer])
    for key in ("w1", "w2"):
        db.add(Workspace(id=key, name=key, owner_id=owner.id))
        db.add(WorkspaceMember(workspace_id=key, user_id=owner.id, role=WorkspaceRole.OWNER))
    membership = WorkspaceMember(workspace_id="w1", user_id=viewer.id, role=WorkspaceRole.VIEWER)
    db.add(membership)
    db.commit()
    current_user = [owner]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user[0]
    client = TestClient(app)
    url = "/workspaces/w1/plan-docs-settings"
    assert client.get(url).json() == {"workspace_id": "w1", "roots": [], "can_edit": True}
    response = client.put(url, json={"roots": [" archive/ ", "repo/docs", "archive"]})
    assert response.status_code == 200
    assert response.json()["roots"] == ["archive", "repo/docs"]
    db.expire_all()
    assert db.get(Workspace, "w1").plan_doc_roots == ["archive", "repo/docs"]
    assert db.get(Workspace, "w2").plan_doc_roots is None
    for root in ("../x", "/absolute", "C:/docs", "//host/share", "docs/../x", ".GIT"):
        assert client.put(url, json={"roots": [root]}).status_code == 422
    assert client.put(url, json={"roots": []}).json()["roots"] == []
    current_user[0] = viewer
    assert client.get(url).json()["can_edit"] is False
    assert client.put(url, json={"roots": ["docs"]}).status_code == 403
    assert client.get(url.replace("w1", "w2")).status_code == 403
    assert client.put(url.replace("w1", "w2"), json={"roots": []}).status_code == 403
    membership.permissions_json = '["MANAGE_MEMBERS"]'
    db.commit()
    assert client.get(url).json()["can_edit"] is True
    assert client.put(url, json={"roots": ["docs"]}).status_code == 200


def test_task_routes_serialize_deltas_and_enforce_workspace_boundaries(db, tmp_path):
    from app.domains.auth.models.user import WorkspaceMember, WorkspaceRole
    from app.domains.task.models.task import SddTask
    from app.domains.task.routers.task.spec_docs import router as task_router

    owner = User(id="owner", email="owner@example.com", hashed_password="x", display_name="Owner")
    workspace = Workspace(id="workspace", name="Workspace", owner_id=owner.id, plan_doc_roots=["archive"])
    db.add_all([owner, workspace])
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    initial = make_task(tmp_path, ["archive"])
    write(tmp_path / "task", "archive/old.md", "old")
    capture(initial, tmp_path)
    write(tmp_path / "task", "archive/new.md", "new")
    db.add(
        SddTask(
            id="task",
            name="Task",
            creator_id=owner.id,
            workspace_id=workspace.id,
            project_path=initial.project_path,
            task_meta_json=initial.task_meta_json,
        )
    )
    db.commit()
    app = FastAPI()
    app.include_router(task_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    client = TestClient(app)
    url = "/workspaces/workspace/tasks/task/plan-docs"
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["baseline_available"] is True
    assert [row["relative_path"] for row in response.json()["plans"]] == ["archive/new.md"]
    params = {"section": "plans", "path": "archive/new.md"}
    assert client.get(url + "/content", params=params).json()["content"] == "new"
    assert client.put(url + "/content", json={**params, "content": "edited"}).status_code == 200
    assert (tmp_path / "task/archive/new.md").read_text() == "edited"
    assert client.get(url + "/content", params={**params, "path": "outside.md"}).status_code == 400
    assert client.get(url.replace("workspace/tasks", "other/tasks")).status_code == 403
