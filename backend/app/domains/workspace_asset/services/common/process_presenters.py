"""过程资产（Evidence / Review / Delta / Decision / Clarification / Final
Summary / Process Audit / Task 文件项）的统一响应构建器。

读侧（Task Detail、分节查询、Requirement 关联任务、追溯视图）与写侧
（创建/更新后回显）共用本模块，任何子域不得各自复制展示逻辑。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.domains.asset.services import decision_service
from app.domains.asset.models.asset import SddAsset
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
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddHumanReviewComment,
    SddTaskFinalSummary,
    SddTaskProcessAuditLog,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    ClarificationResponse,
    DecisionResponse,
    EvidenceResponse,
    ExternalEvidenceRef,
    HumanDeltaFileDiff,
    HumanDeltaResponse,
    HumanReviewCommentResponse,
    HumanReviewResponse,
    TaskFileItemResponse,
    TaskFinalSummaryResponse,
    TaskProcessAuditLogResponse,
)
from app.domains.workspace_asset.services.common.primitives import (
    enum_value,
    normalize_list,
    short_text,
)


def external_evidence_ref(evidence: SddEvidence) -> ExternalEvidenceRef:
    return ExternalEvidenceRef(
        source_type=enum_value(evidence.source_type),
        source_uri=evidence.source_uri,
        source_label=evidence.source_label,
        source_ref=evidence.source_ref,
        source_path=evidence.source_path,
        source_metadata=evidence.source_metadata_json,
    )


def evidence_response(evidence: SddEvidence) -> EvidenceResponse:
    return EvidenceResponse(
        id=evidence.id,
        workspace_id=evidence.workspace_id,
        requirement_id=evidence.requirement_id,
        task_id=evidence.task_id,
        ai_job_id=evidence.ai_job_id,
        human_review_id=evidence.human_review_id,
        status=enum_value(evidence.status),
        evidence_type=enum_value(evidence.evidence_type),
        source=external_evidence_ref(evidence),
        title=evidence.title,
        summary=evidence.summary,
        confirmed_by_id=evidence.confirmed_by_id,
        confirmed_at=evidence.confirmed_at,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
    )


def human_review_comment_response(comment: SddHumanReviewComment) -> HumanReviewCommentResponse:
    return HumanReviewCommentResponse(
        id=comment.id,
        workspace_id=comment.workspace_id,
        task_id=comment.task_id,
        review_id=comment.review_id,
        author_id=comment.author_id,
        comment_type=comment.comment_type,
        body=comment.body,
        required_change=comment.required_change_json if isinstance(comment.required_change_json, dict) else None,
        created_at=comment.created_at,
    )


def _review_target_refs(review: SddHumanReview) -> List[Dict[str, Any]]:
    target_ref = review.target_ref_json
    if isinstance(target_ref, dict) and isinstance(target_ref.get("targets"), list):
        return [item for item in target_ref["targets"] if isinstance(item, dict)]
    return []


def human_review_response(review: SddHumanReview) -> HumanReviewResponse:
    return HumanReviewResponse(
        id=review.id,
        workspace_id=review.workspace_id,
        task_id=review.task_id,
        reviewer_id=review.reviewer_id,
        status=enum_value(review.status),
        outcome=enum_value(review.outcome) if review.outcome else None,
        review_type=review.review_type,
        review_scope=review.review_scope,
        priority=review.priority,
        title=review.title,
        body=review.body,
        source_ref=review.source_ref_json,
        target_ref=review.target_ref_json,
        target_refs=_review_target_refs(review),
        derived_status=getattr(review, "_derived_status", None),
        due_date=review.due_date,
        resolved_at=review.resolved_at,
        linked_clarification_ids=[
            item.clarification_id for item in (review.clarification_links or [])
        ],
        comments=[human_review_comment_response(item) for item in (review.comments or [])],
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def human_delta_response(
    delta: SddHumanDelta,
    *,
    diff_text: Optional[str] = None,
    file_diffs: Optional[List[Dict[str, Any]]] = None,
) -> HumanDeltaResponse:
    from app.domains.workspace_asset.services.human_delta_compare_service import (
        _proposal_summary,
        _evidence_summary,
    )

    proposal_summary = None
    if delta.proposal:
        proposal_summary = _proposal_summary(delta.proposal)

    evidence_summary = None
    if delta.final_evidence:
        evidence_summary = _evidence_summary(delta.final_evidence)

    decision_count = len(delta.decisions or [])

    parsed_file_diffs = [HumanDeltaFileDiff(**fd) for fd in file_diffs] if file_diffs else []

    return HumanDeltaResponse(
        id=delta.id,
        workspace_id=delta.workspace_id,
        task_id=delta.task_id,
        proposal_id=delta.proposal_id,
        final_evidence_id=delta.final_evidence_id,
        status=enum_value(delta.status),
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
        diff_text=diff_text,
        file_diffs=parsed_file_diffs,
        decision_count=decision_count,
        created_at=delta.created_at,
        updated_at=delta.updated_at,
    )


def decision_response(decision: SddDecision) -> DecisionResponse:
    return DecisionResponse(
        id=decision.id,
        workspace_id=decision.workspace_id,
        task_id=decision.task_id,
        requirement_id=decision.requirement_id,
        human_delta_id=decision.human_delta_id,
        delta_region_id=decision.delta_region_id,
        status=enum_value(decision.status),
        title=decision.title,
        body=decision.body,
        rationale=decision.rationale,
        impact_scope=decision.impact_scope,
        source_evidence_id=decision.source_evidence_id,
        source_type=enum_value(decision.source_type),
        source_chat_message_id=decision.source_chat_message_id,
        source_asset_id=decision.source_asset_id,
        source_asset_version_id=decision.source_asset_version_id,
        source_asset_thread_id=decision.source_asset_thread_id,
        source_resolution_proposal_id=decision.source_resolution_proposal_id,
        source_final_summary_id=decision.source_final_summary_id,
        source_metadata=decision.source_metadata_json if isinstance(decision.source_metadata_json, dict) else None,
        source=decision_service.decision_source_response(decision),
        decided_by_id=decision.decided_by_id,
        promote_candidate=bool(decision.promote_candidate),
        created_at=decision.created_at,
        updated_at=decision.updated_at,
    )


def clarification_response(clarification: SddClarification) -> ClarificationResponse:
    return ClarificationResponse(
        id=clarification.id,
        workspace_id=clarification.workspace_id,
        task_id=clarification.task_id,
        requirement_id=clarification.requirement_id,
        status=enum_value(clarification.status),
        blocking_level=enum_value(clarification.blocking_level),
        question=clarification.question,
        answer=clarification.answer,
        requester_id=clarification.requester_id,
        responder_id=clarification.responder_id,
        source_evidence_id=clarification.source_evidence_id,
        source_review_id=clarification.source_review_id,
        clarification_type=clarification.clarification_type,
        target_ref=clarification.target_ref_json if isinstance(clarification.target_ref_json, dict) else None,
        urgency=clarification.urgency,
        answered_at=clarification.answered_at,
        accepted_at=clarification.accepted_at,
        promote_candidate=bool(clarification.promote_candidate),
        converted_requirement_id=clarification.converted_requirement_id,
        created_at=clarification.created_at,
        updated_at=clarification.updated_at,
    )


def final_summary_response(summary: SddTaskFinalSummary) -> TaskFinalSummaryResponse:
    return TaskFinalSummaryResponse(
        id=summary.id,
        workspace_id=summary.workspace_id,
        task_id=summary.task_id,
        author_id=summary.author_id,
        final_status=enum_value(summary.final_status),
        summary=summary.summary,
        remaining_risk=summary.remaining_risk,
        next_steps=summary.next_steps,
        final_evidence_ids=normalize_list(summary.final_evidence_ids_json),
        review_checklist=summary.review_checklist_json if isinstance(summary.review_checklist_json, dict) else None,
        clarification_summary=summary.clarification_summary_json if isinstance(summary.clarification_summary_json, dict) else None,
        delta_summary=summary.delta_summary_json if isinstance(summary.delta_summary_json, dict) else None,
        decision_summary=summary.decision_summary_json if isinstance(summary.decision_summary_json, dict) else None,
        human_confirmation_review_id=summary.human_confirmation_review_id,
        verified_at=summary.verified_at,
        verified_by_id=summary.verified_by_id,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def process_audit_response(log: SddTaskProcessAuditLog) -> TaskProcessAuditLogResponse:
    return TaskProcessAuditLogResponse(
        id=log.id,
        workspace_id=log.workspace_id,
        task_id=log.task_id,
        actor_id=log.actor_id,
        record_type=enum_value(log.record_type),
        record_id=log.record_id,
        action=enum_value(log.action),
        before=log.before_json if isinstance(log.before_json, dict) else None,
        after=log.after_json if isinstance(log.after_json, dict) else None,
        reason=log.reason,
        created_at=log.created_at,
    )


# ---------------------------------------------------------------------------
# Task 文件项（Spec / Plan / AI Output / Change Proposal / Verification / Conflict）
# ---------------------------------------------------------------------------


def task_file_items(
    *,
    specs: List[SddAsset],
    plans: List[SddAsset],
    ai_outputs: List[SddAiOutput],
    change_proposals: List[SddTaskChangeProposal],
    verification_runs: List[SddTaskVerificationRun],
    conflict_reports: List[SddTaskConflictReport],
) -> List[TaskFileItemResponse]:
    items: List[TaskFileItemResponse] = []
    items.extend(task_file_from_asset(asset) for asset in [*specs, *plans])
    items.extend(task_file_from_ai_output(output) for output in ai_outputs)
    for proposal in change_proposals:
        items.append(task_file_from_change_proposal(proposal))
        items.extend(task_file_from_change_file(file_item) for file_item in (proposal.files or []))
    items.extend(task_file_from_verification(run) for run in verification_runs)
    items.extend(task_file_from_conflict(report) for report in conflict_reports)
    return sorted(items, key=lambda item: item.created_at or datetime.min, reverse=True)


def task_file_from_asset(asset: SddAsset) -> TaskFileItemResponse:
    return TaskFileItemResponse(
        id=asset.id,
        file_type=enum_value(asset.asset_type),
        title=asset.name,
        status="AVAILABLE",
        source_kind="asset",
        source_id=asset.id,
        source_version_id=asset.active_version_id,
        source_path=asset.source_file_name,
        summary=short_text(asset.content_text, limit=500),
        metadata=asset.content_json if isinstance(asset.content_json, dict) else None,
        created_at=asset.created_at,
    )


def task_file_from_ai_output(output: SddAiOutput) -> TaskFileItemResponse:
    return TaskFileItemResponse(
        id=output.id,
        file_type=f"AI_OUTPUT:{enum_value(output.output_type)}",
        title=output.title or f"AI Output {output.id}",
        status="AVAILABLE",
        source_kind="ai_output",
        source_id=output.ai_job_id,
        source_version_id=output.asset_version_id,
        summary=short_text(output.content_text, limit=500),
        metadata=output.content_json if isinstance(output.content_json, dict) else None,
        created_at=output.created_at,
    )


def task_file_from_change_proposal(proposal: SddTaskChangeProposal) -> TaskFileItemResponse:
    return TaskFileItemResponse(
        id=proposal.id,
        file_type="GIT_PATCH",
        title=f"Change Proposal #{proposal.proposal_no} Patch Set {proposal.patch_set_no}",
        status=enum_value(proposal.status),
        source_kind="change_proposal",
        source_id=proposal.id,
        source_version_id=proposal.patch_asset_version_id,
        summary=proposal.summary,
        metadata={
            "patch_asset_id": proposal.patch_asset_id,
            "changed_files_count": proposal.changed_files_count,
            "insertions": proposal.insertions,
            "deletions": proposal.deletions,
            "base_branch": proposal.base_branch,
            "base_commit_sha": proposal.base_commit_sha,
            "cloud_task_branch": proposal.cloud_task_branch,
            "cloud_head_sha": proposal.cloud_head_sha,
        },
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def task_file_from_change_file(file_item: SddTaskChangeProposalFile) -> TaskFileItemResponse:
    return TaskFileItemResponse(
        id=file_item.id,
        file_type="GIT_PATCH_FILE",
        title=file_item.file_path,
        status=enum_value(file_item.change_type),
        source_kind="change_proposal_file",
        source_id=file_item.proposal_id,
        source_path=file_item.file_path,
        summary=short_text(file_item.diff_excerpt, limit=500),
        metadata={
            "old_path": file_item.old_path,
            "new_path": file_item.new_path,
            "insertions": file_item.insertions,
            "deletions": file_item.deletions,
            "is_binary": file_item.is_binary,
        },
        created_at=file_item.created_at,
    )


def task_file_from_verification(run: SddTaskVerificationRun) -> TaskFileItemResponse:
    return TaskFileItemResponse(
        id=run.id,
        file_type="VERIFICATION_LOG",
        title=run.command or f"Verification Run {run.id}",
        status=enum_value(run.status),
        source_kind="verification_run",
        source_id=run.proposal_id,
        source_version_id=run.log_asset_version_id,
        summary=short_text(run.log_excerpt, limit=500),
        metadata={
            "log_asset_id": run.log_asset_id,
            "duration_ms": run.duration_ms,
            "base_commit_sha": run.base_commit_sha,
            "local_head_sha": run.local_head_sha,
            "agent_id": run.agent_id,
        },
        created_at=run.created_at,
    )


def task_file_from_conflict(report: SddTaskConflictReport) -> TaskFileItemResponse:
    return TaskFileItemResponse(
        id=report.id,
        file_type="CONFLICT_REPORT",
        title=f"Conflict Report {report.id}",
        status="CONFLICT",
        source_kind="conflict_report",
        source_id=report.proposal_id,
        source_version_id=report.report_asset_version_id,
        summary=short_text(report.conflict_excerpt or report.git_apply_stderr, limit=500),
        metadata={
            "report_asset_id": report.report_asset_id,
            "base_commit_sha": report.base_commit_sha,
            "local_head_sha": report.local_head_sha,
            "conflicted_files": report.conflicted_files_json,
            "agent_id": report.agent_id,
        },
        created_at=report.created_at,
    )


__all__ = [
    "clarification_response",
    "decision_response",
    "evidence_response",
    "external_evidence_ref",
    "final_summary_response",
    "human_delta_response",
    "human_review_comment_response",
    "human_review_response",
    "process_audit_response",
    "task_file_from_ai_output",
    "task_file_from_asset",
    "task_file_from_change_file",
    "task_file_from_change_proposal",
    "task_file_from_conflict",
    "task_file_from_verification",
    "task_file_items",
]
