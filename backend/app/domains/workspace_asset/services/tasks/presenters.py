"""Task（作为 Workspace Asset 视角）摘要展示器。

TaskSummary 是列表、详情、轻量摘要三条查询路径共用的响应模型；
spec/plan/plan_node/AI run 的卡片摘要也集中在这里。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.task.models.task import SddPlanNode, SddTask
from app.domains.workspace_asset.models.workspace_asset import SddAiOutput
from app.domains.workspace_asset.schemas.workspace_asset import (
    AiOutputResponse,
    AiRunSummary,
    PlanNodeAssetSummary,
    TaskAssetSummary,
    TaskSummary,
)
from app.domains.workspace_asset.services.common.primitives import (
    count_rows,
    coverage_status,
    coverage_status_from_counts,
    enum_value,
    json_text,
    short_text,
)


def asset_summary(asset: SddAsset) -> TaskAssetSummary:
    return TaskAssetSummary(
        id=asset.id,
        asset_type=enum_value(asset.asset_type),
        title=asset.name,
        status="AVAILABLE",
        content_text=asset.content_text,
        content_json=asset.content_json if isinstance(asset.content_json, dict) else None,
        created_at=asset.created_at,
        updated_at=None,
    )


def plan_node_summary(node: SddPlanNode) -> PlanNodeAssetSummary:
    return PlanNodeAssetSummary(
        id=node.id,
        title=node.title,
        description=node.description,
        status=enum_value(node.status),
        order_index=node.order_index,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def ai_output_response(output: SddAiOutput) -> AiOutputResponse:
    return AiOutputResponse(
        id=output.id,
        workspace_id=output.workspace_id,
        task_id=output.task_id,
        ai_job_id=output.ai_job_id,
        output_type=enum_value(output.output_type),
        title=output.title,
        content_text=output.content_text,
        content_json=output.content_json,
        created_at=output.created_at,
    )


def ai_run_summary(job: SddAiJob) -> AiRunSummary:
    outputs = list(job.outputs or [])
    explicit_adoption_status = json_text(job.result_json, ["adoption_status", "adoptionStatus"])
    output_titles = [item.title for item in outputs if item.title]
    return AiRunSummary(
        id=job.id,
        task_id=job.task_id,
        channel=enum_value(job.channel),
        status=enum_value(job.status),
        progress=job.progress,
        message=job.message,
        input_summary=short_text(job.prompt_text)
        or json_text(job.context_json, ["input_summary", "inputSummary", "summary", "prompt"]),
        output_summary=json_text(job.result_json, ["output_summary", "outputSummary", "summary", "message"])
        or short_text(", ".join(output_titles)),
        adoption_status=explicit_adoption_status or "not_available",
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def task_summary(
    db: Session,
    task: SddTask,
    *,
    is_following: bool = False,
    counts: dict[str, int] | None = None,
) -> TaskSummary:
    """构建 TaskSummary。

    列表只传 SQL 聚合计数，避免加载作业正文和全部过程资产；详情仍可使用已加载的关联。
    """
    if counts is not None and "requirement_count" in counts:
        related_counts = counts
        coverage = coverage_status_from_counts(
            counts["requirement_count"],
            counts["confirmed_evidence_count"],
            counts["human_confirmation_count"],
        )
    else:
        evidence_items = list(task.evidence_items or [])
        related_counts = {
            "requirement_count": len(task.requirement_links or []),
            "ai_run_count": len(task.ai_jobs or []),
            "human_review_count": len(task.human_reviews or []),
            "human_delta_count": len(task.human_deltas or []),
            "evidence_count": len(evidence_items),
            "decision_count": len(task.decisions or []),
            "clarification_count": len(task.clarifications or []),
        }
        coverage = coverage_status(related_counts["requirement_count"], evidence_items)
    if counts is not None and "spec_count" in counts:
        spec_count = int(counts.get("spec_count") or 0)
        plan_asset_count = int(counts.get("plan_asset_count") or 0)
        plan_node_count = int(counts.get("plan_node_count") or 0)
    else:
        spec_count = count_rows(db, SddAsset, task.workspace_id, task_id=task.id, asset_type=AssetType.SPEC)
        plan_asset_count = count_rows(db, SddAsset, task.workspace_id, task_id=task.id, asset_type=AssetType.PLAN)
        plan_node_count = count_rows(db, SddPlanNode, task.workspace_id, task_id=task.id)
    return TaskSummary(
        id=task.id,
        execution_location=task.execution_location or "SERVER",
        workspace_id=task.workspace_id,
        creator_id=task.creator_id,
        name=task.name,
        description=task.description,
        status=enum_value(task.status),
        current_phase=task.current_phase,
        requirement_count=related_counts["requirement_count"],
        spec_count=spec_count,
        plan_count=plan_asset_count + plan_node_count,
        ai_run_count=related_counts["ai_run_count"],
        human_review_count=related_counts["human_review_count"],
        human_delta_count=related_counts["human_delta_count"],
        evidence_count=related_counts["evidence_count"],
        decision_count=related_counts["decision_count"],
        clarification_count=related_counts["clarification_count"],
        coverage_status=coverage,
        baseline_version=int(task.baseline_version or 0),
        baselined_at=task.baselined_at,
        baselined_by_id=task.baselined_by_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
        is_following=is_following,
    )
