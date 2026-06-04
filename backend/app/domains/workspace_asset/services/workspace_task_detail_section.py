"""
Task Detail section-specific query services.

Each function loads ONLY the data needed for its section,
avoiding the full task relationship graph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.asset.services import asset_document_service
from app.domains.asset.services.decision_service import decision_source_response
from app.domains.task.models.task import SddTask
from app.domains.task.services import task_service
from app.domains.workflow.models.task_change import (
    SddTaskChangeProposal,
    SddTaskChangeProposalFile,
    SddTaskConflictReport,
    SddTaskVerificationRun,
)
from app.domains.workspace_asset.models.workspace_asset import (
    SddAiOutput,
    SddClarification,
    SddDecision,
    SddDeltaRegion,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddHumanReviewComment,
    SddTaskFinalSummary,
    SddTaskProcessAuditLog,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    ClarificationLightResponse,
    ClarificationResponse,
    DecisionLightResponse,
    DecisionResponse,
    DeltaRegionResponse,
    EvidenceLightResponse,
    EvidenceResponse,
    ExternalEvidenceRef,
    HumanDeltaFileDiff,
    HumanDeltaLightResponse,
    HumanDeltaResponse,
    HumanReviewCommentResponse,
    PatchSnapshot,
    HumanReviewLightResponse,
    HumanReviewResponse,
    TaskClarificationsSectionResponse,
    TaskDecisionsSectionResponse,
    TaskDetailSummaryResponse,
    TaskEvidenceSectionResponse,
    TaskFileDiffResponse,
    TaskFileItemLightResponse,
    TaskFileItemResponse,
    TaskFilesSectionResponse,
    TaskFinalSummaryResponse,
    TaskHumanDeltasSectionResponse,
    TaskHumanReviewsSectionResponse,
    TaskProcessAuditLogLightResponse,
    TaskProcessAuditLogResponse,
    TaskProcessAuditSectionResponse,
    WorkbenchDeltaResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _short_text(value: Any, limit: int = 280) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _paginated(query, page: int, page_size: int):
    """Apply pagination to a SQLAlchemy query and return (items, total)."""
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


# ---------------------------------------------------------------------------
# Task File section
# ---------------------------------------------------------------------------

def _task_file_from_asset_light(asset: SddAsset) -> TaskFileItemLightResponse:
    return TaskFileItemLightResponse(
        id=asset.id,
        file_type=_enum_value(asset.asset_type),
        title=asset.name,
        status="AVAILABLE",
        source_kind="asset",
        source_id=asset.id,
        source_version_id=asset.active_version_id,
        source_path=asset.source_file_name,
        summary=_short_text(asset.content_text, limit=500),
        created_at=asset.created_at,
    )


def _task_file_from_ai_output_light(output: SddAiOutput) -> TaskFileItemLightResponse:
    return TaskFileItemLightResponse(
        id=output.id,
        file_type=f"AI_OUTPUT:{_enum_value(output.output_type)}",
        title=output.title or f"AI Output {output.id}",
        status="AVAILABLE",
        source_kind="ai_output",
        source_id=output.ai_job_id,
        source_version_id=output.asset_version_id,
        summary=_short_text(output.content_text, limit=500),
        created_at=output.created_at,
    )


def _task_file_from_change_proposal_light(proposal: SddTaskChangeProposal) -> TaskFileItemLightResponse:
    return TaskFileItemLightResponse(
        id=proposal.id,
        file_type="GIT_PATCH",
        title=f"Change Proposal #{proposal.proposal_no} Patch Set {proposal.patch_set_no}",
        status=_enum_value(proposal.status),
        source_kind="change_proposal",
        source_id=proposal.id,
        source_version_id=proposal.patch_asset_version_id,
        summary=proposal.summary,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _task_file_from_change_file_light(file_item: SddTaskChangeProposalFile) -> TaskFileItemLightResponse:
    return TaskFileItemLightResponse(
        id=file_item.id,
        file_type="GIT_PATCH_FILE",
        title=file_item.file_path,
        status=_enum_value(file_item.change_type),
        source_kind="change_proposal_file",
        source_id=file_item.proposal_id,
        source_path=file_item.file_path,
        summary=_short_text(file_item.diff_excerpt, limit=500),
        created_at=file_item.created_at,
    )


def _task_file_from_verification_light(run: SddTaskVerificationRun) -> TaskFileItemLightResponse:
    return TaskFileItemLightResponse(
        id=run.id,
        file_type="VERIFICATION_LOG",
        title=run.command or f"Verification Run {run.id}",
        status=_enum_value(run.status),
        source_kind="verification_run",
        source_id=run.proposal_id,
        source_version_id=run.log_asset_version_id,
        summary=_short_text(run.log_excerpt, limit=500),
        created_at=run.created_at,
    )


def _task_file_from_conflict_light(report: SddTaskConflictReport) -> TaskFileItemLightResponse:
    return TaskFileItemLightResponse(
        id=report.id,
        file_type="CONFLICT_REPORT",
        title=f"Conflict Report {report.id}",
        status=_enum_value(report.status),
        source_kind="conflict_report",
        source_id=report.proposal_id,
        summary=_short_text(report.stderr_excerpt, limit=500),
        created_at=report.created_at,
    )


def get_task_files(
    db: Session,
    workspace_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 10,
) -> TaskFilesSectionResponse:
    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id).first()
    if not task:
        return TaskFilesSectionResponse()

    asset_document_service.ensure_spec_asset_backfilled(db, task)
    db.commit()

    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 10)))

    specs = (
        db.query(SddAsset)
        .filter(SddAsset.workspace_id == workspace_id, SddAsset.task_id == task_id, SddAsset.asset_type == AssetType.SPEC)
        .order_by(SddAsset.created_at.desc())
        .all()
    )
    plans = (
        db.query(SddAsset)
        .filter(SddAsset.workspace_id == workspace_id, SddAsset.task_id == task_id, SddAsset.asset_type == AssetType.PLAN)
        .order_by(SddAsset.created_at.desc())
        .all()
    )
    ai_outputs = (
        db.query(SddAiOutput)
        .filter(SddAiOutput.workspace_id == workspace_id, SddAiOutput.task_id == task_id)
        .order_by(SddAiOutput.created_at.desc())
        .all()
    )
    change_proposals = (
        db.query(SddTaskChangeProposal)
        .filter(SddTaskChangeProposal.workspace_id == workspace_id, SddTaskChangeProposal.task_id == task_id)
        .order_by(SddTaskChangeProposal.created_at.desc())
        .all()
    )
    verification_runs = (
        db.query(SddTaskVerificationRun)
        .filter(SddTaskVerificationRun.workspace_id == workspace_id, SddTaskVerificationRun.task_id == task_id)
        .order_by(SddTaskVerificationRun.created_at.desc())
        .all()
    )
    conflict_reports = (
        db.query(SddTaskConflictReport)
        .filter(SddTaskConflictReport.workspace_id == workspace_id, SddTaskConflictReport.task_id == task_id)
        .order_by(SddTaskConflictReport.created_at.desc())
        .all()
    )

    items: List[TaskFileItemLightResponse] = []
    items.extend(_task_file_from_asset_light(a) for a in [*specs, *plans])
    items.extend(_task_file_from_ai_output_light(o) for o in ai_outputs)
    items.extend(_task_file_from_change_proposal_light(p) for p in change_proposals)
    items.extend(_task_file_from_verification_light(r) for r in verification_runs)
    items.extend(_task_file_from_conflict_light(r) for r in conflict_reports)

    existing_paths = {item.source_path for item in items if item.source_path}
    try:
        superpowers = task_service.list_superpowers_docs(task)
        for section_key in ("specs", "plans"):
            file_type = section_key.upper().rstrip("S")
            for entry in superpowers.get(section_key, []):
                rel_path = entry.get("relative_path", "")
                if not rel_path or rel_path in existing_paths:
                    continue
                existing_paths.add(rel_path)
                items.append(TaskFileItemLightResponse(
                    id=f"sp:{rel_path}",
                    file_type=file_type,
                    title=entry.get("name", rel_path),
                    status="AVAILABLE",
                    source_kind="superpowers_doc",
                    source_path=rel_path,
                    summary=None,
                    created_at=entry.get("updated_at"),
                ))
    except Exception:
        pass

    items.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
    total = len(items)

    start = (page - 1) * page_size
    paged = items[start : start + page_size]

    return TaskFilesSectionResponse(items=paged, total=total, page=page, page_size=page_size)


def get_task_file_detail(
    db: Session,
    workspace_id: str,
    task_id: str,
    file_id: str,
) -> Optional[TaskFileItemResponse]:
    """Load full task file item with metadata."""
    from app.domains.workspace_asset.services.workspace_task_detail_service import (
        _task_file_from_asset,
        _task_file_from_ai_output,
        _task_file_from_change_file,
        _task_file_from_change_proposal,
        _task_file_from_conflict,
        _task_file_from_verification,
    )

    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id).first()
    if not task:
        return None

    # Search across all source types
    # Check assets (specs/plans)
    asset = db.query(SddAsset).filter(SddAsset.id == file_id, SddAsset.workspace_id == workspace_id).first()
    if asset:
        return _task_file_from_asset(asset)

    # Check AI outputs
    ai_output = db.query(SddAiOutput).filter(SddAiOutput.id == file_id, SddAiOutput.workspace_id == workspace_id).first()
    if ai_output:
        return _task_file_from_ai_output(ai_output)

    # Check change proposals
    proposal = (
        db.query(SddTaskChangeProposal)
        .options(selectinload(SddTaskChangeProposal.files))
        .filter(SddTaskChangeProposal.id == file_id, SddTaskChangeProposal.workspace_id == workspace_id)
        .first()
    )
    if proposal:
        return _task_file_from_change_proposal(proposal)

    # Check change proposal files
    change_file = (
        db.query(SddTaskChangeProposalFile)
        .filter(SddTaskChangeProposalFile.id == file_id)
        .first()
    )
    if change_file:
        return _task_file_from_change_file(change_file)

    # Check verification runs
    run = (
        db.query(SddTaskVerificationRun)
        .filter(SddTaskVerificationRun.id == file_id, SddTaskVerificationRun.workspace_id == workspace_id)
        .first()
    )
    if run:
        return _task_file_from_verification(run)

    # Check conflict reports
    report = (
        db.query(SddTaskConflictReport)
        .filter(SddTaskConflictReport.id == file_id, SddTaskConflictReport.workspace_id == workspace_id)
        .first()
    )
    if report:
        return _task_file_from_conflict(report)

    return None


def get_task_file_diff(
    db: Session,
    workspace_id: str,
    task_id: str,
    file_id: str,
) -> Optional[TaskFileDiffResponse]:
    """Load full diff text for a patch file. Loads the patch asset content on demand."""
    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id).first()
    if not task:
        return None

    # Check if file_id is a change proposal
    proposal = (
        db.query(SddTaskChangeProposal)
        .filter(SddTaskChangeProposal.id == file_id, SddTaskChangeProposal.workspace_id == workspace_id)
        .first()
    )
    if proposal and proposal.patch_asset_id:
        asset = db.query(SddAsset).filter(SddAsset.id == proposal.patch_asset_id).first()
        if asset and asset.content_text:
            return TaskFileDiffResponse(file_id=file_id, diff_text=asset.content_text)

    # Check if file_id is a change proposal file - load parent proposal's patch
    change_file = db.query(SddTaskChangeProposalFile).filter(SddTaskChangeProposalFile.id == file_id).first()
    if change_file:
        parent_proposal = (
            db.query(SddTaskChangeProposal)
            .filter(SddTaskChangeProposal.id == change_file.proposal_id)
            .first()
        )
        if parent_proposal and parent_proposal.patch_asset_id:
            asset = db.query(SddAsset).filter(SddAsset.id == parent_proposal.patch_asset_id).first()
            if asset and asset.content_text:
                return TaskFileDiffResponse(file_id=file_id, diff_text=asset.content_text)

    # Check if file_id is an asset with patch content
    asset = db.query(SddAsset).filter(SddAsset.id == file_id, SddAsset.workspace_id == workspace_id).first()
    if asset and asset.content_text:
        return TaskFileDiffResponse(file_id=file_id, diff_text=asset.content_text)

    return None


# ---------------------------------------------------------------------------
# Human Reviews section
# ---------------------------------------------------------------------------

def get_task_human_reviews(
    db: Session,
    workspace_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 50,
) -> TaskHumanReviewsSectionResponse:
    query = (
        db.query(SddHumanReview)
        .filter(SddHumanReview.workspace_id == workspace_id, SddHumanReview.task_id == task_id)
        .order_by(SddHumanReview.created_at.desc())
    )
    items, total = _paginated(query, page, page_size)

    result = []
    for review in items:
        comment_count = (
            db.query(func.count(SddHumanReviewComment.id))
            .filter(SddHumanReviewComment.review_id == review.id)
            .scalar()
            or 0
        )
        result.append(HumanReviewLightResponse(
            id=review.id,
            workspace_id=review.workspace_id,
            task_id=review.task_id,
            reviewer_id=review.reviewer_id,
        status=_enum_value(review.status),
        outcome=_enum_value(review.outcome) if review.outcome else None,
        review_type=review.review_type,
        review_scope=review.review_scope,
        priority=review.priority,
        title=review.title,
        due_date=review.due_date,
        resolved_at=review.resolved_at,
        linked_clarification_ids=[
            link.clarification_id for link in (review.clarification_links or [])
        ],
        comment_count=comment_count,
        created_at=review.created_at,
        updated_at=review.updated_at,
        ))

    return TaskHumanReviewsSectionResponse(items=result, total=total, page=page, page_size=page_size)


def get_task_human_review_detail(db: Session, workspace_id: str, task_id: str, review_id: str) -> Optional[HumanReviewResponse]:
    review = (
        db.query(SddHumanReview)
        .options(selectinload(SddHumanReview.comments))
        .filter(
            SddHumanReview.id == review_id,
            SddHumanReview.workspace_id == workspace_id,
            SddHumanReview.task_id == task_id,
        )
        .first()
    )
    if not review:
        return None
    return HumanReviewResponse(
        id=review.id,
        workspace_id=review.workspace_id,
        task_id=review.task_id,
        reviewer_id=review.reviewer_id,
        status=_enum_value(review.status),
        outcome=_enum_value(review.outcome) if review.outcome else None,
        review_type=review.review_type,
        title=review.title,
        body=review.body,
        source_ref=review.source_ref_json if isinstance(review.source_ref_json, dict) else None,
        target_ref=review.target_ref_json if isinstance(review.target_ref_json, dict) else None,
        review_scope=review.review_scope,
        priority=review.priority,
        due_date=review.due_date,
        resolved_at=review.resolved_at,
        linked_clarification_ids=[
            link.clarification_id for link in (review.clarification_links or [])
        ],
        comments=[
            HumanReviewCommentResponse(
                id=c.id,
                workspace_id=c.workspace_id,
                task_id=c.task_id,
                review_id=c.review_id,
                author_id=c.author_id,
                comment_type=c.comment_type,
                body=c.body,
                required_change=c.required_change_json if isinstance(c.required_change_json, dict) else None,
                created_at=c.created_at,
            )
            for c in sorted(review.comments or [], key=lambda x: x.created_at or datetime.min)
        ],
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


# ---------------------------------------------------------------------------
# Human Deltas section
# ---------------------------------------------------------------------------

def get_task_human_deltas(
    db: Session,
    workspace_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 10,
) -> TaskHumanDeltasSectionResponse:
    from app.domains.workspace_asset.services.human_delta_compare_service import (
        _evidence_summary,
        _proposal_summary,
    )

    query = (
        db.query(SddHumanDelta)
        .filter(SddHumanDelta.workspace_id == workspace_id, SddHumanDelta.task_id == task_id)
        .order_by(SddHumanDelta.created_at.desc())
    )
    items, total = _paginated(query, page, page_size)

    result = []
    for delta in items:
        proposal_summary = _proposal_summary(delta.proposal) if delta.proposal else None
        evidence_summary = _evidence_summary(delta.final_evidence) if delta.final_evidence else None
        decision_count = len(delta.decisions or [])
        result.append(HumanDeltaLightResponse(
            id=delta.id,
            workspace_id=delta.workspace_id,
            task_id=delta.task_id,
            proposal_id=delta.proposal_id,
            final_evidence_id=delta.final_evidence_id,
            status=_enum_value(delta.status),
            diff_asset_id=delta.diff_asset_id,
            changed_files_count=delta.changed_files_count,
            insertions=delta.insertions,
            deletions=delta.deletions,
            comparison_summary=delta.comparison_summary,
            change_category=delta.change_category,
            change_reason=delta.change_reason,
            promote_candidate=bool(delta.promote_candidate),
            proposal_summary=proposal_summary,
            final_evidence_summary=evidence_summary,
            decision_count=decision_count,
            created_at=delta.created_at,
            updated_at=delta.updated_at,
        ))

    return TaskHumanDeltasSectionResponse(items=result, total=total, page=page, page_size=page_size)


def get_task_human_delta_detail(db: Session, workspace_id: str, task_id: str, delta_id: str) -> Optional[HumanDeltaResponse]:
    from app.domains.workspace_asset.services.workspace_task_detail_service import human_delta_response
    from app.domains.workspace_asset.services.human_delta_compare_service import _parse_patch_to_files

    delta = (
        db.query(SddHumanDelta)
        .filter(
            SddHumanDelta.id == delta_id,
            SddHumanDelta.workspace_id == workspace_id,
            SddHumanDelta.task_id == task_id,
        )
        .first()
    )
    if not delta:
        return None

    # Load diff text and structured file diffs
    diff_text = None
    file_diffs = None
    if delta.diff_asset_id:
        asset = db.query(SddAsset).filter(SddAsset.id == delta.diff_asset_id).first()
        if asset:
            diff_text = asset.content_text
            # Read pre-computed structured diffs (with comparison_type, source, per-side stats)
            content_json = getattr(asset, 'content_json', None)
            if isinstance(content_json, dict) and content_json.get("file_diffs"):
                file_diffs = content_json["file_diffs"]
            elif diff_text:
                # Fallback: re-parse if structured data not available
                file_diffs = _parse_patch_to_files(diff_text)

    return human_delta_response(delta, diff_text=diff_text, file_diffs=file_diffs)


def get_task_delta_workbench(
    db: Session, workspace_id: str, task_id: str, delta_id: str
) -> Optional[WorkbenchDeltaResponse]:
    """Load full workbench data for a delta: file_diffs, delta_regions, patch snapshots, decisions."""
    from app.domains.workspace_asset.services.human_delta_compare_service import (
        _evidence_summary,
        _proposal_summary,
        _parse_patch_to_files,
    )

    delta = (
        db.query(SddHumanDelta)
        .filter(
            SddHumanDelta.id == delta_id,
            SddHumanDelta.workspace_id == workspace_id,
            SddHumanDelta.task_id == task_id,
        )
        .first()
    )
    if not delta:
        return None

    # Load diff text and structured file diffs
    diff_text = None
    file_diffs: List[Dict[str, Any]] = []
    if delta.diff_asset_id:
        asset = db.query(SddAsset).filter(SddAsset.id == delta.diff_asset_id).first()
        if asset:
            diff_text = asset.content_text
            content_json = getattr(asset, "content_json", None)
            if isinstance(content_json, dict) and content_json.get("file_diffs"):
                file_diffs = content_json["file_diffs"]
            elif diff_text:
                file_diffs = _parse_patch_to_files(diff_text)

    parsed_file_diffs = [HumanDeltaFileDiff(**fd) for fd in file_diffs]

    # Load delta regions with their decisions
    regions = (
        db.query(SddDeltaRegion)
        .filter(SddDeltaRegion.delta_id == delta_id)
        .order_by(SddDeltaRegion.file_path, SddDeltaRegion.created_at)
        .all()
    )
    region_responses: List[DeltaRegionResponse] = []
    for region in regions:
        region_decisions = [
            _decision_light(d)
            for d in (region.decisions or [])
        ]
        region_responses.append(
            DeltaRegionResponse(
                id=region.id,
                delta_id=region.delta_id,
                file_path=region.file_path,
                old_file_path=region.old_file_path,
                region_type=_enum_value(region.region_type),
                region_source=_enum_value(region.region_source),
                ai_line_start=region.ai_line_start,
                ai_line_end=region.ai_line_end,
                human_line_start=region.human_line_start,
                human_line_end=region.human_line_end,
                ai_insertions=region.ai_insertions,
                ai_deletions=region.ai_deletions,
                human_insertions=region.human_insertions,
                human_deletions=region.human_deletions,
                summary=region.summary,
                decisions=region_decisions,
                created_at=region.created_at,
            )
        )

    # Build patch snapshots
    ai_patch = None
    if delta.proposal:
        proposal = delta.proposal
        ai_patch = PatchSnapshot(
            source_type="proposal",
            source_id=proposal.id,
            source_label=f"Proposal #{proposal.proposal_no} (Patch Set {proposal.patch_set_no})",
            base_commit_sha=proposal.base_commit_sha,
            head_commit_sha=proposal.cloud_head_sha,
            changed_files_count=proposal.changed_files_count or 0,
            insertions=proposal.insertions or 0,
            deletions=proposal.deletions or 0,
        )

    human_patch = None
    if delta.final_evidence:
        evidence = delta.final_evidence
        human_file_count = 0
        human_ins_total = 0
        human_del_total = 0
        for fd in parsed_file_diffs:
            if fd.comparison_type == "human_only":
                human_file_count += 1
                human_ins_total += fd.insertions
                human_del_total += fd.deletions
            elif fd.comparison_type == "common":
                human_file_count += 1
                human_ins_total += fd.human_insertions
                human_del_total += fd.human_deletions
        human_patch = PatchSnapshot(
            source_type="evidence",
            source_id=evidence.id,
            source_label=evidence.title or evidence.source_ref or evidence.source_type,
            base_commit_sha=None,
            head_commit_sha=evidence.source_ref if evidence.source_type in ("COMMIT", "MR") else None,
            changed_files_count=human_file_count,
            insertions=human_ins_total,
            deletions=human_del_total,
        )

    # Load linked decisions
    decisions = [
        _decision_light(d)
        for d in (delta.decisions or [])
    ]

    return WorkbenchDeltaResponse(
        id=delta.id,
        workspace_id=delta.workspace_id,
        task_id=delta.task_id,
        status=_enum_value(delta.status),
        change_category=delta.change_category,
        change_reason=delta.change_reason,
        promote_candidate=bool(delta.promote_candidate),
        ai_patch=ai_patch,
        human_patch=human_patch,
        file_diffs=parsed_file_diffs,
        delta_regions=region_responses,
        changed_files_count=delta.changed_files_count,
        insertions=delta.insertions,
        deletions=delta.deletions,
        comparison_summary=delta.comparison_summary,
        decision_count=len(decisions),
        decisions=decisions,
        created_at=delta.created_at,
        updated_at=delta.updated_at,
    )


# ---------------------------------------------------------------------------
# Evidence section
# ---------------------------------------------------------------------------

def _evidence_light(evidence: SddEvidence) -> EvidenceLightResponse:
    return EvidenceLightResponse(
        id=evidence.id,
        workspace_id=evidence.workspace_id,
        requirement_id=evidence.requirement_id,
        task_id=evidence.task_id,
        ai_job_id=evidence.ai_job_id,
        human_review_id=evidence.human_review_id,
        status=_enum_value(evidence.status),
        evidence_type=_enum_value(evidence.evidence_type),
        source_type=_enum_value(evidence.source_type),
        source_uri=evidence.source_uri,
        source_label=evidence.source_label,
        source_ref=evidence.source_ref,
        source_path=evidence.source_path,
        title=evidence.title,
        summary=evidence.summary,
        confirmed_by_id=evidence.confirmed_by_id,
        confirmed_at=evidence.confirmed_at,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
    )


def get_task_evidence(
    db: Session,
    workspace_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 50,
) -> TaskEvidenceSectionResponse:
    query = (
        db.query(SddEvidence)
        .filter(SddEvidence.workspace_id == workspace_id, SddEvidence.task_id == task_id)
        .order_by(SddEvidence.created_at.desc())
    )
    items, total = _paginated(query, page, page_size)
    return TaskEvidenceSectionResponse(
        items=[_evidence_light(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_task_evidence_detail(db: Session, workspace_id: str, task_id: str, evidence_id: str) -> Optional[EvidenceResponse]:
    from app.domains.workspace_asset.services.workspace_asset_service import _evidence_response

    evidence = (
        db.query(SddEvidence)
        .filter(
            SddEvidence.id == evidence_id,
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
        )
        .first()
    )
    if not evidence:
        return None
    return _evidence_response(evidence)


# ---------------------------------------------------------------------------
# Decisions section
# ---------------------------------------------------------------------------

def _decision_light(decision: SddDecision) -> DecisionLightResponse:
    return DecisionLightResponse(
        id=decision.id,
        workspace_id=decision.workspace_id,
        task_id=decision.task_id,
        requirement_id=decision.requirement_id,
        human_delta_id=decision.human_delta_id,
        delta_region_id=decision.delta_region_id,
        status=_enum_value(decision.status),
        title=decision.title,
        impact_scope=decision.impact_scope,
        source_evidence_id=decision.source_evidence_id,
        source_type=_enum_value(decision.source_type),
        source=decision_source_response(decision),
        decided_by_id=decision.decided_by_id,
        promote_candidate=decision.promote_candidate,
        delta_line_refs=decision.delta_line_refs_json if isinstance(decision.delta_line_refs_json, list) else None,
        created_at=decision.created_at,
        updated_at=decision.updated_at,
    )


def get_task_decisions(
    db: Session,
    workspace_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 50,
) -> TaskDecisionsSectionResponse:
    query = (
        db.query(SddDecision)
        .filter(SddDecision.workspace_id == workspace_id, SddDecision.task_id == task_id)
        .order_by(SddDecision.created_at.desc())
    )
    items, total = _paginated(query, page, page_size)
    return TaskDecisionsSectionResponse(
        items=[_decision_light(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_task_decision_detail(db: Session, workspace_id: str, task_id: str, decision_id: str) -> Optional[DecisionResponse]:
    from app.domains.workspace_asset.services.workspace_asset_service import _decision_response

    decision = (
        db.query(SddDecision)
        .filter(
            SddDecision.id == decision_id,
            SddDecision.workspace_id == workspace_id,
            SddDecision.task_id == task_id,
        )
        .first()
    )
    if not decision:
        return None
    return _decision_response(decision)


# ---------------------------------------------------------------------------
# Clarifications section
# ---------------------------------------------------------------------------

def _clarification_light(clarification: SddClarification) -> ClarificationLightResponse:
    return ClarificationLightResponse(
        id=clarification.id,
        workspace_id=clarification.workspace_id,
        task_id=clarification.task_id,
        requirement_id=clarification.requirement_id,
        status=_enum_value(clarification.status),
        blocking_level=_enum_value(clarification.blocking_level),
        question=clarification.question,
        requester_id=clarification.requester_id,
        responder_id=clarification.responder_id,
        source_evidence_id=clarification.source_evidence_id,
        source_review_id=clarification.source_review_id,
        clarification_type=clarification.clarification_type,
        urgency=clarification.urgency,
        answered_at=clarification.answered_at,
        accepted_at=clarification.accepted_at,
        promote_candidate=clarification.promote_candidate,
        converted_requirement_id=clarification.converted_requirement_id,
        created_at=clarification.created_at,
        updated_at=clarification.updated_at,
    )


def get_task_clarifications(
    db: Session,
    workspace_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 50,
) -> TaskClarificationsSectionResponse:
    query = (
        db.query(SddClarification)
        .filter(SddClarification.workspace_id == workspace_id, SddClarification.task_id == task_id)
        .order_by(SddClarification.created_at.desc())
    )
    items, total = _paginated(query, page, page_size)
    return TaskClarificationsSectionResponse(
        items=[_clarification_light(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_task_clarification_detail(db: Session, workspace_id: str, task_id: str, clarification_id: str) -> Optional[ClarificationResponse]:
    from app.domains.workspace_asset.services.workspace_asset_service import _clarification_response

    clarification = (
        db.query(SddClarification)
        .filter(
            SddClarification.id == clarification_id,
            SddClarification.workspace_id == workspace_id,
            SddClarification.task_id == task_id,
        )
        .first()
    )
    if not clarification:
        return None
    return _clarification_response(clarification)


# ---------------------------------------------------------------------------
# Final Summary section
# ---------------------------------------------------------------------------

def get_task_final_summary(
    db: Session,
    workspace_id: str,
    task_id: str,
) -> Optional[TaskFinalSummaryResponse]:
    from app.domains.workspace_asset.services.workspace_asset_service import _final_summary_response

    summary = (
        db.query(SddTaskFinalSummary)
        .filter(
            SddTaskFinalSummary.workspace_id == workspace_id,
            SddTaskFinalSummary.task_id == task_id,
        )
        .first()
    )
    if not summary:
        return None
    return _final_summary_response(summary)


# ---------------------------------------------------------------------------
# Process Audit section
# ---------------------------------------------------------------------------

def _audit_log_light(log: SddTaskProcessAuditLog) -> TaskProcessAuditLogLightResponse:
    return TaskProcessAuditLogLightResponse(
        id=log.id,
        workspace_id=log.workspace_id,
        task_id=log.task_id,
        actor_id=log.actor_id,
        record_type=_enum_value(log.record_type),
        record_id=log.record_id,
        action=_enum_value(log.action),
        reason=log.reason,
        created_at=log.created_at,
    )


def get_task_process_audit(
    db: Session,
    workspace_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 10,
) -> TaskProcessAuditSectionResponse:
    query = (
        db.query(SddTaskProcessAuditLog)
        .filter(
            SddTaskProcessAuditLog.workspace_id == workspace_id,
            SddTaskProcessAuditLog.task_id == task_id,
        )
        .order_by(SddTaskProcessAuditLog.created_at.desc())
    )
    items, total = _paginated(query, page, page_size)
    return TaskProcessAuditSectionResponse(
        items=[_audit_log_light(log) for log in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_task_process_audit_detail(
    db: Session,
    workspace_id: str,
    task_id: str,
    log_id: str,
) -> Optional[TaskProcessAuditLogResponse]:
    from app.domains.workspace_asset.services.workspace_task_detail_service import process_audit_response

    log = (
        db.query(SddTaskProcessAuditLog)
        .filter(
            SddTaskProcessAuditLog.id == log_id,
            SddTaskProcessAuditLog.workspace_id == workspace_id,
            SddTaskProcessAuditLog.task_id == task_id,
        )
        .first()
    )
    if not log:
        return None
    return process_audit_response(log)
