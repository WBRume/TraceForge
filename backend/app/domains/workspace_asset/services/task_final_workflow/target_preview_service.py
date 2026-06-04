"""Read-only previews for final-workflow review targets."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session, selectinload

from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.workspace_asset.models.workspace_asset import (
    SddAiOutput,
    SddDecision,
    SddEvidence,
    SddHumanDelta,
)
from app.domains.workspace_asset.schemas.task_final_workflow import (
    FinalWorkflowReviewTarget,
    FinalWorkflowReviewTargetPreviewBlock,
    FinalWorkflowReviewTargetPreviewMetadata,
    FinalWorkflowReviewTargetPreviewResponse,
)
from app.domains.workspace_asset.services import workspace_task_detail_section
from app.domains.workspace_asset.services.task_final_workflow import workflow_state
from app.domains.workspace_asset.services.workspace_task_detail_shared import TaskDetailWriteError, enum_value


TARGET_TYPES = {"SPEC", "PLAN", "AI_CHANGE", "HUMAN_DELTA", "EVIDENCE", "DECISION", "TASK_FILE"}


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True)
    text = str(value).strip()
    return text or None


def _metadata_item(key: str, label: str, value: Any) -> Optional[FinalWorkflowReviewTargetPreviewMetadata]:
    text = _stringify(value)
    if text is None:
        return None
    return FinalWorkflowReviewTargetPreviewMetadata(key=key, label=label, value=text)


def _metadata(items: Iterable[tuple[str, str, Any]]) -> list[FinalWorkflowReviewTargetPreviewMetadata]:
    result: list[FinalWorkflowReviewTargetPreviewMetadata] = []
    for key, label, value in items:
        item = _metadata_item(key, label, value)
        if item:
            result.append(item)
    return result


def _block(
    *,
    key: str,
    title: str,
    kind: str,
    content: Optional[str] = None,
    items: Optional[list[dict[str, Any]]] = None,
    file_diffs: Optional[list[Any]] = None,
    delta_regions: Optional[list[Any]] = None,
    diff_text: Optional[str] = None,
) -> Optional[FinalWorkflowReviewTargetPreviewBlock]:
    if not content and not items and not file_diffs and not delta_regions and not diff_text:
        return None
    return FinalWorkflowReviewTargetPreviewBlock(
        key=key,
        title=title,
        kind=kind,
        content=content,
        items=items or [],
        file_diffs=file_diffs or [],
        delta_regions=delta_regions or [],
        diff_text=diff_text,
    )


def _append(blocks: list[FinalWorkflowReviewTargetPreviewBlock], block: Optional[FinalWorkflowReviewTargetPreviewBlock]) -> None:
    if block:
        blocks.append(block)


def _json_content(value: Any) -> Optional[str]:
    if not value:
        return None
    return json.dumps(value, ensure_ascii=True, indent=2, default=str)


def _target_from_task(db: Session, workspace_id: str, task_id: str, target_type: str, target_id: str) -> FinalWorkflowReviewTarget:
    task = workflow_state._load_task(db, workspace_id, task_id)
    targets = workflow_state._review_targets(task).get(target_type, [])
    for target in targets:
        if target.target_id == target_id:
            return target
    raise TaskDetailWriteError("Review target not found for this Task.", status_code=404)


def _asset_preview(
    db: Session,
    workspace_id: str,
    task_id: str,
    target: FinalWorkflowReviewTarget,
) -> FinalWorkflowReviewTargetPreviewResponse:
    asset = (
        db.query(SddAsset)
        .options(selectinload(SddAsset.active_version))
        .filter(
            SddAsset.workspace_id == workspace_id,
            SddAsset.task_id == task_id,
            SddAsset.id == target.target_id,
        )
        .first()
    )
    if not asset:
        raise TaskDetailWriteError("Review target not found for this Task.", status_code=404)

    version_text = asset.active_version.normalized_markdown if asset.active_version else None
    content = asset.content_text or version_text
    asset_type = enum_value(asset.asset_type)
    diff = (
        workspace_task_detail_section.get_task_file_diff(db, workspace_id, task_id, asset.id)
        if asset_type == AssetType.CODE_DIFF.value
        else None
    )
    blocks: list[FinalWorkflowReviewTargetPreviewBlock] = []
    _append(blocks, _block(key="content", title="Content", kind="markdown", content=content))
    _append(blocks, _block(key="metadata", title="Metadata", kind="json", content=_json_content(asset.content_json)))
    _append(blocks, _block(key="diff", title="Diff", kind="diff", diff_text=diff.diff_text if diff else None))

    return FinalWorkflowReviewTargetPreviewResponse(
        target=target,
        title=asset.name,
        status=target.status,
        subtitle=asset.source_file_name,
        source_ref=target.source_ref,
        metadata=_metadata(
            [
                ("target_type", "Target type", target.target_type),
                ("asset_type", "Asset type", asset_type),
                ("source_file", "Source file", asset.source_file_name),
                ("active_version", "Active version", asset.active_version_id),
                ("created_at", "Created at", asset.created_at),
            ]
        ),
        blocks=blocks,
    )


def _ai_change_preview(
    db: Session,
    workspace_id: str,
    task_id: str,
    target: FinalWorkflowReviewTarget,
) -> FinalWorkflowReviewTargetPreviewResponse:
    output = (
        db.query(SddAiOutput)
        .filter(
            SddAiOutput.workspace_id == workspace_id,
            SddAiOutput.task_id == task_id,
            SddAiOutput.id == target.target_id,
        )
        .first()
    )
    if not output:
        raise TaskDetailWriteError("Review target not found for this Task.", status_code=404)

    blocks: list[FinalWorkflowReviewTargetPreviewBlock] = []
    _append(blocks, _block(key="content", title="Content", kind="markdown", content=output.content_text))
    _append(blocks, _block(key="metadata", title="Metadata", kind="json", content=_json_content(output.content_json)))

    return FinalWorkflowReviewTargetPreviewResponse(
        target=target,
        title=output.title or target.label,
        status=enum_value(output.output_type),
        subtitle=output.ai_job_id,
        source_ref=target.source_ref,
        metadata=_metadata(
            [
                ("target_type", "Target type", target.target_type),
                ("output_type", "Output type", enum_value(output.output_type)),
                ("ai_job", "AI job", output.ai_job_id),
                ("asset_version", "Asset version", output.asset_version_id),
                ("created_at", "Created at", output.created_at),
            ]
        ),
        blocks=blocks,
    )


def _human_delta_preview(
    db: Session,
    workspace_id: str,
    task_id: str,
    target: FinalWorkflowReviewTarget,
) -> FinalWorkflowReviewTargetPreviewResponse:
    delta = (
        db.query(SddHumanDelta)
        .filter(
            SddHumanDelta.workspace_id == workspace_id,
            SddHumanDelta.task_id == task_id,
            SddHumanDelta.id == target.target_id,
        )
        .first()
    )
    if not delta:
        raise TaskDetailWriteError("Review target not found for this Task.", status_code=404)

    detail = workspace_task_detail_section.get_task_human_delta_detail(db, workspace_id, task_id, target.target_id)
    workbench = workspace_task_detail_section.get_task_delta_workbench(db, workspace_id, task_id, target.target_id)
    blocks: list[FinalWorkflowReviewTargetPreviewBlock] = []
    _append(blocks, _block(key="summary", title="Summary", kind="text", content=delta.comparison_summary))
    _append(
        blocks,
        _block(
            key="file_diffs",
            title="Changed files",
            kind="file_diffs",
            file_diffs=workbench.file_diffs if workbench else (detail.file_diffs if detail else []),
            delta_regions=workbench.delta_regions if workbench else [],
            diff_text=detail.diff_text if detail else None,
        ),
    )

    return FinalWorkflowReviewTargetPreviewResponse(
        target=target,
        title=delta.change_category or target.label,
        status=enum_value(delta.status),
        subtitle=f"{delta.changed_files_count or 0} file(s)",
        source_ref=target.source_ref,
        metadata=_metadata(
            [
                ("target_type", "Target type", target.target_type),
                ("status", "Status", enum_value(delta.status)),
                ("changed_files", "Changed files", delta.changed_files_count),
                ("insertions", "Insertions", delta.insertions),
                ("deletions", "Deletions", delta.deletions),
                ("proposal", "Proposal", delta.proposal_id),
                ("final_evidence", "Final evidence", delta.final_evidence_id),
                ("created_at", "Created at", delta.created_at),
                ("updated_at", "Updated at", delta.updated_at),
            ]
        ),
        blocks=blocks,
    )


def _evidence_preview(
    db: Session,
    workspace_id: str,
    task_id: str,
    target: FinalWorkflowReviewTarget,
) -> FinalWorkflowReviewTargetPreviewResponse:
    evidence = (
        db.query(SddEvidence)
        .filter(
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
            SddEvidence.id == target.target_id,
        )
        .first()
    )
    if not evidence:
        raise TaskDetailWriteError("Review target not found for this Task.", status_code=404)

    source_items = [
        {"key": "source_type", "label": "Source type", "value": enum_value(evidence.source_type)},
        {"key": "source_ref", "label": "Source ref", "value": evidence.source_ref},
        {"key": "source_uri", "label": "Source URI", "value": evidence.source_uri},
        {"key": "source_path", "label": "Source path", "value": evidence.source_path},
    ]
    blocks: list[FinalWorkflowReviewTargetPreviewBlock] = []
    _append(blocks, _block(key="summary", title="Summary", kind="text", content=evidence.summary))
    _append(blocks, _block(key="source", title="Source", kind="metadata", items=[item for item in source_items if item.get("value")]))
    _append(blocks, _block(key="metadata", title="Metadata", kind="json", content=_json_content(evidence.source_metadata_json)))

    return FinalWorkflowReviewTargetPreviewResponse(
        target=target,
        title=evidence.title or target.label,
        status=enum_value(evidence.status),
        subtitle=enum_value(evidence.evidence_type),
        source_ref=target.source_ref,
        metadata=_metadata(
            [
                ("target_type", "Target type", target.target_type),
                ("status", "Status", enum_value(evidence.status)),
                ("evidence_type", "Evidence type", enum_value(evidence.evidence_type)),
                ("source_type", "Source type", enum_value(evidence.source_type)),
                ("confirmed_at", "Confirmed at", evidence.confirmed_at),
                ("created_at", "Created at", evidence.created_at),
            ]
        ),
        blocks=blocks,
    )


def _decision_preview(
    db: Session,
    workspace_id: str,
    task_id: str,
    target: FinalWorkflowReviewTarget,
) -> FinalWorkflowReviewTargetPreviewResponse:
    decision = (
        db.query(SddDecision)
        .filter(
            SddDecision.workspace_id == workspace_id,
            SddDecision.task_id == task_id,
            SddDecision.id == target.target_id,
        )
        .first()
    )
    if not decision:
        raise TaskDetailWriteError("Review target not found for this Task.", status_code=404)

    blocks: list[FinalWorkflowReviewTargetPreviewBlock] = []
    _append(blocks, _block(key="body", title="Decision", kind="text", content=decision.body))
    _append(blocks, _block(key="rationale", title="Rationale", kind="text", content=decision.rationale))
    _append(blocks, _block(key="line_refs", title="Line references", kind="json", content=_json_content(decision.delta_line_refs_json)))
    _append(blocks, _block(key="metadata", title="Metadata", kind="json", content=_json_content(decision.source_metadata_json)))

    return FinalWorkflowReviewTargetPreviewResponse(
        target=target,
        title=decision.title,
        status=enum_value(decision.status),
        subtitle=decision.impact_scope,
        source_ref=target.source_ref,
        metadata=_metadata(
            [
                ("target_type", "Target type", target.target_type),
                ("status", "Status", enum_value(decision.status)),
                ("source_type", "Source type", enum_value(decision.source_type)),
                ("impact_scope", "Impact scope", decision.impact_scope),
                ("human_delta", "Human delta", decision.human_delta_id),
                ("source_evidence", "Source evidence", decision.source_evidence_id),
                ("created_at", "Created at", decision.created_at),
                ("updated_at", "Updated at", decision.updated_at),
            ]
        ),
        blocks=blocks,
    )


def get_review_target_preview(
    db: Session,
    workspace_id: str,
    task_id: str,
    target_type: str,
    target_id: str,
) -> FinalWorkflowReviewTargetPreviewResponse:
    normalized_type = str(target_type or "").upper()
    if normalized_type not in TARGET_TYPES:
        raise TaskDetailWriteError("Unsupported review target type.", status_code=422)

    target = _target_from_task(db, workspace_id, task_id, normalized_type, target_id)
    if normalized_type in {AssetType.SPEC.value, AssetType.PLAN.value, "TASK_FILE"}:
        return _asset_preview(db, workspace_id, task_id, target)
    if normalized_type == "AI_CHANGE":
        return _ai_change_preview(db, workspace_id, task_id, target)
    if normalized_type == "HUMAN_DELTA":
        return _human_delta_preview(db, workspace_id, task_id, target)
    if normalized_type == "EVIDENCE":
        return _evidence_preview(db, workspace_id, task_id, target)
    if normalized_type == "DECISION":
        return _decision_preview(db, workspace_id, task_id, target)
    raise TaskDetailWriteError("Unsupported review target type.", status_code=422)
