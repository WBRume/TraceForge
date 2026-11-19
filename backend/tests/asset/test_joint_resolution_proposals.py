"""A direct comparison preserves the selected discussions and their provenance."""

from unittest.mock import AsyncMock

import pytest

from app.agents.domain_tools.contracts import DocumentRewrite
from app.domains.ai.models.ai_job import SddAiJob
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


def _seed_discussions(db):
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
    return user, workspace, asset, original, current, timeout, audit


async def _run_with_mock_agent(db, factory, base, prepared, monkeypatch):
    async def run_in_transaction(operation):
        with factory.begin() as session:
            return operation(session)

    async def submit_comparison(_prompt, _cwd, *, tool, **kwargs):
        assert tool.name == "submit_document_rewrite"
        assert kwargs["permission_mode"] == "read-only"
        artifact = DocumentRewrite(
            scope="document",
            document_markdown="Reject after 900 ms and record SIG-714.",
            change_summary="Specify the timeout and its audit code",
        )
        await tool.validate(artifact)
        # The tool validation transaction must not publish a draft.
        assert db.query(SddAssetResolutionProposal).count() == 1
        return {"artifact": artifact, "domain_milestones": [], "session_id": "joint-session"}

    turn = AsyncMock(side_effect=submit_comparison)
    monkeypatch.setattr(asset_thread, "run_domain_turn", turn)
    monkeypatch.setattr(asset_thread, "run_db_txn", run_in_transaction)
    monkeypatch.setattr(asset_thread, "lock_domain_attempt", lambda session, job_id, _: session.get(SddAiJob, job_id))
    monkeypatch.setattr(asset_thread.state, "update_job_state", AsyncMock())
    broadcast = AsyncMock()
    monkeypatch.setattr(asset_thread.asset_discussion_ws_manager, "broadcast", broadcast)
    await asset_thread._execute_rewrite_turn(base["job_id"], base, prepared, None)
    turn.assert_awaited_once()
    return broadcast


@pytest.mark.asyncio
async def test_joint_comparison_uses_one_turn_and_saves_a_reviewable_draft(monkeypatch):
    engine, factory = _build_db()
    monkeypatch.setattr(jobs.task_cli_state_service, "ensure_bootstrap_ready", lambda *_args, **_kw: None)
    monkeypatch.setattr(asset_thread, "attempt_is_current_sync", lambda *_args, **_kw: True)
    try:
        with _session(factory) as db:
            user, workspace, asset, original, current, timeout, audit = _seed_discussions(db)
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
                return jobs.create_joint_comparison_job(
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
            assert result["payload"]["context_json"]["job_kind"] == "RESOLUTION_REWRITE"
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
            prepared = asset_thread._build_joint_comparison_run(
                db,
                base,
                owner,
                {
                    **base,
                    "thread_cwd": ".",
                    "thread_backend": "mock",
                    "resume_session_id": None,
                    "fork_first_turn": False,
                },
            )
            assert "原引用 v1" in prepared["prompt"] and "原引用 v2" in prepared["prompt"]
            assert "Review decisions" in prepared["prompt"]
            assert "900 ms" in prepared["prompt"] and "SIG-714" in prepared["prompt"]
            assert set(prepared["source_message_ids"]) == {timeout.messages[0].id, audit.messages[0].id}
            db.commit()

            broadcast = await _run_with_mock_agent(db, factory, base, prepared, monkeypatch)

            completed = db.get(SddAiJob, base["job_id"])
            proposal = db.get(SddAssetResolutionProposal, completed.result_json["proposal_id"])
            assert proposal_sources.source_ids(proposal.proposed_patch_json) == sources
            assert set(proposal.proposed_patch_json["source_message_ids"]) == set(prepared["source_message_ids"])
            assert proposal.proposed_patch_json["rewrite_scope"] == "document"
            assert proposal.proposed_patch_json["rewrite_status"] == "ready"
            assert proposal.proposed_patch_json["merged_blocks_ast"]
            assert completed.completion_json["artifacts"][0]["id"] == proposal.id
            assert broadcast.await_args.args[1]["proposal"]["id"] == proposal.id
            assert old_draft.status == AssetResolutionProposalStatus.DRAFT
            db.refresh(owner)
            assert owner.cli_session_id is None
    finally:
        engine.dispose()
