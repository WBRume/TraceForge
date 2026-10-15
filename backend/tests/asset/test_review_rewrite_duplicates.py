"""A proposal may have only one unfinished rewrite; terminal attempts are retryable."""

import pytest

from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.constants import JOB_KIND_RESOLUTION_REWRITE, JOB_KIND_THREAD_AI_REPLY
from app.domains.ai.services.jobs.store import create_asset_thread_job
from app.domains.asset.models.asset import (
    AssetType,
    SddAsset,
    SddAssetResolutionProposal,
    SddAssetThread,
    SddAssetVersion,
)
from app.domains.asset.services.review.errors import ReviewError
from app.domains.asset.services.review.jobs import _create_asset_resolution_job_sync
from app.domains.task.services import task_cli_state_service
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace


@pytest.fixture
def review(monkeypatch):
    engine, factory = _build_db()
    with factory() as db:
        user, ws, task = _seed_workspace(db)
        asset = SddAsset(
            id="asset", workspace_id=ws.id, task_id=task.id, creator_id=user.id, asset_type=AssetType.SPEC, name="Spec"
        )
        version = SddAssetVersion(id="version", asset_id=asset.id, version_no=1, created_by=user.id)
        db.add_all([asset, version])
        db.flush()
        asset.active_version_id = version.id
        thread = SddAssetThread(
            id="thread",
            asset_id=asset.id,
            version_id=version.id,
            workspace_id=ws.id,
            task_id=task.id,
            creator_id=user.id,
            block_id="blk-1",
        )
        proposal = SddAssetResolutionProposal(
            id="proposal", thread_id=thread.id, base_version_id=version.id, creator_id=user.id
        )
        db.add_all([thread, proposal])
        db.commit()
    monkeypatch.setattr(task_cli_state_service, "ensure_bootstrap_ready_or_start", lambda *a, **k: None)
    yield factory
    engine.dispose()


def rewrite(db):
    return _create_asset_resolution_job_sync(
        db,
        ws_id="ws-1",
        asset_id="asset",
        thread_id="thread",
        creator_id="user-1",
        job_kind=JOB_KIND_RESOLUTION_REWRITE,
        context_json={"proposal_id": "proposal", "context_version_id": "version", "proposal_text": "Clarify"},
    )["payload"]


@pytest.mark.parametrize(
    "status",
    [AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL, AiJobStatus.TERMINATING, AiJobStatus.ORPHANED],
)
def test_unfinished_rewrite_rejected_across_sessions(review, status):
    with review() as db:
        first = rewrite(db)
        db.get(SddAiJob, first["id"]).status = status
        db.commit()
    with review() as db:
        with pytest.raises(ReviewError) as error:
            rewrite(db)
        assert error.value.status_code == 409
        assert error.value.detail["job_id"] == first["id"]
        assert db.query(SddAiJob).count() == 1


@pytest.mark.parametrize("status", [AiJobStatus.SUCCESS, AiJobStatus.FAILED, AiJobStatus.CANCELLED])
def test_finished_rewrite_allows_new_attempt(review, status):
    with review() as db:
        first = rewrite(db)
        db.get(SddAiJob, first["id"]).status = status
        db.commit()
    with review() as db:
        assert rewrite(db)["id"] != first["id"]
        assert db.query(SddAiJob).count() == 2


@pytest.mark.parametrize(
    "kind,proposal_id", [(JOB_KIND_THREAD_AI_REPLY, None), (JOB_KIND_RESOLUTION_REWRITE, "other-proposal")]
)
def test_unrelated_queued_job_does_not_block_rewrite(review, kind, proposal_id):
    with review() as db:
        create_asset_thread_job(
            db,
            workspace_id="ws-1",
            task_id="task-1",
            asset_id="asset",
            thread_id="thread",
            creator_id="user-1",
            prompt_text=None,
            job_kind=kind,
            context_json={"proposal_id": proposal_id},
        )
        assert rewrite(db)["status"] == AiJobStatus.PENDING.value
        assert db.query(SddAiJob).count() == 2
