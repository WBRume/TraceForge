"""
Regression tests for workspace_task_detail_service write operations.

These tests exercise all CRUD write paths through the router endpoints.
They must pass BEFORE and AFTER the service file refactoring.
"""
import os
import sys

from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.task.models.task import TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    RequirementStatus,
    SddRequirement,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_asset.services import workspace_asset_service  # noqa: E402

from test_workspace_asset_boundary import _build_app, _build_db, _seed_workspace, _session  # noqa: E402


def _seed_requirement_link(db, workspace, task, user):
    requirement = SddRequirement(
        id="req-task-detail",
        workspace_id=workspace.id,
        created_by_id=user.id,
        title="Task Detail must track real process assets",
        status=RequirementStatus.READY,
    )
    link = SddTaskRequirement(
        id="link-task-detail",
        workspace_id=workspace.id,
        requirement_id=requirement.id,
        task_id=task.id,
        relation_type=TaskRequirementRelationType.COVERS,
        created_by_id=user.id,
    )
    db.add_all([requirement, link])
    db.commit()
    return requirement


def _set_task_done(db, workspace_id, task_id):
    """Set task status to DONE so evidence can be created."""
    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id).first()
    if task:
        task.status = TaskStatus.DONE
        db.commit()


# Import SddTask for the helper above
from app.domains.task.models.task import SddTask  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: get entity from section endpoint
# ---------------------------------------------------------------------------

def _get_section_items(client, ws_id, task_id, section):
    """Fetch items from a section list endpoint."""
    res = client.get(f"/api/workspaces/{ws_id}/workspace-assets/tasks/{task_id}/{section}")
    assert res.status_code == 200, f"GET {section} failed: {res.text}"
    return res.json()["items"]


def _get_detail(client, ws_id, task_id, section, entity_id):
    """Fetch a single entity detail."""
    res = client.get(f"/api/workspaces/{ws_id}/workspace-assets/tasks/{task_id}/{section}/{entity_id}")
    assert res.status_code == 200, f"GET {section}/{entity_id} failed: {res.text}"
    return res.json()


# ---------------------------------------------------------------------------
# Human Review CRUD
# ---------------------------------------------------------------------------

def test_create_and_update_human_review():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-review", task_id="task-review")

        client = TestClient(_build_app(SessionLocal, user))

        # Create review
        res = client.post(
            "/api/workspaces/ws-review/workspace-assets/tasks/task-review/human-reviews",
            json={
                "outcome": "REJECT",
                "status": "RESOLVED",
                "title": "Reject current AI result",
                "body": "The result misses the required traceability boundary.",
                "change_reason": "Manual review found missing evidence.",
            },
        )
        assert res.status_code == 201
        assert res.json()["task"]["human_review_count"] == 1

        # Verify via section endpoint
        reviews = _get_section_items(client, "ws-review", "task-review", "human-reviews")
        assert len(reviews) == 1
        assert reviews[0]["outcome"] == "REJECT"
        assert reviews[0]["title"] == "Reject current AI result"
        review_id = reviews[0]["id"]

        # Update review
        update_res = client.patch(
            f"/api/workspaces/ws-review/workspace-assets/tasks/task-review/human-reviews/{review_id}",
            json={
                "outcome": "ACCEPT",
                "change_reason": "Changed mind after further review.",
            },
        )
        assert update_res.status_code == 200

        # Verify update
        detail = _get_detail(client, "ws-review", "task-review", "human-reviews", review_id)
        assert detail["outcome"] == "ACCEPT"

        # Add comment
        comment_res = client.post(
            f"/api/workspaces/ws-review/workspace-assets/tasks/task-review/human-reviews/{review_id}/comments",
            json={
                "body": "Additional context for the decision change.",
                "comment_type": "CLARIFICATION",
            },
        )
        assert comment_res.status_code == 201
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Evidence CRUD
# ---------------------------------------------------------------------------

