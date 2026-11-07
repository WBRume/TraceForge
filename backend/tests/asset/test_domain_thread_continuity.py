import pytest

from app.domains.ai.services.jobs.executors import asset_thread
from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError
from app.domains.asset.models.asset import SddAssetResolutionProposal, SddAssetThread, SddAssetVersion
from tests.asset.test_review_rewrite_duplicates import review as review


@pytest.mark.parametrize("kind", ["proposal", "rewrite"])
def test_domain_session_pointer_commits_atomically_with_artifact(review, monkeypatch, kind):
    monkeypatch.setattr(asset_thread, "attempt_is_current_sync", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        asset_thread, "resolve_context_version", lambda db, **_kwargs: db.get(SddAssetVersion, "version")
    )
    monkeypatch.setattr(asset_thread, "serialize_proposal_for_ws", lambda proposal: {"id": proposal.id})
    monkeypatch.setattr(
        asset_thread.asset_resolution_service,
        "create_resolution_proposal",
        lambda db, **_kwargs: db.get(SddAssetResolutionProposal, "proposal"),
    )

    def rewrite(_db, *, proposal, **_kwargs):
        proposal.proposed_patch_json = {"rewrite_status": "ready", "merged_block_ast": {"text": "rewritten"}}
        return proposal

    monkeypatch.setattr(asset_thread.asset_resolution_service, "update_resolution_proposal_rewrite", rewrite)
    base = {
        "job_id": "job",
        "asset_id": "asset",
        "thread_id": "thread",
        "creator_id": "user-1",
        "proposal_id": "proposal",
    }

    def persist(db, **options):
        if kind == "proposal":
            return asset_thread._persist_asset_proposal_sync(db, base=base, proposal_text="suggestion", **options)
        return asset_thread._persist_asset_rewrite_sync(
            db,
            base=base,
            proposal_text="suggestion",
            rewritten_text="rewritten",
            rewrite_scope="anchor",
            rewritten_markdown="",
            selection_mode=False,
            **options,
        )

    with review() as db:
        db.get(SddAssetThread, "thread").cli_session_id = "previous"
        db.commit()
        if kind == "rewrite":
            persist(db, provider_session_id="child", validate_only=True)
            assert db.get(SddAssetThread, "thread").cli_session_id == "previous"
        persist(db, provider_session_id="child")
        db.rollback()
        assert db.get(SddAssetThread, "thread").cli_session_id == "previous"
        persist(db, provider_session_id="child")
        db.commit()
    with review() as db:
        assert db.get(SddAssetThread, "thread").cli_session_id == "child"
        monkeypatch.setattr(asset_thread, "attempt_is_current_sync", lambda *_args, **_kwargs: False)
        with pytest.raises(AgentAttemptFencedError):
            persist(db, provider_session_id="stale-child")
        assert db.get(SddAssetThread, "thread").cli_session_id == "child"
