"""Collaborative prompts preserve their creator and only use that user's live desktop."""

from datetime import datetime, timedelta

import pytest

from app.domains.auth.models.user import User
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.workspace_collaboration import control
from app.domains.workspace_collaboration.models import CollaborationState
from tests.workspace_collaboration.test_service import acknowledge, enabled
from tests.workspace_collaboration.test_service import environment as repository_environment

environment = repository_environment


@pytest.mark.parametrize(
    "actor,connected,local_input",
    [("u", True, True), ("u", False, False), ("other", True, False), ("other", False, False)],
)
def test_preinput_only_handoffs_from_connected_creator(environment, actor, connected, local_input):
    db, task, _ = environment
    db.add(User(id="other", email="other@test.local", display_name="Other", hashed_password="x"))
    acknowledge(environment, enabled(environment))
    state = db.get(CollaborationState, task.id)
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=60 if connected else -1)
    db.commit()
    result = control.accept_pre_input(db, task.id, actor, "shared prompt", {"pre_input_id": "pre-1"})
    db.commit()
    receipt = db.get(TaskChatSubmission, result["id"])
    assert receipt.creator_id == actor
    assert ("collaboration" in receipt.metadata_json) is local_input
    assert state.driver_user_id == "u" and state.client_id == "desktop"