def test_create_and_update_evidence():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-evidence", task_id="task-evidence")
            _set_task_done(db, "ws-evidence", "task-evidence")

        client = TestClient(_build_app(SessionLocal, user))

        # Create evidence
        res = client.post(
            "/api/workspaces/ws-evidence/workspace-assets/tasks/task-evidence/evidence",
            json={
                "evidence_type": "CODE",
                "source_type": "COMMIT",
                "source_uri": "https://example.com/commit/abc123",
                "title": "Initial commit",
            },
        )
        assert res.status_code == 201
        assert res.json()["task"]["evidence_count"] == 1

        # Verify via section endpoint
        evidence_items = _get_section_items(client, "ws-evidence", "task-evidence", "evidence")
        assert len(evidence_items) == 1
        evidence_id = evidence_items[0]["id"]

        # Verify via detail endpoint
        detail = _get_detail(client, "ws-evidence", "task-evidence", "evidence", evidence_id)
        assert detail["source"]["source_uri"] == "https://example.com/commit/abc123"
        assert detail["title"] == "Initial commit"

        # Update source fields
        update_res = client.patch(
            f"/api/workspaces/ws-evidence/workspace-assets/tasks/task-evidence/evidence/{evidence_id}",
            json={
                "source_uri": "https://example.com/commit/def456",
                "source_ref": "def456",
                "title": "Updated commit reference",
                "change_reason": "Commit was amended.",
            },
        )
        assert update_res.status_code == 200

        # Verify update
        updated = _get_detail(client, "ws-evidence", "task-evidence", "evidence", evidence_id)
        assert updated["source"]["source_uri"] == "https://example.com/commit/def456"
        assert updated["source"]["source_ref"] == "def456"
        assert updated["title"] == "Updated commit reference"
    finally:
        engine.dispose()


def test_evidence_phase_gating():
    """Evidence can only be created after task reaches DONE or FAILED status."""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-ev-phase", task_id="task-ev-phase")
            # Task is still PLANNING — evidence should be rejected

        client = TestClient(_build_app(SessionLocal, user))

        res = client.post(
            "/api/workspaces/ws-ev-phase/workspace-assets/tasks/task-ev-phase/evidence",
            json={
                "evidence_type": "CODE",
                "source_type": "COMMIT",
                "source_uri": "https://example.com/commit/abc",
                "title": "Test",
            },
        )
        assert res.status_code == 422
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Decision CRUD
# ---------------------------------------------------------------------------

def test_create_and_update_decision():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-decision", task_id="task-decision")
            requirement = _seed_requirement_link(db, workspace, task, user)

        client = TestClient(_build_app(SessionLocal, user))

        # Create decision
        res = client.post(
            "/api/workspaces/ws-decision/workspace-assets/tasks/task-decision/decisions",
            json={
                "requirement_id": requirement.id,
                "title": "Use PostgreSQL instead of SQLite",
                "body": "SQLite does not support concurrent writes needed for the checkout flow.",
                "status": "PROPOSED",
                "source_type": "TASK_DETAIL_BACKFILL",
                "promote_candidate": True,
                "change_reason": "Performance requirement from load testing.",
            },
        )
        assert res.status_code == 201
        assert res.json()["task"]["decision_count"] == 1

        # Verify via section endpoint
        decisions = _get_section_items(client, "ws-decision", "task-decision", "decisions")
        assert len(decisions) == 1
        assert decisions[0]["title"] == "Use PostgreSQL instead of SQLite"
        assert decisions[0]["status"] == "PROPOSED"
        assert decisions[0]["promote_candidate"] is True
        decision_id = decisions[0]["id"]

        # Verify via detail endpoint
        detail = _get_detail(client, "ws-decision", "task-decision", "decisions", decision_id)
        assert detail["requirement_id"] == requirement.id
        assert detail["source_type"] == "TASK_DETAIL_BACKFILL"

        # Update decision
        update_res = client.patch(
            f"/api/workspaces/ws-decision/workspace-assets/tasks/task-decision/decisions/{decision_id}",
            json={
                "status": "ACCEPTED",
                "title": "Use PostgreSQL for production",
                "body": "Confirmed by DBA review.",
                "change_reason": "DBA approved the change.",
            },
        )
        assert update_res.status_code == 200

        # Verify update
        updated = _get_detail(client, "ws-decision", "task-decision", "decisions", decision_id)
        assert updated["status"] == "ACCEPTED"
        assert updated["title"] == "Use PostgreSQL for production"

        # Verify audit log
        audit_res = client.get(
            "/api/workspaces/ws-decision/workspace-assets/tasks/task-decision/process-audit"
        )
        assert audit_res.status_code == 200
        audit_items = audit_res.json()["items"]
        decision_audits = [a for a in audit_items if a["record_type"] == "DECISION"]
        assert len(decision_audits) >= 2  # CREATED + UPDATED
        assert any(a["action"] == "CREATED" for a in decision_audits)
        assert any(a["action"] == "UPDATED" for a in decision_audits)
    finally:
        engine.dispose()


