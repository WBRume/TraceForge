"""Validate the resolved discussions used by a document-level proposal."""

from sqlalchemy.orm import Session, selectinload

from app.domains.asset.models.asset import (
    AssetResolutionProposalStatus,
    AssetThreadStatus,
    SddAsset,
    SddAssetResolutionProposal,
    SddAssetThread,
    SddAssetVersion,
)
from app.domains.asset.services.document import repository, transactions
from app.domains.asset.services.review.errors import ReviewError


def source_ids(value: dict | None) -> tuple[str, ...]:
    ids = value.get("source_thread_ids") if isinstance(value, dict) else None
    return tuple(sorted(set(ids))) if isinstance(ids, list) and all(isinstance(item, str) for item in ids) else ()


def matching_drafts(db: Session, thread_id: str, sources: tuple[str, ...], version_id: str):
    query = db.query(SddAssetResolutionProposal).filter(
        SddAssetResolutionProposal.thread_id == thread_id,
        SddAssetResolutionProposal.status == AssetResolutionProposalStatus.DRAFT,
    )
    if sources:
        query = query.filter(SddAssetResolutionProposal.base_version_id == version_id)
    return [
        proposal
        for proposal in query.order_by(
            SddAssetResolutionProposal.updated_at.desc(), SddAssetResolutionProposal.created_at.desc()
        ).all()
        if source_ids(proposal.proposed_patch_json) == sources
    ]


def validate_sources(
    db: Session,
    asset: SddAsset,
    sources: tuple[str, ...],
    version_id: str,
    *,
    lock: bool = False,
) -> tuple[SddAssetVersion, list[SddAssetThread]]:
    if lock:
        transactions.lock_asset(db, asset)
    if not version_id or asset.active_version_id != version_id:
        raise ReviewError(409, "The published document version changed. Refresh to continue.")
    version = repository.get_asset_version(db, asset.id, version_id)
    if not version:
        raise ReviewError(404, "Document version not found")
    query = (
        db.query(SddAssetThread)
        .options(
            selectinload(SddAssetThread.messages),
            selectinload(SddAssetThread.version).load_only(SddAssetVersion.version_no),
        )
        .filter(
            SddAssetThread.asset_id == asset.id,
            SddAssetThread.id.in_(sources),
        )
        .order_by(SddAssetThread.id)
        .populate_existing()
    )
    if lock:
        query = query.with_for_update()
    threads = query.all()
    if len(threads) != len(sources):
        raise ReviewError(404, "A selected discussion was not found in this document")
    if any(thread.status != AssetThreadStatus.RESOLVED for thread in threads):
        raise ReviewError(409, "Only resolved discussions can be used in a joint proposal")
    return version, threads
