"""Diagnosis tasks use ordinary chat without local workspace collaboration."""

import pytest

from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.task.services import chat_submission_service as submissions
from app.domains.workspace_collaboration import service, session
from app.domains.workspace_collaboration.models import CollaborationSnapshot, CollaborationState
from app.domains.workspace_collaboration.schemas import EnableRequest


@pytest.fixture
def diagnosis_task(db):
    db.add(User(id="u", email="diagnosis-collaboration@test.local", hashed_password="x", display_name="User"))
    db.add(Workspace(id="w", name="Workspace", owner_id="u"))
    task = SddTask(
        id="diagnosis",
        workspace_id="w",
        creator_id="u",
        name="Investigate the issue",
        task_type=TaskType.DIAGNOSIS,
        execution_location="SERVER",
        status=TaskStatus.CODING,
        session_generation=1,
        session_revision=0,
    )
    db.add(task)
    db.commit()
    return task


@pytest.mark.parametrize("action", ["enable", "claim_driver", "latest_snapshot"])
def test_diagnosis_cannot_start_local_collaboration(db, diagnosis_task, action):
    request = EnableRequest(operation_id="diagnosis", client_id="desktop", instance_id="instance")
    function = session.latest_snapshot if action == "latest_snapshot" else getattr(service, action)
    with pytest.raises(service.CollaborationError) as error:
        function(db, diagnosis_task, "u", request)
    assert error.value.code == "TASK_TYPE_UNSUPPORTED"
    assert db.query(CollaborationState).count() == 0
    assert db.query(CollaborationSnapshot).count() == 0


def test_diagnosis_message_needs_no_local_input(db, diagnosis_task):
    result = submissions._accept_sync(db, diagnosis_task.id, "u", "message", "Investigate the issue", {})
    db.commit()
    prepared = submissions._load_preparation(db, result["id"])
    assert prepared is not None
    assert "collaboration" not in prepared["context_json"]
    assert db.query(CollaborationState).count() == 0