def test_create_decision_with_line_refs():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-decision-refs", task_id="task-decision-refs")

        client = TestClient(_build_app(SessionLocal, user))

        res = client.post(
            "/api/workspaces/ws-decision-refs/workspace-assets/tasks/task-decision-refs/decisions",
            json={
                "title": "Decision on main.py#L10-L20",
                "body": "Selected lines show the checkout validation logic.",
                "status": "PROPOSED",
                "source_type": "TASK_DETAIL_BACKFILL",
                "delta_line_refs": [
                    {"file_path": "src/main.py", "line_start": 10, "line_end": 20, "selected_text": "def validate_checkout():"},
                ],
            },
        )
        assert res.status_code == 201

        decisions = _get_section_items(client, "ws-decision-refs", "task-decision-refs", "decisions")
        assert len(decisions) == 1
        assert decisions[0]["title"] == "Decision on main.py#L10-L20"
    finally:
        engine.dispose()


def test_decision_validation_missing_title():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-decision-valid", task_id="task-decision-valid")

        client = TestClient(_build_app(SessionLocal, user))

        res = client.post(
            "/api/workspaces/ws-decision-valid/workspace-assets/tasks/task-decision-valid/decisions",
            json={
                "title": "",
                "status": "PROPOSED",
                "source_type": "TASK_DETAIL_BACKFILL",
            },
        )
        assert res.status_code == 422
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Clarification CRUD
# ---------------------------------------------------------------------------

def test_create_and_update_clarification():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-clarif", task_id="task-clarif")
            requirement = _seed_requirement_link(db, workspace, task, user)

        client = TestClient(_build_app(SessionLocal, user))

        # Create blocking clarification
        res = client.post(
            "/api/workspaces/ws-clarif/workspace-assets/tasks/task-clarif/clarifications",
            json={
                "requirement_id": requirement.id,
                "blocking_level": "BLOCKING",
                "status": "OPEN",
                "question": "Does this behavior apply to all workspace roles?",
                "change_reason": "Need to verify scope.",
            },
        )
        assert res.status_code == 201
        assert res.json()["task"]["clarification_count"] == 1

        # Verify via section endpoint
        clarifications = _get_section_items(client, "ws-clarif", "task-clarif", "clarifications")
        assert len(clarifications) == 1
        assert clarifications[0]["status"] == "OPEN"
        assert clarifications[0]["blocking_level"] == "BLOCKING"
        assert clarifications[0]["question"] == "Does this behavior apply to all workspace roles?"
        clarification_id = clarifications[0]["id"]

        # Update clarification — close it
        update_res = client.patch(
            f"/api/workspaces/ws-clarif/workspace-assets/tasks/task-clarif/clarifications/{clarification_id}",
            json={
                "status": "CLOSED",
                "answer": "Confirmed for owner workflow only.",
                "change_reason": "Human answered blocking question.",
            },
        )
        assert update_res.status_code == 200

        # Verify update
        detail = _get_detail(client, "ws-clarif", "task-clarif", "clarifications", clarification_id)
        assert detail["status"] == "CLOSED"
        assert detail["answer"] == "Confirmed for owner workflow only."
    finally:
        engine.dispose()


