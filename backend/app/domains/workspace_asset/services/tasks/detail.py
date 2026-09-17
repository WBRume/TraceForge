"""Task Detail 全量聚合读。

一次加载 Task 全部过程资产关联并组装 TaskDetailResponse；分节轻量读取
在 ``tasks.sections``，写侧在 ``task_process``。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session, selectinload

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.task.models.task import SddPlanNode, SddTask
from app.domains.workflow.models.task_change import SddTaskChangeProposal
from app.domains.workspace_asset.models.workspace_asset import (
    SddHumanDelta,
    SddHumanReview,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    TaskDetailResponse,
    TaskProcessSummary,
)
from app.domains.workspace_asset.services.common.process_presenters import (
    clarification_response,
    decision_response,
    evidence_response,
    final_summary_response,
    human_delta_response,
    human_review_response,
    process_audit_response,
    task_file_items,
)
from app.domains.workspace_asset.services.common.primitives import make_connection
from app.domains.workspace_asset.services.requirements.presenters import task_requirement_link
from app.domains.workspace_asset.services.tasks.presenters import (
    ai_output_response,
    ai_run_summary,
    asset_summary,
    plan_node_summary,
    task_summary,
)


def get_task_detail(db: Session, workspace_id: str, task_id: str) -> Optional[TaskDetailResponse]:
    task = (
        db.query(SddTask)
        .options(
            selectinload(SddTask.requirement_links).selectinload(SddTaskRequirement.requirement),
            selectinload(SddTask.ai_jobs).selectinload(SddAiJob.outputs),
            selectinload(SddTask.ai_outputs),
            selectinload(SddTask.human_reviews).selectinload(SddHumanReview.comments),
            selectinload(SddTask.human_deltas).selectinload(SddHumanDelta.decisions),
            selectinload(SddTask.evidence_items),
            selectinload(SddTask.decisions),
            selectinload(SddTask.clarifications),
            selectinload(SddTask.final_summary),
            selectinload(SddTask.process_audit_logs),
            selectinload(SddTask.change_proposals).selectinload(SddTaskChangeProposal.files),
            selectinload(SddTask.verification_runs),
            selectinload(SddTask.conflict_reports),
        )
        .filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id)
        .first()
    )
    if not task:
        return None

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
    plan_nodes = (
        db.query(SddPlanNode)
        .filter(SddPlanNode.workspace_id == workspace_id, SddPlanNode.task_id == task_id)
        .order_by(SddPlanNode.order_index.asc(), SddPlanNode.created_at.asc())
        .all()
    )

    ai_runs = sorted(task.ai_jobs or [], key=lambda item: item.created_at, reverse=True)
    ai_outputs = sorted(task.ai_outputs or [], key=lambda item: item.created_at, reverse=True)
    reviews = sorted(task.human_reviews or [], key=lambda item: item.created_at, reverse=True)
    deltas = sorted(task.human_deltas or [], key=lambda item: item.created_at, reverse=True)
    evidence = sorted(task.evidence_items or [], key=lambda item: item.created_at, reverse=True)
    decisions = sorted(task.decisions or [], key=lambda item: item.created_at, reverse=True)
    clarifications = sorted(task.clarifications or [], key=lambda item: item.created_at, reverse=True)
    requirement_links = sorted(task.requirement_links or [], key=lambda item: item.created_at, reverse=True)
    change_proposals = sorted(task.change_proposals or [], key=lambda item: item.created_at, reverse=True)
    verification_runs = sorted(task.verification_runs or [], key=lambda item: item.created_at, reverse=True)
    conflict_reports = sorted(task.conflict_reports or [], key=lambda item: item.created_at, reverse=True)

    summary = task_summary(db, task)
    process_summary = TaskProcessSummary(
        spec_status="available" if specs else "empty",
        plan_status="available" if plans or plan_nodes else "empty",
        ai_run_status="available" if ai_runs else "empty",
        human_review_status="available" if reviews else "empty",
        human_delta_status="available" if deltas else "empty",
        evidence_status="available" if evidence else "empty",
        coverage_status=summary.coverage_status,
        risk_status="not_available",
    )

    return TaskDetailResponse(
        task=summary,
        requirement_links=[task_requirement_link(item) for item in requirement_links],
        task_files=task_file_items(
            specs=specs,
            plans=plans,
            ai_outputs=ai_outputs,
            change_proposals=change_proposals,
            verification_runs=verification_runs,
            conflict_reports=conflict_reports,
        ),
        specs=[asset_summary(item) for item in specs],
        plans=[asset_summary(item) for item in plans],
        plan_nodes=[plan_node_summary(item) for item in plan_nodes],
        ai_runs=[ai_run_summary(item) for item in ai_runs],
        ai_outputs=[ai_output_response(item) for item in ai_outputs],
        human_reviews=[human_review_response(item) for item in reviews],
        human_deltas=[human_delta_response(item) for item in deltas],
        evidence=[evidence_response(item) for item in evidence],
        decisions=[decision_response(item) for item in decisions],
        clarifications=[clarification_response(item) for item in clarifications],
        final_summary=final_summary_response(task.final_summary) if task.final_summary else None,
        process_audit_logs=[process_audit_response(item) for item in (task.process_audit_logs or [])],
        process_summary=process_summary,
        connection_status=[
            make_connection(
                "task_process_assets",
                "Task process assets",
                "AVAILABLE" if any([specs, plans, plan_nodes, ai_runs, reviews, deltas, evidence]) else "EMPTY",
                "Real process records are available."
                if any([specs, plans, plan_nodes, ai_runs, reviews, deltas, evidence])
                else "No process assets are connected for this task yet.",
            ),
            make_connection(
                "coverage_verification",
                "Coverage verification",
                "AVAILABLE" if summary.coverage_status == "verified" else "EMPTY",
                "Verified coverage is backed by confirmed Evidence and human confirmation."
                if summary.coverage_status == "verified"
                else "Coverage cannot be verified without real Evidence and human confirmation.",
            ),
        ],
    )
