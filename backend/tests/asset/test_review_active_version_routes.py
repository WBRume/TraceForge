from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.constants import JOB_KIND_RESOLUTION_REWRITE
from app.domains.ai.services.jobs.store import create_asset_thread_job
from app.domains.asset.models.asset import SddAssetResolutionProposal
from app.domains.asset.routers.assets import resolutions, threads
from app.domains.asset.services import asset_discussion_service
from app.domains.asset.services.document.versioning import create_asset_version_from_upload
from app.domains.auth.models.user import User
from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace


def test_thread_reads_and_anchor_precheck_resolve_active_version(db, tmp_path):
    user, workspace, task = _seed_workspace(db, workspace_id="review-w", task_id="review-t")
    task.project_path = str(tmp_path)
    asset, version = create_asset_version_from_upload(
        db, task, creator_id=user.id, file_name="spec.md", file_content=b"# Spec\n\nContract.\n"
    )
    thread = asset_discussion_service.create_thread(
        db, asset=asset, version=version, creator_id=user.id, block_id="blk-2", body="Clarify contract"
    )
    proposal = SddAssetResolutionProposal(thread_id=thread.id, base_version_id=version.id, creator_id=user.id)
    db.add(proposal)
    db.commit()
    app = FastAPI()
    app.include_router(threads.router, prefix="/api/workspaces/{ws_id}/assets")
    app.include_router(resolutions.router, prefix="/api/workspaces/{ws_id}/assets")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    base = f"/api/workspaces/{workspace.id}/assets/{asset.id}/threads"
    with TestClient(app) as client:
        listed = client.get(base)
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"][0]["id"] == thread.id
        detail = client.get(base + "/" + thread.id)
        assert detail.status_code == 200, detail.text
        assert detail.json()["effective_anchor"]["block_id"] == "blk-2"
        # Older assets without an active pointer use the same fallback helper.
        asset.active_version_id = None
        db.commit()
        checked = client.post(base + f"/{thread.id}/resolution/proposals/{proposal.id}/anchor-precheck", json={})
        assert checked.status_code == 200, checked.text
        assert checked.json()["ok"] is True


def test_background_comparison_snapshot_requires_the_job_owner(db, tmp_path):
    user, workspace, task = _seed_workspace(db, workspace_id="jobs-w", task_id="jobs-t")
    task.project_path = str(tmp_path)
    asset, version = create_asset_version_from_upload(
        db, task, creator_id=user.id, file_name="spec.md", file_content=b"# Spec\n\nContract.\n"
    )
    thread = asset_discussion_service.create_thread(
        db, asset=asset, version=version, creator_id=user.id, block_id="blk-2", body="Clarify contract"
    )
    job = create_asset_thread_job(
        db,
        workspace_id=workspace.id,
        task_id=task.id,
        asset_id=asset.id,
        thread_id=thread.id,
        creator_id=user.id,
        prompt_text=None,
        job_kind=JOB_KIND_RESOLUTION_REWRITE,
    )
    job_id = job.id
    app = FastAPI()
    app.include_router(resolutions.background_router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    path = "/api/document-revision-jobs"
    with TestClient(app) as client:
        listed = client.get(path)
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()] == [job_id]

        job = db.get(SddAiJob, job_id)
        job.status = AiJobStatus.SUCCESS
        job.result_json = {"proposal_id": "saved-draft"}
        db.commit()
        assert client.get(path).json() == []
        restored = client.get(path, params={"job_ids": job_id})
        assert restored.json()[0]["result_json"]["proposal_id"] == "saved-draft"
        assert client.get(f"{path}/{job_id}").json()["status"] == "SUCCESS"

        app.dependency_overrides[get_current_user] = lambda: User(id="other-user")
        assert client.get(path, params={"job_ids": job_id}).json() == []
        assert client.get(f"{path}/{job_id}").status_code == 404
