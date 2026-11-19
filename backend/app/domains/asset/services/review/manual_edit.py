"""Manual review-block edits with anchor reconciliation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAsset, SddAssetThread, SddAssetVersion
from app.domains.asset.services import asset_discussion_service
from app.domains.asset.services.asset_resolution_service import (
    ResolutionServiceError,
    _blocks_to_markdown,
    _build_new_block_ast,
    _normalize_runs,
    _refresh_task_spec_pointer_and_bootstrap,
    _replace_block_ast,
    _runs_text,
)
from app.domains.asset.services.document import repository as document_repository
from app.domains.asset.services.document import versioning as document_versioning
from app.domains.asset.services.document.docx import edit_docx_paragraph


def _pick_closest_occurrence(text: str, keyword: str, target: int | None) -> int | None:
    if not text or not keyword:
        return None
    points: list[int] = []
    from_index = 0
    while from_index <= len(text) - len(keyword):
        idx = text.find(keyword, from_index)
        if idx < 0:
            break
        points.append(idx)
        from_index = idx + 1
    if not points:
        return None
    if not isinstance(target, int):
        return points[0]
    return min(points, key=lambda point: abs(point - target))


def _remap_anchor_selection(
    effective_anchor: dict[str, Any],
    new_text: str,
) -> tuple[str | None, int | None, int | None]:
    old_selected = str(effective_anchor.get("selected_text") or "").strip()
    if not old_selected or old_selected not in new_text:
        return None, None, None
    old_start = effective_anchor.get("char_start")
    try:
        old_start_int = int(old_start) if old_start is not None else None
    except Exception:
        old_start_int = None
    start = _pick_closest_occurrence(new_text, old_selected, old_start_int)
    if start is None:
        return None, None, None
    return old_selected, start, start + len(old_selected)


def _edit_docx_review_block(version: SddAssetVersion, block: dict[str, Any], old_text: str, new_text: str) -> bytes:
    spans = block.get("docx_spans") or []
    if len(spans) != 1 or not isinstance(spans[0].get("paragraph"), int):
        raise ResolutionServiceError("The review block has no source DOCX paragraph", status_code=422)
    try:
        return edit_docx_paragraph(version.original_path or "", spans[0]["paragraph"], old_text, new_text)
    except ValueError as exc:
        raise ResolutionServiceError(str(exc), status_code=422) from exc


def manual_edit_block(
    db: Session,
    *,
    asset: SddAsset,
    block_id: str,
    new_text: str,
    actor_user_id: str,
    context_version_id: str | None = None,
    change_note: str | None = None,
) -> tuple[SddAssetVersion, list[SddAssetThread]]:
    text = str(new_text or "")
    if not text.strip():
        raise ResolutionServiceError("Edited block content cannot be empty", status_code=422)

    resolved_context_version_id = str(context_version_id or "").strip() or asset.active_version_id
    base_version = document_repository.get_asset_version(db, asset.id, resolved_context_version_id)
    if not base_version:
        raise ResolutionServiceError("Document version not found", status_code=404)
    if str(base_version.id) != str(asset.active_version_id or ""):
        raise ResolutionServiceError(
            "Document has a newer version, please refresh and retry",
            status_code=409,
        )

    base_block = asset_discussion_service.get_block_by_id(base_version, block_id)
    if not base_block:
        raise ResolutionServiceError("Block not found in current version", status_code=404)
    if str(base_block.get("type") or "").strip().lower() == "table":
        raise ResolutionServiceError("Table blocks do not support manual editing", status_code=422)

    base_blocks = base_version.blocks_json or []
    if not isinstance(base_blocks, list):
        raise ResolutionServiceError("Base version blocks are invalid")

    output_ext = base_version.original_ext or asset.source_ext or ".md"
    if output_ext.lower() == ".docx":
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        old_text = str(base_block.get("text") or "")
        output_bytes = _edit_docx_review_block(base_version, base_block, old_text, text)
        next_blocks = base_blocks
        next_markdown = base_version.normalized_markdown or ""
    else:
        text = text.strip()
        old_runs = _normalize_runs(base_block.get("runs"), str(base_block.get("text") or ""))
        old_text = _runs_text(old_runs)
        target_block = _build_new_block_ast(base_block, old_runs, text)
        next_blocks = _replace_block_ast(base_blocks, block_id=block_id, target_block=target_block)
        next_markdown = _blocks_to_markdown(next_blocks)
        output_bytes = next_markdown.encode("utf-8")

    version = document_versioning.create_asset_version_from_normalized_content(
        db,
        asset,
        creator_id=actor_user_id,
        normalized_markdown=next_markdown,
        blocks_json=next_blocks,
        change_note=change_note or f"Manual edit on block {block_id}",
        base_version_id=base_version.id,
        output_ext=output_ext,
        output_mime=base_version.original_mime or asset.source_mime or "text/markdown",
        output_file_bytes=output_bytes,
        output_file_name=asset.source_file_name or f"spec-v{base_version.version_no + 1}.md",
    )

    affected_threads: list[SddAssetThread] = []
    for thread in asset_discussion_service.list_threads(db, asset_id=asset.id):
        anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
            db,
            thread=thread,
            context_version=base_version,
        )
        effective_anchor = (
            anchor_eval.get("effective_anchor") if isinstance(anchor_eval.get("effective_anchor"), dict) else {}
        )
        if str(effective_anchor.get("block_id") or "").strip() != str(block_id).strip():
            continue

        new_selected, new_start, new_end = _remap_anchor_selection(effective_anchor, text)
        try:
            asset_discussion_service.upsert_thread_anchor_mapping(
                db,
                thread=thread,
                version_id=version.id,
                block_id=block_id,
                selected_text=new_selected,
                char_start=new_start,
                char_end=new_end,
                actor_user_id=actor_user_id,
            )
        except ValueError:
            # Older historical data may miss stable anchor ids.
            pass

        anchor_eval_next = asset_discussion_service.resolve_thread_anchor_for_version(
            db,
            thread=thread,
            context_version=version,
        )
        if anchor_eval_next.get("anchor_status") == "missing":
            if str(thread.close_hint_state or "none") != "no_close_needed":
                asset_discussion_service.set_thread_close_hint(
                    db,
                    thread=thread,
                    state="pending",
                    reason="anchor_missing",
                    version_id=version.id,
                )
        elif str(thread.close_hint_reason or "") == "anchor_missing":
            asset_discussion_service.set_thread_close_hint(
                db,
                thread=thread,
                state="none",
                reason=None,
                version_id=None,
            )
        affected_threads.append(thread)

    if asset.task_id:
        _refresh_task_spec_pointer_and_bootstrap(
            db,
            task_id=asset.task_id,
            workspace_id=asset.workspace_id,
            asset=asset,
            version=version,
            refresh_mode="DELTA",
            refresh_context_json={
                "scope": "manual_edit",
                "block_id": block_id,
                "old_text": old_text[:2400],
                "new_text": text[:2400],
            },
        )

    db.flush()
    return version, affected_threads
