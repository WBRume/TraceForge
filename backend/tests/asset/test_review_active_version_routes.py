from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.asset.models.asset import SddAssetResolutionProposal
from app.domains.asset.routers.assets import resolutions, threads
from app.domains.asset.services import asset_discussion_service
from app.domains.asset.services.document.versioning import create_asset_version_from_upload
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
