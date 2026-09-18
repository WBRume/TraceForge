"""资产文档版本生命周期：版本创建、激活与历史数据兜底。

四个业务入口共享「写原文件 → 建版本记录 → 激活」核心流程：
- create_asset_version_from_upload          SPEC 文档上传（任务级唯一）
- create_diagnosis_doc_asset_version        诊断辅助文档上传（任务+文件名唯一）
- create_asset_version_from_normalized_content
- create_task_asset_version_from_bytes      产物类资产（diff/报告等）
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.domains.asset.models.asset import AssetType, SddAsset, SddAssetVersion
from app.domains.asset.services import asset_service
from app.domains.asset.services.document import markdown_blocks, repository, storage
from app.domains.asset.services.document.docx import DOCX_MIME, build_docx_bytes, looks_like_docx_bytes
from app.domains.asset.services.document.payload import guess_ext_and_mime, parse_document_payload
from app.domains.task.models.task import SddTask


def _create_version(
    db: Session,
    asset: SddAsset,
    *,
    version_no: int,
    base_version_id: Optional[str],
    original_path: Optional[str],
    original_ext: Optional[str],
    original_mime: Optional[str],
    normalized_markdown: Optional[str],
    blocks_json: Optional[List[Dict[str, Any]]],
    render_json: Optional[Dict[str, Any]],
    change_note: Optional[str],
    creator_id: str,
) -> SddAssetVersion:
    version = SddAssetVersion(
        asset_id=asset.id,
        version_no=version_no,
        base_version_id=base_version_id,
        original_path=original_path,
        original_ext=original_ext,
        original_mime=original_mime,
        normalized_markdown=normalized_markdown,
        blocks_json=blocks_json,
        render_json=render_json,
        change_note=change_note,
        created_by=creator_id,
    )
    db.add(version)
    db.flush()
    return version


def _activate_version(
    asset: SddAsset,
    version: SddAssetVersion,
    *,
    normalized_markdown: Optional[str],
    block_count: int,
    source_file_name: Optional[str] = None,
    source_ext: Optional[str] = None,
    source_mime: Optional[str] = None,
) -> None:
    """激活版本：同步资产上的内容快照与来源元数据。"""
    asset.active_version_id = version.id
    asset.content_text = normalized_markdown
    asset.content_json = {
        "active_version_no": version.version_no,
        "block_count": block_count,
    }
    if source_file_name is not None:
        asset.source_file_name = source_file_name
    if source_ext is not None:
        asset.source_ext = source_ext
    if source_mime is not None:
        asset.source_mime = source_mime


def _upsert_spec_asset(
    db: Session,
    task: SddTask,
    creator_id: str,
    file_name: str,
    payload: Dict[str, Any],
) -> SddAsset:
    asset = asset_service.get_spec_asset_by_task(db, task.id)
    if asset:
        asset.name = file_name
        asset.source_file_name = payload.get("source_file_name")
        asset.source_ext = payload.get("source_ext")
        asset.source_mime = payload.get("source_mime")
        return asset

    asset = SddAsset(
        task_id=task.id,
        workspace_id=task.workspace_id,
        creator_id=creator_id,
        asset_type=AssetType.SPEC,
        name=file_name,
        source_file_name=payload.get("source_file_name"),
        source_ext=payload.get("source_ext"),
        source_mime=payload.get("source_mime"),
    )
    db.add(asset)
    db.flush()
    return asset


def create_asset_version_from_upload(
    db: Session,
    task: SddTask,
    *,
    creator_id: str,
    file_name: str,
    file_content: bytes,
    change_note: Optional[str] = None,
) -> Tuple[SddAsset, SddAssetVersion]:
    payload = parse_document_payload(file_name, file_content)
    asset = _upsert_spec_asset(db, task, creator_id, file_name, payload)
    version_no = repository.next_version_no(db, asset.id)
    original_path = storage.write_original_file(task, asset, version_no, file_name, file_content)
    version = _create_version(
        db,
        asset,
        version_no=version_no,
        base_version_id=asset.active_version_id,
        original_path=original_path,
        original_ext=payload.get("source_ext"),
        original_mime=payload.get("source_mime"),
        normalized_markdown=payload.get("normalized_markdown"),
        blocks_json=payload.get("blocks_json"),
        render_json=payload.get("render_json"),
        change_note=change_note,
        creator_id=creator_id,
    )
    _activate_version(
        asset,
        version,
        normalized_markdown=payload.get("normalized_markdown"),
        block_count=len(payload.get("blocks_json") or []),
        source_file_name=payload.get("source_file_name"),
        source_ext=payload.get("source_ext"),
        source_mime=payload.get("source_mime"),
    )
    return asset, version


def create_diagnosis_doc_asset_version(
    db: Session,
    task: SddTask,
    *,
    creator_id: str,
    file_name: str,
    file_content: bytes,
    change_note: Optional[str] = None,
) -> Tuple[SddAsset, SddAssetVersion, str]:
    """问题定位任务：上传需求/日志等辅助文档。

    - 按「任务 + 文件名」复用同一 DIAGNOSIS_DOC 资产（重复上传生成新版本）；
    - 原始文件同时写入任务 CLI 工作区 `.sdd/diagnosis/` 目录，AI 会话可直接读取；
    - 返回 (asset, version, cli_path)。
    """
    safe_name = storage.normalize_filename(file_name)
    payload = parse_document_payload(safe_name, file_content)

    asset = asset_service.get_diagnosis_doc_asset_by_task_and_name(db, task.id, safe_name)
    if asset is None:
        asset = SddAsset(
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=creator_id,
            asset_type=AssetType.DIAGNOSIS_DOC,
            name=safe_name,
            source_file_name=payload.get("source_file_name"),
            source_ext=payload.get("source_ext"),
            source_mime=payload.get("source_mime"),
        )
        db.add(asset)
        db.flush()

    version_no = repository.next_version_no(db, asset.id)
    original_path = storage.write_original_file(task, asset, version_no, safe_name, file_content)
    version = _create_version(
        db,
        asset,
        version_no=version_no,
        base_version_id=asset.active_version_id,
        original_path=original_path,
        original_ext=payload.get("source_ext"),
        original_mime=payload.get("source_mime"),
        normalized_markdown=payload.get("normalized_markdown"),
        blocks_json=payload.get("blocks_json"),
        render_json=payload.get("render_json"),
        change_note=change_note,
        creator_id=creator_id,
    )
    _activate_version(
        asset,
        version,
        normalized_markdown=payload.get("normalized_markdown"),
        block_count=len(payload.get("blocks_json") or []),
        source_file_name=payload.get("source_file_name"),
        source_ext=payload.get("source_ext"),
        source_mime=payload.get("source_mime"),
    )
    asset.name = safe_name

    cli_path = storage.write_cli_workspace_copy(task, safe_name, file_content)
    db.flush()
    return asset, version, cli_path


def create_asset_version_from_normalized_content(
    db: Session,
    asset: SddAsset,
    *,
    creator_id: str,
    normalized_markdown: str,
    blocks_json: Optional[List[Dict[str, Any]]] = None,
    change_note: Optional[str] = None,
    base_version_id: Optional[str] = None,
    output_ext: Optional[str] = None,
    output_mime: Optional[str] = None,
    output_file_bytes: Optional[bytes] = None,
    output_file_name: Optional[str] = None,
) -> SddAssetVersion:
    task = repository.task_for_asset(db, asset)
    version_no = repository.next_version_no(db, asset.id)
    ext = (output_ext or asset.source_ext or ".md").lower()
    mime = output_mime or asset.source_mime or "text/markdown"
    effective_markdown = normalized_markdown
    blocks = blocks_json if blocks_json is not None else markdown_blocks.markdown_to_blocks(effective_markdown)
    render_json: Dict[str, Any] = {"format": "markdown", "block_count": len(blocks)}
    filename = output_file_name or (asset.source_file_name or f"spec-v{version_no}{ext}")
    file_name = storage.normalize_filename(filename, fallback_ext=ext or ".md")
    file_bytes = output_file_bytes
    if file_bytes is None:
        file_bytes = effective_markdown.encode("utf-8")

    if ext == ".docx" and not looks_like_docx_bytes(file_bytes):
        rebuilt_docx = build_docx_bytes(blocks, effective_markdown)
        if rebuilt_docx:
            file_bytes = rebuilt_docx
        mime = DOCX_MIME

    if ext == ".docx" and file_bytes:
        reparsed = parse_document_payload(file_name, file_bytes)
        reparsed_markdown = str(reparsed.get("normalized_markdown") or "")
        reparsed_blocks = list(reparsed.get("blocks_json") or [])
        reparsed_render = dict(reparsed.get("render_json") or {})
        if reparsed_blocks or reparsed_markdown:
            if reparsed_markdown:
                effective_markdown = reparsed_markdown
            if reparsed_blocks:
                blocks = reparsed_blocks
            render_json = reparsed_render or {"format": "rich_doc", "block_count": len(blocks), "docx_comments": []}

    original_path = storage.write_original_file(task, asset, version_no, file_name, file_bytes)

    version = _create_version(
        db,
        asset,
        version_no=version_no,
        base_version_id=base_version_id or asset.active_version_id,
        original_path=original_path,
        original_ext=ext,
        original_mime=mime,
        normalized_markdown=effective_markdown,
        blocks_json=blocks,
        render_json=render_json,
        change_note=change_note,
        creator_id=creator_id,
    )
    _activate_version(
        asset,
        version,
        normalized_markdown=effective_markdown,
        block_count=len(blocks),
        source_file_name=file_name,
        source_ext=ext,
        source_mime=mime,
    )
    return version


def create_task_asset_version_from_bytes(
    db: Session,
    task: SddTask,
    *,
    creator_id: str,
    asset_type: AssetType,
    asset_name: str,
    file_name: str,
    file_content: bytes,
    content_text: Optional[str] = None,
    content_json: Optional[Dict[str, Any]] = None,
    change_note: Optional[str] = None,
    source_ext: Optional[str] = None,
    source_mime: Optional[str] = None,
) -> Tuple[SddAsset, SddAssetVersion]:
    """产物类资产（diff/报告等）：不走文档解析，原样存字节。"""
    ext, guessed_mime = guess_ext_and_mime(file_name)
    effective_ext = source_ext if source_ext is not None else ext
    effective_mime = source_mime or guessed_mime
    asset = SddAsset(
        task_id=task.id,
        workspace_id=task.workspace_id,
        creator_id=creator_id,
        asset_type=asset_type,
        name=asset_name,
        content_text=content_text,
        content_json=content_json or {},
        source_file_name=file_name,
        source_ext=effective_ext,
        source_mime=effective_mime,
    )
    db.add(asset)
    db.flush()

    version_no = repository.next_version_no(db, asset.id)
    original_path = storage.write_original_file(task, asset, version_no, file_name, file_content)
    version = _create_version(
        db,
        asset,
        version_no=version_no,
        base_version_id=None,
        original_path=original_path,
        original_ext=effective_ext,
        original_mime=effective_mime,
        normalized_markdown=content_text,
        blocks_json=[],
        render_json={
            "format": "artifact",
            "source_file_name": file_name,
            "size_bytes": len(file_content or b""),
        },
        change_note=change_note,
        creator_id=creator_id,
    )
    asset.active_version_id = version.id
    return asset, version


def ensure_spec_asset_backfilled(db: Session, task: SddTask) -> Optional[SddAsset]:
    """遗留任务兜底：从 task.spec_doc_path 懒回填 SPEC 资产/版本。"""
    existing = asset_service.get_spec_asset_by_task(db, task.id)
    if existing:
        return existing

    spec_path = (task.spec_doc_path or "").strip()
    if not spec_path:
        return None
    abs_spec_path = os.path.abspath(spec_path)
    if not os.path.exists(abs_spec_path) or not os.path.isfile(abs_spec_path):
        return None

    try:
        with open(abs_spec_path, "rb") as f:
            raw = f.read()
    except Exception:
        return None

    file_name = os.path.basename(abs_spec_path)
    asset, _version = create_asset_version_from_upload(
        db,
        task,
        creator_id=task.creator_id,
        file_name=file_name,
        file_content=raw,
        change_note="Initial version (backfilled from task.spec_doc_path)",
    )
    return asset


def ensure_asset_has_version(db: Session, asset: SddAsset) -> Optional[SddAssetVersion]:
    """兜底保证资产存在可用版本（激活指针缺失/历史数据迁移）。"""
    if asset.active_version_id:
        active = repository.get_asset_version(db, asset.id, asset.active_version_id)
        if active:
            return active

    versions = repository.list_asset_versions(db, asset.id)
    if versions:
        newest = versions[0]
        asset.active_version_id = newest.id
        db.flush()
        return newest

    text = (asset.content_text or "").strip()
    if not text:
        return None

    source_name = asset.source_file_name or "legacy-spec.md"
    return create_asset_version_from_normalized_content(
        db,
        asset,
        creator_id=asset.creator_id,
        normalized_markdown=text,
        change_note="Initial version (backfilled from legacy asset content)",
        output_ext=asset.source_ext or ".md",
        output_mime=asset.source_mime or "text/markdown",
        output_file_name=source_name,
    )
