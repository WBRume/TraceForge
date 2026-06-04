import os
import sys
import json

from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    RequirementAuditAction,
    RequirementStatus,
    SddRequirement,
    SddRequirementAuditLog,
    SddTaskRequirement,
)
from app.domains.workspace_asset.services import workspace_asset_service  # noqa: E402

from test_workspace_asset_boundary import _build_app, _build_db, _seed_workspace, _session  # noqa: E402


def _use_project_path(db, workspace, task, project_path):
    workspace.project_path = str(project_path)
    task.project_path = str(project_path)
    db.commit()


async def _fake_requirement_preview_cli(prompt, project_path, max_attempts=1):
    return {
        "text": json.dumps(
            {
                "items": [
                    {
                        "title": "Payment validation",
                        "body": "Payment state must be valid before checkout completion.",
                        "acceptance_criteria": ["Reject invalid payment state"],
                        "priority": "P1",
                        "source_ref": "REQ-AI-1",
                        "source_metadata": {"split_reason": "Separate payment validation"},
                        "task_prompt": "Implement checkout payment-state validation.",
                    },
                    {
                        "title": "Receipt",
                        "body": "Show receipt after successful checkout.",
                        "acceptance_criteria": ["Show receipt after success"],
                        "priority": "P2",
                        "source_ref": "REQ-AI-2",
                        "source_metadata": {"split_reason": "Separate receipt behavior"},
                        "task_prompt": "Implement checkout receipt rendering.",
                    },
                ]
            }
        ),
        "session_id": "test-session",
    }


async def _fake_requirement_split_cli(prompt, project_path, max_attempts=1):
    return {
        "text": json.dumps(
            {
                "items": [
                    {
                        "title": "Validate payment state",
                        "body": "Validate payment state before checkout completion.",
                        "acceptance_criteria": ["Reject invalid payment state"],
                        "source_ref": "REQ-SPLIT-1",
                        "task_prompt": "Implement payment state validation.",
                    },
                    {
                        "title": "Render receipt",
                        "body": "Render receipt after successful checkout.",
                        "acceptance_criteria": ["Show receipt after success"],
                        "source_ref": "REQ-SPLIT-2",
                        "task_prompt": "Implement receipt rendering.",
                    },
                ]
            }
        ),
        "session_id": "split-session",
    }