def test_clarification_validation_missing_question():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-clarif-valid", task_id="task-clarif-valid")

        client = TestClient(_build_app(SessionLocal, user))

        res = client.post(
            "/api/workspaces/ws-clarif-valid/workspace-assets/tasks/task-clarif-valid/clarifications",
            json={
                "question": "",
                "status": "OPEN",
            },
        )
        assert res.status_code == 422
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Final Summary
# ---------------------------------------------------------------------------

def test_final_summary_verified_requires_human_confirmation_and_no_blocking_clarification():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-final", task_id="task-final")
            requirement = _seed_requirement_link(db, workspace, task, user)
            _set_task_done(db, "ws-final", "task-final")

        client = TestClient(_build_app(SessionLocal, user))

        # Create accepting review
        review = client.post(
            "/api/workspaces/ws-final/workspace-assets/tasks/task-final/human-reviews",
            json={
                "outcome": "ACCEPT",
                "status": "RESOLVED",
                "title": "Accept after manual confirmation",
            },
        )
        assert review.status_code == 201
        reviews = _get_section_items(client, "ws-final", "task-final", "human-reviews")
        review_id = reviews[0]["id"]

        # Create human confirmation evidence
        human_confirmation = client.post(
            "/api/workspaces/ws-final/workspace-assets/tasks/task-final/evidence",
            json={
                "requirement_id": requirement.id,
                "human_review_id": review_id,
                "evidence_type": "BUSINESS",
                "source_type": "HUMAN_CONFIRMATION",
                "source_ref": "manual-confirmation",
                "title": "Manual confirmation",
                "confirmed": True,
            },
        )
        assert human_confirmation.status_code == 201
        evidence_items = _get_section_items(client, "ws-final", "task-final", "evidence")
        evidence_id = evidence_items[0]["id"]

        # Create blocking clarification — should block VERIFIED
        blocking = client.post(
            "/api/workspaces/ws-final/workspace-assets/tasks/task-final/clarifications",
            json={
                "requirement_id": requirement.id,
                "blocking_level": "BLOCKING",
                "status": "OPEN",
                "question": "Does this behavior apply to all workspace roles?",
            },
        )
        assert blocking.status_code == 201

        blocked_summary = client.put(
            "/api/workspaces/ws-final/workspace-assets/tasks/task-final/final-summary",
            json={
                "final_status": "VERIFIED",
                "summary": "Should not pass while blocking clarification is open.",
                "final_evidence_ids": [evidence_id],
                "human_confirmation_review_id": review_id,
            },
        )
        assert blocked_summary.status_code == 409

        # Close the blocking clarification
        clarification_items = _get_section_items(client, "ws-final", "task-final", "clarifications")
        clarification_id = clarification_items[0]["id"]
        closed = client.patch(
            f"/api/workspaces/ws-final/workspace-assets/tasks/task-final/clarifications/{clarification_id}",
            json={
                "status": "CLOSED",
                "answer": "Confirmed for owner workflow only.",
                "change_reason": "Human answered blocking question.",
            },
        )
        assert closed.status_code == 200

        # Now VERIFIED should succeed
        verified_summary = client.put(
            "/api/workspaces/ws-final/workspace-assets/tasks/task-final/final-summary",
            json={
                "final_status": "VERIFIED",
                "summary": "Closed with human confirmation Evidence.",
                "remaining_risk": "No automated risk board integration yet.",
                "next_steps": "Promote reusable clarification if needed.",
                "final_evidence_ids": [evidence_id],
                "human_confirmation_review_id": review_id,
                "change_reason": "Manual closeout.",
            },
        )
        assert verified_summary.status_code == 200
        # Response is TaskDetailSummaryResponse — verify coverage via process_summary
        assert verified_summary.json()["process_summary"]["coverage_status"] == "verified"
    finally:
        engine.dispose()
