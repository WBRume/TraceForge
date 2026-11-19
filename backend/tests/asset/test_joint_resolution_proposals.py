"""Joint proposals preserve the exact discussion and message provenance."""

import pytest

from app.domains.ai.services.jobs.executors import asset_thread
from app.domains.asset.models.asset import (
    AssetResolutionProposalStatus,
    AssetThreadStatus,
    AssetType,
    SddAsset,
    SddAssetResolutionProposal,
    SddAssetVersion,
)
from app.domains.asset.schemas.asset import AssetJointProposalCreateRequest
from app.domains.asset.services import asset_discussion_service
from app.domains.asset.services.review import jobs, proposal_sources
from app.domains.asset.services.review.errors import ReviewError
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session


def test_joint_proposal_uses_each_resolved_discussion_and_keeps_other_drafts(monkeypatch):
    engine, factory = _build_db()
    monkeypatch.setattr(jobs.task_cli_state_service, "ensure_bootstrap_ready", lambda *_args, **_kw: None)
    monkeypatch.setattr(asset_thread, "attempt_is_current_sync", lambda *_args, **_kw: True)
    try:
        with _session(factory) as db:
            user, workspace, task = _seed_workspace(db)
            asset = SddAsset(
                id="joint-asset",
                workspace_id=workspace.id,
                task_id=task.id,
                creator_id=user.id,
                asset_type=AssetType.SPEC,
                name="Acceptance",
            )
            db.add(asset)
            db.flush()
            blocks = [{"id": "b", "type": "paragraph", "text": "Review decisions"}]
            original = SddAssetVersion(asset_id=asset.id, version_no=1, created_by=user.id, blocks_json=blocks)
            current = SddAssetVersion(asset_id=asset.id, version_no=2, created_by=user.id, blocks_json=blocks)
            db.add_all([original, current])
            db.flush()
            asset.active_version_id = current.id
            timeout = asset_discussion_service.create_thread(
                db,
                asset=asset,
                version=original,
                creator_id=user.id,
                block_id="b",
                selected_text="timeout",
                body="Timeout must reject after 900 ms",
            )
            audit = asset_discussion_service.create_thread(
                db,
                asset=asset,
                version=current,
                creator_id=user.id,
                block_id="b",
                selected_text="Review",
                body="Audit code is SIG-714",
            )
            timeout.status = AssetThreadStatus.RESOLVED
            db.flush()
            # The same quote and block ID do not make a future discussion valid in the old version.
            assert (
                asset_discussion_service.resolve_thread_anchor_for_version(
                    db,
                    thread=audit,
                    context_version=original,
                )["anchor_status"]
                == "missing"
            )
            request = AssetJointProposalCreateRequest(
                thread_ids=[timeout.id, audit.id],
                context_version_id=current.id,
            )

            def enqueue():
                return jobs.create_joint_proposal_job(
                    db,
                    ws_id=workspace.id,
                    asset_id=asset.id,
                    user_id=user.id,
                    data=request,
                )

            with pytest.raises(ReviewError, match="Only resolved"):
                enqueue()
            audit.status = AssetThreadStatus.RESOLVED
            result = enqueue()
            retry = enqueue()
            assert result["created"] and not retry["created"]
            assert result["payload"]["id"] == retry["payload"]["id"]
            sources = tuple(sorted((timeout.id, audit.id)))
            owner = db.get(type(audit), sources[0])
            old_draft = SddAssetResolutionProposal(
                thread_id=owner.id,
                base_version_id=current.id,
                creator_id=user.id,
                proposed_patch_json={},
            )
            db.add(old_draft)
            db.flush()
            base = {
                "job_id": result["payload"]["id"],
                "creator_id": user.id,
                "asset_id": asset.id,
                "thread_id": owner.id,
                "bootstrap_version_id": current.id,
                "document_name": asset.name,
                "context_json": result["payload"]["context_json"],
            }
            prepared = asset_thread._build_proposal_run(db, base, owner, task, owner.version, {**base})
            assert "原引用 v1" in prepared["prompt"] and "原引用 v2" in prepared["prompt"]
            assert "900 ms" in prepared["prompt"] and "SIG-714" in prepared["prompt"]
            assert set(prepared["source_message_ids"]) == {timeout.messages[0].id, audit.messages[0].id}
            saved = asset_thread._persist_asset_proposal_sync(
                db,
                base=prepared,
                proposal_text="Reject after 900 ms and record SIG-714",
                provider_session_id="joint-session",
            )
            proposal = db.get(SddAssetResolutionProposal, saved["proposal_id"])
            assert proposal_sources.source_ids(proposal.proposed_patch_json) == sources
            assert proposal.proposed_patch_json["rewrite_scope"] == "document"
            assert old_draft.status == AssetResolutionProposalStatus.DRAFT
            assert owner.cli_session_id is None
    finally:
        engine.dispose()