def test_requirement_create_edit_and_audit_history_are_real_records():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _task = _seed_workspace(db, workspace_id="ws-req-write", task_id="task-write")

        client = TestClient(_build_app(SessionLocal, user))
        created = client.post(
            "/api/workspaces/ws-req-write/workspace-assets/requirements",
            json={
                "title": "Checkout validates payment state",
                "body": "Payment state must be valid before checkout completion.",
                "acceptance_criteria": ["Reject invalid payment state."],
                "priority": "P1",
                "status": "READY",
                "source_kind": "manual",
                "source_ref": "REQ-101",
                "change_reason": "Initial requirement capture",
            },
        )
        assert created.status_code == 201
        requirement_id = created.json()["requirement"]["id"]
        assert created.json()["requirement"]["coverage_summary"]["coverage_status"] == "not_available"
        assert created.json()["audit_logs"][0]["action"] == RequirementAuditAction.CREATED.value

        updated = client.patch(
            f"/api/workspaces/ws-req-write/workspace-assets/requirements/{requirement_id}",
            json={
                "status": "IN_PROGRESS",
                "change_reason": "Implementation task started",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["requirement"]["status"] == RequirementStatus.IN_PROGRESS.value
        assert RequirementAuditAction.STATUS_CHANGED.value in {
            item["action"] for item in updated.json()["audit_logs"]
        }

        with _session(SessionLocal) as db:
            logs = db.query(SddRequirementAuditLog).filter(SddRequirementAuditLog.requirement_id == requirement_id).all()
            assert {log.action for log in logs} == {
                RequirementAuditAction.CREATED,
                RequirementAuditAction.STATUS_CHANGED,
            }
    finally:
        engine.dispose()


def test_requirement_import_preview_requires_confirm_before_creating_requirements(monkeypatch, tmp_path):
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(workspace_asset_service, "SessionLocal", SessionLocal)
        monkeypatch.setattr(workspace_asset_service, "run_cli_single_turn", _fake_requirement_preview_cli)
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-import", task_id="task-import")
            _use_project_path(db, workspace, task, tmp_path)

        client = TestClient(_build_app(SessionLocal, user))
        preview = client.post(
            "/api/workspaces/ws-import/workspace-assets/requirements/imports",
            data={
                "text": "# Payment validation\n\nAcceptance Criteria\n- Reject invalid payment state\n\n# Receipt\n\n- Show receipt after success",
                "source_kind": "document",
                "source_ref": "PRD-1",
            },
        )
        assert preview.status_code == 202
        job = preview.json()
        assert job["status"] in {"PENDING", "SUCCESS"}
        job_result = client.get(
            f"/api/workspaces/ws-import/workspace-assets/requirements/preview-jobs/{job['job_id']}"
        )
        assert job_result.status_code == 200
        assert job_result.json()["status"] == "SUCCESS"
        batch = job_result.json()["batch"]
        assert batch["status"] == "PREVIEW"
        assert batch["item_count"] == 2
        assert batch["items"][0]["task_prompt"] == "Implement checkout payment-state validation."

        with _session(SessionLocal) as db:
            assert db.query(SddRequirement).filter(SddRequirement.workspace_id == workspace.id).count() == 0

        confirm = client.post(
            f"/api/workspaces/ws-import/workspace-assets/requirements/imports/{batch['id']}/confirm",
            json={
                "items": [
                    {
                        "item_id": batch["items"][0]["id"],
                        "include": True,
                        "title": "Payment validation",
                        "status": "READY",
                    }
                ],
                "change_reason": "Confirm parsed requirement",
            },
        )
        assert confirm.status_code == 200
        assert confirm.json()["confirmed_count"] == 1
        with _session(SessionLocal) as db:
            requirement = db.query(SddRequirement).filter(SddRequirement.workspace_id == workspace.id).one()
            assert requirement.title == "Payment validation"
            assert requirement.status == RequirementStatus.READY
            assert requirement.acceptance_criteria_json == ["Reject invalid payment state"]
            assert requirement.source_metadata_json["task_prompt"] == "Implement checkout payment-state validation."
    finally:
        engine.dispose()


def test_requirement_import_preview_keeps_simple_requirement_as_single_item(monkeypatch, tmp_path):
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(workspace_asset_service, "SessionLocal", SessionLocal)
        monkeypatch.setattr(workspace_asset_service, "run_cli_single_turn", _fake_requirement_preview_cli)
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-simple-import", task_id="task-simple-import")
            _use_project_path(db, workspace, task, tmp_path)

        client = TestClient(_build_app(SessionLocal, user))
        preview = client.post(
            "/api/workspaces/ws-simple-import/workspace-assets/requirements/imports",
            data={
                "text": "# Payment validation\n\nCheckout must reject invalid payment states.\n\nAcceptance Criteria\n- Reject invalid payment state",
                "source_kind": "pasted_text",
            },
        )

        assert preview.status_code == 202
        job_result = client.get(
            f"/api/workspaces/ws-simple-import/workspace-assets/requirements/preview-jobs/{preview.json()['job_id']}"
        )
        assert job_result.status_code == 200
        batch = job_result.json()["batch"]
        assert batch["item_count"] == 1
        assert batch["items"][0]["title"] == "Payment validation"
        assert batch["items"][0]["body"].startswith("# Payment validation")
        assert batch["items"][0]["task_prompt"]
    finally:
        engine.dispose()


def test_requirement_ai_preview_requires_configured_project_path(monkeypatch):
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(workspace_asset_service, "SessionLocal", SessionLocal)
        with _session(SessionLocal) as db:
            user, _workspace, _task = _seed_workspace(db, workspace_id="ws-import-no-path", task_id="task-import-no-path")

        client = TestClient(_build_app(SessionLocal, user))
        preview = client.post(
            "/api/workspaces/ws-import-no-path/workspace-assets/requirements/imports",
            data={"text": "# Payment validation", "source_kind": "document"},
        )
        assert preview.status_code == 409
        assert "project_path" in preview.json()["detail"]
    finally:
        engine.dispose()


def test_requirement_direct_import_creates_single_requirement_without_preview(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-direct-import", task_id="task-direct-import")
            _use_project_path(db, workspace, task, tmp_path)

        client = TestClient(_build_app(SessionLocal, user))
        response = client.post(
            "/api/workspaces/ws-direct-import/workspace-assets/requirements/imports/direct",
            data={
                "text": "# Payment validation\n\nAcceptance Criteria\n- Reject invalid payment state\n\n# Receipt\n\n- Show receipt after success",
                "source_kind": "document",
                "source_ref": "PRD-DIRECT",
                "change_reason": "Import as a single requirement",
            },
        )

        assert response.status_code == 201
        assert response.json()["requirement"]["title"] == "Payment validation"
        assert response.json()["requirement"]["body"].count("#") == 2
        with _session(SessionLocal) as db:
            requirements = db.query(SddRequirement).filter(SddRequirement.workspace_id == workspace.id).all()
            assert len(requirements) == 1
            assert requirements[0].source_metadata_json["created_from"] == "direct_import"
    finally:
        engine.dispose()


def test_requirement_list_supports_hierarchy_query_sort_and_detail_children():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _task = _seed_workspace(db, workspace_id="ws-hierarchy", task_id="task-hierarchy")
            parent = SddRequirement(
                id="req-parent",
                workspace_id=workspace.id,
                created_by_id=user.id,
                title="Checkout parent requirement",
                body="Checkout source document body",
                status=RequirementStatus.READY,
                priority="P1",
                source_kind="document",
                source_ref="PRD-77",
            )
            child = SddRequirement(
                id="req-child",
                workspace_id=workspace.id,
                created_by_id=user.id,
                title="Validate payment child requirement",
                body="Payment state must be valid.",
                status=RequirementStatus.DRAFT,
                priority="P0",
                parent_requirement_id=parent.id,
                source_kind="document",
                source_ref="PRD-77#payment",
            )
            db.add_all([parent, child])
            db.commit()

        client = TestClient(_build_app(SessionLocal, user))
        tree = client.get(
            "/api/workspaces/ws-hierarchy/workspace-assets/requirements",
            params={"scope": "tree", "sort_by": "child_count", "sort_order": "desc"},
        )
        assert tree.status_code == 200
        assert tree.json()["scope"] == "tree"
        assert tree.json()["items"][0]["id"] == "req-parent"
        assert tree.json()["items"][0]["child_count"] == 1
        assert tree.json()["items"][0]["can_link_task"] is False
        assert tree.json()["items"][0]["children"][0]["id"] == "req-child"
        assert tree.json()["items"][0]["children"][0]["parent_title"] == "Checkout parent requirement"

        children = client.get(
            "/api/workspaces/ws-hierarchy/workspace-assets/requirements",
            params={"scope": "children", "q": "payment"},
        )
        assert children.status_code == 200
        assert children.json()["total"] == 1
        assert children.json()["items"][0]["id"] == "req-child"
        assert children.json()["items"][0]["can_link_task"] is True

        detail = client.get("/api/workspaces/ws-hierarchy/workspace-assets/requirements/req-parent")
        assert detail.status_code == 200
        assert detail.json()["children"][0]["id"] == "req-child"
    finally:
        engine.dispose()


def test_parent_requirement_with_children_rejects_new_task_links_but_child_can_link():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-child-link", task_id="task-child-link")
            parent = SddRequirement(
                id="req-parent-link",
                workspace_id=workspace.id,
                created_by_id=user.id,
                title="Parent with children",
                status=RequirementStatus.READY,
            )
            child = SddRequirement(
                id="req-child-link",
                workspace_id=workspace.id,
                created_by_id=user.id,
                title="Child requirement",
                status=RequirementStatus.READY,
                parent_requirement_id=parent.id,
            )
            db.add_all([parent, child])
            db.commit()

        client = TestClient(_build_app(SessionLocal, user))
        parent_link = client.post(
            "/api/workspaces/ws-child-link/workspace-assets/requirements/req-parent-link/tasks",
            json={"task_id": task.id, "relation_type": "RELATES_TO"},
        )
        assert parent_link.status_code == 409

        child_link = client.post(
            "/api/workspaces/ws-child-link/workspace-assets/requirements/req-child-link/tasks",
            json={"task_id": task.id, "relation_type": "COVERS"},
        )
        assert child_link.status_code == 200
        assert child_link.json()["linked_tasks"][0]["task_id"] == task.id
        with _session(SessionLocal) as db:
            links = db.query(SddTaskRequirement).filter(SddTaskRequirement.workspace_id == workspace.id).all()
            assert len(links) == 1
            assert links[0].requirement_id == "req-child-link"
    finally:
        engine.dispose()


def test_requirement_import_preview_multiple_items_creates_parent_with_children(monkeypatch, tmp_path):
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(workspace_asset_service, "SessionLocal", SessionLocal)
        monkeypatch.setattr(workspace_asset_service, "run_cli_single_turn", _fake_requirement_preview_cli)
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-import-tree", task_id="task-import-tree")
            _use_project_path(db, workspace, task, tmp_path)

        client = TestClient(_build_app(SessionLocal, user))
        preview = client.post(
            "/api/workspaces/ws-import-tree/workspace-assets/requirements/imports",
            data={
                "text": "# Checkout\n\n## Payment\n\nReject invalid payment.\n\n## Receipt\n\nShow receipt.",
                "source_kind": "document",
                "source_ref": "PRD-TREE",
            },
        )
        assert preview.status_code == 202
        job = client.get(
            f"/api/workspaces/ws-import-tree/workspace-assets/requirements/preview-jobs/{preview.json()['job_id']}"
        )
        batch = job.json()["batch"]

        confirm = client.post(
            f"/api/workspaces/ws-import-tree/workspace-assets/requirements/imports/{batch['id']}/confirm",
            json={
                "items": [{"item_id": item["id"], "include": True} for item in batch["items"]],
                "change_reason": "Confirm parent with children",
            },
        )
        assert confirm.status_code == 200
        assert confirm.json()["confirmed_count"] == 2

        with _session(SessionLocal) as db:
            requirements = (
                db.query(SddRequirement)
                .filter(SddRequirement.workspace_id == workspace.id)
                .order_by(SddRequirement.title.asc())
                .all()
            )
            parents = [item for item in requirements if not item.parent_requirement_id]
            children = [item for item in requirements if item.parent_requirement_id]
            assert len(parents) == 1
            assert len(children) == 2
            assert {child.parent_requirement_id for child in children} == {parents[0].id}
            assert parents[0].source_metadata_json["created_from"] == "import_confirm_parent"
            assert all(child.source_metadata_json["created_from"] == "import_confirm_child" for child in children)
    finally:
        engine.dispose()


def test_requirement_task_link_unlink_and_duplicate_conflict_write_audit():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-link", task_id="task-link")
            requirement = SddRequirement(
                id="req-link",
                workspace_id=workspace.id,
                created_by_id=user.id,
                title="Linked requirement",
                status=RequirementStatus.READY,
            )
            db.add(requirement)
            db.commit()

        client = TestClient(_build_app(SessionLocal, user))
        linked = client.post(
            "/api/workspaces/ws-link/workspace-assets/requirements/req-link/tasks",
            json={"task_id": "task-link", "relation_type": "COVERS", "change_reason": "Trace task"},
        )
        assert linked.status_code == 200
        assert linked.json()["linked_tasks"][0]["task_id"] == task.id

        duplicate = client.post(
            "/api/workspaces/ws-link/workspace-assets/requirements/req-link/tasks",
            json={"task_id": "task-link", "relation_type": "COVERS"},
        )
        assert duplicate.status_code == 409

        unlinked = client.delete(
            "/api/workspaces/ws-link/workspace-assets/requirements/req-link/tasks/task-link",
            params={"change_reason": "Wrong task"},
        )
        assert unlinked.status_code == 200
        assert unlinked.json()["linked_tasks"] == []

        with _session(SessionLocal) as db:
            actions = [
                log.action
                for log in db.query(SddRequirementAuditLog)
                .filter(SddRequirementAuditLog.requirement_id == "req-link")
                .order_by(SddRequirementAuditLog.created_at.asc())
                .all()
            ]
            assert RequirementAuditAction.LINKED_TASK in actions
            assert RequirementAuditAction.UNLINKED_TASK in actions
    finally:
        engine.dispose()


def test_requirement_split_preview_and_confirm_create_child_requirements(monkeypatch, tmp_path):
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(workspace_asset_service, "SessionLocal", SessionLocal)
        monkeypatch.setattr(workspace_asset_service, "run_cli_single_turn", _fake_requirement_split_cli)
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-split", task_id="task-split")
            _use_project_path(db, workspace, task, tmp_path)
            requirement = SddRequirement(
                id="req-parent",
                workspace_id=workspace.id,
                created_by_id=user.id,
                title="Checkout parent",
                body="1. Validate payment state\n2. Render receipt",
                status=RequirementStatus.READY,
            )
            db.add(requirement)
            db.commit()

        client = TestClient(_build_app(SessionLocal, user))
        preview = client.post(
            "/api/workspaces/ws-split/workspace-assets/requirements/req-parent/split-preview",
            json={"change_reason": "Split into traceable items"},
        )
        assert preview.status_code == 202
        job_result = client.get(
            f"/api/workspaces/ws-split/workspace-assets/requirements/preview-jobs/{preview.json()['job_id']}"
        )
        assert job_result.status_code == 200
        assert job_result.json()["status"] == "SUCCESS"
        batch = job_result.json()["batch"]
        assert batch["item_count"] == 2
        assert batch["items"][0]["task_prompt"] == "Implement payment state validation."

        confirmed = client.post(
            "/api/workspaces/ws-split/workspace-assets/requirements/req-parent/split",
            json={
                "batch_id": batch["id"],
                "items": [{"item_id": item["id"], "include": True} for item in batch["items"]],
                "change_reason": "Confirm split",
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["confirmed_count"] == 2

        with _session(SessionLocal) as db:
            children = (
                db.query(SddRequirement)
                .filter(SddRequirement.parent_requirement_id == "req-parent")
                .order_by(SddRequirement.title.asc())
                .all()
            )
            assert [child.title for child in children] == ["Render receipt", "Validate payment state"]
            assert children[0].source_metadata_json["task_prompt"] == "Implement receipt rendering."
    finally:
        engine.dispose()


def test_manage_requirements_permission_is_required_for_writes():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            owner, workspace, _task = _seed_workspace(db, workspace_id="ws-perm", task_id="task-perm")
            viewer = User(id="viewer-1", email="viewer@example.com", hashed_password="x", display_name="Viewer")
            member = WorkspaceMember(
                id="member-viewer",
                workspace_id=workspace.id,
                user_id=viewer.id,
                role=WorkspaceRole.VIEWER,
                permissions_json='["VIEW_ASSETS"]',
                is_expert=False,
            )
            db.add_all([viewer, member])
            db.commit()

        client = TestClient(_build_app(SessionLocal, viewer))
        response = client.post(
            "/api/workspaces/ws-perm/workspace-assets/requirements",
            json={"title": "Should not write", "status": "DRAFT"},
        )
        assert response.status_code == 403
    finally:
        engine.dispose()
