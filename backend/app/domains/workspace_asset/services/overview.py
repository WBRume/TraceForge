"""工作区资产总览与知识资产列表。"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.task.models.task import SddTask
from app.domains.workspace_asset.models.workspace_asset import (
    SddEvidence,
    SddKnowledgeAsset,
    SddRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    KnowledgeAssetResponse,
    WorkspaceAssetsKnowledgeResponse,
    WorkspaceAssetsOverviewResponse,
)
from app.domains.workspace_asset.services.common.primitives import (
    collection_state,
    count_rows,
    enum_value,
    make_connection,
)


def _overview_connection_status(
    *,
    requirement_count: int,
    task_count: int,
    ai_run_count: int,
    evidence_count: int,
) -> List:
    return [
        make_connection(
            "requirement_source",
            "Requirement source",
            "AVAILABLE" if requirement_count else "NOT_CONNECTED",
            "Requirement Repository has real records." if requirement_count else "Waiting for requirement source connection.",
        ),
        make_connection(
            "task_records",
            "Task records",
            "AVAILABLE" if task_count else "EMPTY",
            "Real Task records are available." if task_count else "No real task process records yet.",
        ),
        make_connection(
            "ai_runs",
            "AI Run records",
            "AVAILABLE" if ai_run_count else "EMPTY",
            "AI Run records are available." if ai_run_count else "No AI Run records are connected for assets yet.",
        ),
        make_connection(
            "evidence_source",
            "Evidence source",
            "AVAILABLE" if evidence_count else "NOT_CONNECTED",
            "Evidence references are available." if evidence_count else "Waiting for real external evidence or human confirmation.",
        ),
        make_connection(
            "coverage_verification",
            "Coverage verification",
            "EMPTY",
            "Verified coverage requires real Evidence and human confirmation.",
        ),
    ]


def get_overview(db: Session, workspace_id: str) -> WorkspaceAssetsOverviewResponse:
    requirement_count = count_rows(db, SddRequirement, workspace_id)
    task_count = count_rows(db, SddTask, workspace_id)
    ai_run_count = count_rows(db, SddAiJob, workspace_id)
    evidence_count = count_rows(db, SddEvidence, workspace_id)
    knowledge_asset_count = count_rows(db, SddKnowledgeAsset, workspace_id)
    return WorkspaceAssetsOverviewResponse(
        workspace_id=workspace_id,
        requirement_count=requirement_count,
        task_count=task_count,
        ai_run_count=ai_run_count,
        evidence_count=evidence_count,
        knowledge_asset_count=knowledge_asset_count,
        coverage_status="not_available",
        connection_status=_overview_connection_status(
            requirement_count=requirement_count,
            task_count=task_count,
            ai_run_count=ai_run_count,
            evidence_count=evidence_count,
        ),
    )


def _knowledge_asset_response(asset: SddKnowledgeAsset) -> KnowledgeAssetResponse:
    return KnowledgeAssetResponse(
        id=asset.id,
        workspace_id=asset.workspace_id,
        asset_type=enum_value(asset.asset_type),
        status=enum_value(asset.status),
        title=asset.title,
        body=asset.body,
        source_task_id=asset.source_task_id,
        source_decision_id=asset.source_decision_id,
        source_human_delta_id=asset.source_human_delta_id,
        source_clarification_id=asset.source_clarification_id,
        source_review_id=asset.source_review_id,
        source_evidence_id=asset.source_evidence_id,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def list_knowledge_assets(db: Session, workspace_id: str) -> WorkspaceAssetsKnowledgeResponse:
    assets = (
        db.query(SddKnowledgeAsset)
        .filter(SddKnowledgeAsset.workspace_id == workspace_id)
        .order_by(SddKnowledgeAsset.created_at.desc())
        .all()
    )
    total = len(assets)
    return WorkspaceAssetsKnowledgeResponse(
        workspace_id=workspace_id,
        items=[_knowledge_asset_response(item) for item in assets],
        total=total,
        state=collection_state(total, "No promoted Knowledge Asset records are available yet."),
        connection_status=[
            make_connection(
                "knowledge_assets",
                "Knowledge assets",
                "AVAILABLE" if total else "EMPTY",
                "Promoted Knowledge Asset records are available."
                if total
                else "Waiting for promotion from real task process records.",
            )
        ],
    )
