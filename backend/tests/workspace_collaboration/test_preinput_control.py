"""Collaborative prompts preserve their creator and only use that user's live desktop."""

from datetime import datetime, timedelta

import pytest

from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.workspace_collaboration import control
from app.domains.workspace_collaboration.models import CollaborationState
from tests.task.test_collaboration_execution import collaboration_db as collaboration_db


@pytest.mark.parametrize(
    "actor,connected,local_input",
    [("u", True, True), ("u", False, False), ("other", True, False)],
)
def test_preinput_only_handoffs_from_connected_creator(collaboration_db, actor, connected, local_input):
    db = collaboration_db
    state = db.get(CollaborationState, "t")
    db.add(User(id="other", email="other@test.local", display_name="Other", hashed_password="x"))
    db.add(WorkspaceMember(id="other-member", workspace_id="w", user_id="other", role=WorkspaceRole.DEVELOPER))
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=60 if connected else -1)
    db.commit()
    result = control.accept_pre_input(db, state.task_id, actor, "shared prompt", {"pre_input_id": "pre-1"})
    db.commit()
    receipt = db.get(TaskChatSubmission, result["id"])
    assert receipt.creator_id == actor
    assert ("collaboration" in receipt.metadata_json) is local_input
    assert state.driver_user_id == "u" and state.client_id == "desktop"
