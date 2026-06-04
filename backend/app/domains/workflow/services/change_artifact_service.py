"""
Asset-backed storage helpers for change proposals and local verification artifacts.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.domains.asset.models.asset import AssetType, SddAsset, SddAssetVersion
from app.domains.task.models.task import SddTask
from app.domains.asset.services import asset_document_service


def _decode_excerpt(raw: bytes, *, limit: int = 12000) -> str:
    data = raw or b""
    if not data:
        return ""
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except Exception:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    max_chars = max(1000, int(limit or 12000))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<artifact excerpt truncated>..."


def create_patch_asset(
    db: Session,
    task: SddTask,
    *,
    creator_id: str,
    proposal_no: int,
    patch_set_no: int,
    patch_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[SddAsset, SddAssetVersion]:
    file_name = f"change-proposal-{proposal_no}-patch-set-{patch_set_no}.patch"
    raw = str(patch_text or "").encode("utf-8")
    return asset_document_service.create_task_asset_version_from_bytes(
        db,
        task,
        creator_id=creator_id,
        asset_type=AssetType.CODE_DIFF,
        asset_name=f"Change Proposal #{proposal_no} Patch Set {patch_set_no}",
        file_name=file_name,
        file_content=raw,
        content_text=_decode_excerpt(raw, limit=settings.TASK_CHANGE_DIFF_EXCERPT_CHARS),
        content_json={
            "artifact_kind": "change_proposal_patch",
            "proposal_no": proposal_no,
            "patch_set_no": patch_set_no,
            **(metadata or {}),
        },
        change_note="Generated change proposal patch",
        source_ext=".patch",
        source_mime="text/x-patch",
    )


def create_verification_log_asset(
    db: Session,
    task: SddTask,
    *,
    creator_id: str,
    run_id: str,
    file_name: str,
    file_content: bytes,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[SddAsset, SddAssetVersion, str]:
    excerpt = _decode_excerpt(file_content)
    safe_name = file_name or f"verification-run-{run_id}.log"
    asset, version = asset_document_service.create_task_asset_version_from_bytes(
        db,
        task,
        creator_id=creator_id,
        asset_type=AssetType.UT_REPORT,
        asset_name=f"Verification Run {run_id} Log",
        file_name=safe_name,
        file_content=file_content,
        content_text=excerpt,
        content_json={
            "artifact_kind": "verification_log",
            "verification_run_id": run_id,
            "size_bytes": len(file_content or b""),
            **(metadata or {}),
        },
        change_note="Uploaded local verification log",
        source_ext=".log",
        source_mime="text/plain",
    )
    return asset, version, excerpt


def create_conflict_report_asset(
    db: Session,
    task: SddTask,
    *,
    creator_id: str,
    report_id: str,
    file_name: str,
    file_content: bytes,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[SddAsset, SddAssetVersion, str]:
    excerpt = _decode_excerpt(file_content)
    safe_name = file_name or f"conflict-report-{report_id}.log"
    asset, version = asset_document_service.create_task_asset_version_from_bytes(
        db,
        task,
        creator_id=creator_id,
        asset_type=AssetType.ERROR_STACK,
        asset_name=f"Conflict Report {report_id}",
        file_name=safe_name,
        file_content=file_content,
        content_text=excerpt,
        content_json={
            "artifact_kind": "conflict_report",
            "conflict_report_id": report_id,
            "size_bytes": len(file_content or b""),
            **(metadata or {}),
        },
        change_note="Uploaded local patch apply conflict report",
        source_ext=".log",
        source_mime="text/plain",
    )
    return asset, version, excerpt
