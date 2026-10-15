"""Human edits retain their immutable versions and appear in task detail."""

from datetime import datetime

import pytest
from sqlalchemy import text

from app.domains.workspace_asset.models.workspace_asset import SddHumanDelta
from app.domains.workspace_asset.services.tasks.sections import get_task_delta_workbench, get_task_human_deltas
from app.domains.workspace_collaboration import content, history, service
from tests.workspace_collaboration.test_service import environment as repository_environment
from tests.workspace_collaboration.test_service import input_request, preparing

environment = repository_environment


def test_backup_turn_time_preserves_the_conversation_timestamp(environment):
    from app.domains.task.models.session_turn import TaskSessionTurn
    from app.domains.workspace_collaboration.models import CollaborationState
    from tests.workspace_collaboration.test_service import enabled

    db, task, _ = environment
    initial = enabled(environment)
    state = db.get(CollaborationState, task.id)
    state.run_id = "job"
    created = datetime(2026, 10, 15, 17, 36, 48)
    db.add(
        TaskSessionTurn(
            task_id=task.id,
            workspace_id=task.workspace_id,
            session_generation=1,
            session_revision=0,
            turn_index=1,
            provider="opencode",
            ai_job_id="job",
            created_at=created,
        )
    )
    db.flush()
    manifest = service._snapshot(
        db, task, state, "AGENT_OUTPUT", service.get_snapshot(db, task.id, initial["snapshot_id"])["repositories"]
    )
    assert manifest["turn_created_at"] == "2026-10-15T17:36:48"


def test_handoff_is_indexed_once_and_comparison_survives_later_edits(environment):
    db, task, root = environment
    db.execute(text("PRAGMA foreign_keys=ON"))
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    state = preparing(environment)
    request = input_request(
        environment,
        state,
        {
            "api": {"same.txt": b"api baselinetest\r\n", "added.txt": b"new"},
            "web": {"same.txt": b"web baselinetest\r\n", "binary.bin": None},
        },
    )
    service.handoff(db, task, "u", request)
    db.commit()
    service.handoff(db, task, "u", request)
    db.commit()
    assert db.query(SddHumanDelta).filter_by(task_id=task.id).count() == 1
    indexed = get_task_human_deltas(db, "w", "t").items[0]
    assert indexed.changed_files_count == 4
    assert indexed.collaboration_handoff_id
    assert indexed.proposal_id is None and indexed.final_evidence_id is None
    assert (
        get_task_delta_workbench(db, "w", "t", indexed.id).collaboration_handoff_id == indexed.collaboration_handoff_id
    )
    listing = history.list_changes(db, "t", 1, 20)
    assert listing["total"] == 1
    assert listing["items"][0]["delta_id"] == indexed.id
    assert listing["items"][0]["actor_name"] == "Driver"
    assert history.list_changes(db, "t", 2, 1)["items"] == []
    record = history.change_detail(db, "t", indexed.collaboration_handoff_id)
    assert len({(f["repo_slug"], f["path"]) for f in record["files"]}) == 4
    assert {f["branch_name"] for f in record["files"]} == {"release/2.x", "feature/login"}
    added = next(f for f in record["files"] if f["path"] == "added.txt")
    deleted = next(f for f in record["files"] if f["path"] == "binary.bin")
    assert added["before"] is None and deleted["after"] is None
    (root / "api/same.txt").write_bytes(b"later Agent output")
    store = content.ObjectStore("t")
    for file in record["files"]:
        if file["path"] == "same.txt":
            assert store.read(file["before"]["sha256"]) == (file["repo_slug"] + " baseline\r\n").encode()
            assert store.read(file["after"]["sha256"]) == (file["repo_slug"] + " baselinetest\r\n").encode()
    with pytest.raises(service.CollaborationError) as exc:
        history.change_detail(db, "another-task", indexed.collaboration_handoff_id)
    assert exc.value.status_code == 404


def test_no_change_does_not_create_human_delta(environment):
    db, task, _ = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    db.commit()
    assert db.query(SddHumanDelta).filter_by(task_id=task.id).count() == 0
