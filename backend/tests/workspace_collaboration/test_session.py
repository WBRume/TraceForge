from datetime import datetime

import pytest

from app.domains.workspace_collaboration import service, session
from app.domains.workspace_collaboration.models import CollaborationState
from app.domains.workspace_collaboration.router import ReleaseRequest
from app.domains.workspace_collaboration.schemas import EnableRequest, LeaseRequest
from tests.workspace_collaboration.test_service import acknowledge, enabled, fence
from tests.workspace_collaboration.test_service import environment as repository_environment

environment = repository_environment


@pytest.mark.parametrize("phase", ["READY", "RUNNING", "CONFLICT_PENDING", "PREPARING"])
def test_release_fences_stale_requests_without_stopping_cloud_work(environment, phase):
    db, task, _ = environment
    state = acknowledge(environment, enabled(environment))
    row = db.get(CollaborationState, task.id)
    row.sync_phase = phase
    row.conflicts_json = [{"path": "same.txt", "task_repository_id": "api"}]
    request = ReleaseRequest(**fence(state), operation_id="leave")
    released = session.release_driver(db, task, "u", request)
    db.commit()
    assert released["enabled"] is True
    assert released["driver_connected"] is False
    assert released["sync_phase"] == phase
    assert released["conflicts"] == row.conflicts_json
    assert released["lease_epoch"] == state["lease_epoch"] + 1
    assert session.release_driver(db, task, "u", request)["lease_epoch"] == released["lease_epoch"]
    with pytest.raises(service.CollaborationError, match="not the task driver"):
        service.renew_lease(db, task, "u", LeaseRequest(**fence(state)))


def test_same_instance_reconnects_without_active_driver_error(environment):
    db, task, _ = environment
    state = enabled(environment)
    result = service.claim_driver(
        db, task, "u", EnableRequest(client_id="desktop", instance_id="boot", operation_id="same-device")
    )
    assert result["lease_epoch"] == state["lease_epoch"]
    with pytest.raises(service.CollaborationError, match="active lease"):
        service.claim_driver(
            db, task, "u", EnableRequest(client_id="desktop", instance_id="other", operation_id="other")
        )
    with pytest.raises(service.CollaborationError, match="active desktop instance"):
        session.release_driver(
            db, task, "u", ReleaseRequest(**{**fence(state), "instance_id": "other"}, operation_id="bad-leave")
        )


def test_receive_once_creates_no_binding_or_lease_and_reuses_unchanged_snapshot(environment):
    db, task, root = environment
    (root / "api" / "same.txt").write_text("cloud latest")
    result = session.latest_snapshot(db, task, "u", None)
    db.commit()
    assert len(result["repositories"]) == 2
    assert db.get(CollaborationState, task.id) is None
    assert session.latest_snapshot(db, task, "u", None)["snapshot_id"] == result["snapshot_id"]


def test_receive_from_an_active_task_preserves_lease_and_delivery(environment):
    db, task, _ = environment
    state = enabled(environment)
    row = db.get(CollaborationState, task.id)
    row.sync_phase = "RUNNING"
    row.lease_expires_at = datetime(2030, 1, 1)
    before = service.get_state(db, task)
    result = session.latest_snapshot(db, task, "u", None)
    assert result["snapshot_id"] == state["snapshot_id"]
    assert service.get_state(db, task) == before
