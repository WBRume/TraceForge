"""
Asset resolution proposal and apply service.
"""

from __future__ import annotations

import copy
import difflib
import io
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.domains.asset.models.asset import (
    AssetResolutionProposalStatus,
    AssetThreadMessageRole,
    SddAsset,
    SddAssetResolutionProposal,
    SddAssetThread,
    SddAssetVersion,
)
from app.domains.task.models.task import SddTask
from app.domains.asset.services import asset_discussion_service, asset_document_service
from app.domains.task.services import task_cli_state_service

try:
    from docx import Document as DocxDocument  # type: ignore
except Exception:
    DocxDocument = None


class ResolutionServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _render_block_to_markdown(block: Dict[str, Any]) -> str:
    text = str(block.get("text") or "").strip()
    block_type = str(block.get("type") or "paragraph")
    meta = block.get("meta") or {}
    if block_type == "heading":
        level = int(meta.get("level") or 1)
        level = min(max(level, 1), 6)
        return f"{'#' * level} {text}".rstrip()
    if block_type == "list_item":
        marker = str(meta.get("marker") or "-")
        if marker and not marker.endswith(".") and marker not in {"-", "*", "+"}:
            marker = "-"
        return f"{marker} {text}".rstrip()
    return text


def _blocks_to_markdown(blocks: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = _render_block_to_markdown(block)
        if not text:
            continue
        lines.append(text)
    return "\n\n".join(lines).strip()


def _normalize_role(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _collect_source_message_ids(thread: SddAssetThread) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    return [
        item.id
        for item in messages
        if _normalize_role(item.role) in {AssetThreadMessageRole.USER.value, AssetThreadMessageRole.AI.value}
        and str(item.content or "").strip()
    ]


def _build_diff(old_text: str, new_text: str) -> str:
    lines = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    return "\n".join(lines)


def _copy_without_keys(payload: Dict[str, Any], drop_keys: set[str]) -> Dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in payload.items() if k not in drop_keys and v is not None}


def _run_style(run: Dict[str, Any]) -> Dict[str, Any]:
    return _copy_without_keys(run, {"text", "revision"})


def _normalize_runs(raw_runs: Any, fallback_text: str) -> List[Dict[str, Any]]:
    if isinstance(raw_runs, list):
        normalized: List[Dict[str, Any]] = []
        for item in raw_runs:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "")
            if not text:
                continue
            run = {"text": text}
            run.update(_run_style(item))
            revision = item.get("revision")
            if isinstance(revision, dict):
                run["revision"] = {
                    "change_id": str(revision.get("change_id") or "").strip(),
                    "op": str(revision.get("op") or "").strip(),
                    "status": str(revision.get("status") or "pending").strip(),
                }
            normalized.append(run)
        if normalized:
            return normalized
    text = str(fallback_text or "")
    if not text:
        return []
    return [{"text": text}]


def _runs_text(runs: List[Dict[str, Any]]) -> str:
    return "".join(str(item.get("text") or "") for item in runs)


def _append_run(runs: List[Dict[str, Any]], run: Dict[str, Any]) -> None:
    text = str(run.get("text") or "")
    if not text:
        return
    candidate = copy.deepcopy(run)
    candidate["text"] = text
    if not runs:
        runs.append(candidate)
        return

    prev = runs[-1]
    prev_key = _copy_without_keys(prev, {"text"})
    next_key = _copy_without_keys(candidate, {"text"})
    if prev_key == next_key:
        prev["text"] = str(prev.get("text") or "") + text
        return
    runs.append(candidate)


def _slice_runs(runs: List[Dict[str, Any]], start: int, end: int) -> List[Dict[str, Any]]:
    if end <= start:
        return []
    cursor = 0
    chunks: List[Dict[str, Any]] = []
    for run in runs:
        run_text = str(run.get("text") or "")
        run_start = cursor
        run_end = cursor + len(run_text)
        cursor = run_end
        if run_end <= start or run_start >= end:
            continue
        overlap_start = max(start, run_start)
        overlap_end = min(end, run_end)
        piece = run_text[overlap_start - run_start : overlap_end - run_start]
        if not piece:
            continue
        chunk = {"text": piece}
        chunk.update(_run_style(run))
        chunks.append(chunk)
    return chunks


def _style_for_insert(runs: List[Dict[str, Any]], index: int) -> Dict[str, Any]:
    if not runs:
        return {}
    cursor = 0
    last_style: Dict[str, Any] = {}
    for run in runs:
        run_text = str(run.get("text") or "")
        style = _run_style(run)
        run_start = cursor
        run_end = cursor + len(run_text)
        if run_start <= index < run_end:
            return style
        if run_text:
            last_style = style
        cursor = run_end
    return last_style or _run_style(runs[0])


def _next_change_id(counter: List[int]) -> str:
    counter[0] += 1
    return f"chg-{counter[0]}"


def _compose_revision_runs(
    old_runs: List[Dict[str, Any]],
    old_text: str,
    new_text: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    matcher = difflib.SequenceMatcher(a=old_text, b=new_text)
    merged_runs: List[Dict[str, Any]] = []
    change_counter = [0]
    stats = {
        "inserted_chars": 0,
        "deleted_chars": 0,
        "inserted_segments": 0,
        "deleted_segments": 0,
    }

    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            for piece in _slice_runs(old_runs, i1, i2):
                _append_run(merged_runs, piece)
            continue

        if opcode in {"delete", "replace"}:
            deleted = _slice_runs(old_runs, i1, i2)
            if deleted:
                change_id = _next_change_id(change_counter)
                for piece in deleted:
                    piece["revision"] = {"change_id": change_id, "op": "delete", "status": "pending"}
                    _append_run(merged_runs, piece)
                stats["deleted_chars"] += sum(len(str(item.get("text") or "")) for item in deleted)
                stats["deleted_segments"] += 1

        if opcode in {"insert", "replace"}:
            inserted_text = new_text[j1:j2]
            if inserted_text:
                change_id = _next_change_id(change_counter)
                insert_run: Dict[str, Any] = {"text": inserted_text}
                insert_run.update(_style_for_insert(old_runs, i1))
                insert_run["revision"] = {"change_id": change_id, "op": "insert", "status": "pending"}
                _append_run(merged_runs, insert_run)
                stats["inserted_chars"] += len(inserted_text)
                stats["inserted_segments"] += 1

    stats["total_changes"] = stats["inserted_segments"] + stats["deleted_segments"]
    stats["pending_changes"] = stats["total_changes"]
    return merged_runs, stats


def _apply_patch_to_block_text(
    original_text: str,
    *,
    selected_text: Optional[str],
    char_start: Optional[int],
    char_end: Optional[int],
    replacement_text: str,
) -> str:
    if char_start is not None and char_end is not None and 0 <= char_start <= char_end <= len(original_text):
        return original_text[:char_start] + replacement_text + original_text[char_end:]
    if selected_text and selected_text in original_text:
        return original_text.replace(selected_text, replacement_text, 1)
    return replacement_text


def _build_new_block_ast(
    old_block: Dict[str, Any],
    old_runs: List[Dict[str, Any]],
    new_text: str,
) -> Dict[str, Any]:
    block = copy.deepcopy(old_block)
    block["text"] = new_text
    if new_text:
        run = {"text": new_text}
        run.update(_style_for_insert(old_runs, 0))
        block["runs"] = [run]
    else:
        block["runs"] = []
    return block


def _build_old_block_ast(old_block: Dict[str, Any], old_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    block = copy.deepcopy(old_block)
    block["runs"] = copy.deepcopy(old_runs)
    block["text"] = _runs_text(old_runs)
    return block


def _build_merged_block_ast(old_block: Dict[str, Any], merged_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    block = copy.deepcopy(old_block)
    block["runs"] = copy.deepcopy(merged_runs)
    block["text"] = _runs_text(merged_runs)
    return block


def _sanitize_final_block_ast(
    final_block_ast: Any,
    *,
    block_id: str,
    fallback_block: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(final_block_ast, dict):
        raise ResolutionServiceError("final_block_ast must be an object", status_code=422)

    base = copy.deepcopy(final_block_ast)
    base["id"] = block_id
    if not base.get("type"):
        base["type"] = fallback_block.get("type") or "paragraph"
    if "meta" not in base:
        base["meta"] = copy.deepcopy(fallback_block.get("meta") or {})
    if "order" not in base and fallback_block.get("order") is not None:
        base["order"] = fallback_block.get("order")

    runs = _normalize_runs(base.get("runs"), str(base.get("text") or ""))
    for run in runs:
        revision = run.get("revision")
        if isinstance(revision, dict):
            status = str(revision.get("status") or "pending").strip().lower()
            if status == "pending":
                raise ResolutionServiceError("There are pending revisions not processed", status_code=422)

    sanitized_runs: List[Dict[str, Any]] = []
    for run in runs:
        text = str(run.get("text") or "")
        if not text:
            continue
        clean = {"text": text}
        clean.update(_run_style(run))
        sanitized_runs.append(clean)

    if not sanitized_runs and str(base.get("text") or "").strip():
        sanitized_runs = [{"text": str(base.get("text") or "")}]

    sanitized_text = _runs_text(sanitized_runs)
    if not sanitized_text.strip():
        raise ResolutionServiceError("final_block_ast content cannot be empty", status_code=422)

    base["runs"] = sanitized_runs
    base["text"] = sanitized_text
    return base


def _sanitize_final_blocks_ast(
    final_blocks_ast: Any,
    *,
    base_blocks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(final_blocks_ast, list) or not final_blocks_ast:
        raise ResolutionServiceError("final_blocks_ast must be a non-empty array", status_code=422)

    base_map: Dict[str, Dict[str, Any]] = {}
    for idx, block in enumerate(base_blocks):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("id") or f"blk-{idx + 1}")
        base_map[block_id] = block

    sanitized: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, raw in enumerate(final_blocks_ast):
        if not isinstance(raw, dict):
            continue
        incoming_id = str(raw.get("id") or "").strip()
        fallback = (
            base_map.get(incoming_id)
            if incoming_id
            else (base_blocks[idx] if idx < len(base_blocks) and isinstance(base_blocks[idx], dict) else {})
        )
        block_id = incoming_id or str(fallback.get("id") or f"blk-{idx + 1}")
        if block_id in seen_ids:
            raise ResolutionServiceError(f"Duplicated block id in final_blocks_ast: {block_id}", status_code=422)
        seen_ids.add(block_id)
        clean = _sanitize_final_block_ast(
            raw,
            block_id=block_id,
            fallback_block=fallback or {"id": block_id, "type": "paragraph", "meta": {}},
        )
        if clean.get("order") is None:
            clean["order"] = idx + 1
        sanitized.append(clean)

    if not sanitized:
        raise ResolutionServiceError("final_blocks_ast has no valid block", status_code=422)
    return sanitized


def _replace_block_ast(
    blocks: List[Dict[str, Any]],
    *,
    block_id: str,
    target_block: Dict[str, Any],
) -> List[Dict[str, Any]]:
    cloned = copy.deepcopy(blocks)
    replaced = False
    for idx, block in enumerate(cloned):
        if isinstance(block, dict) and str(block.get("id")) == str(block_id):
            cloned[idx] = copy.deepcopy(target_block)
            replaced = True
            break
    if not replaced:
        raise ResolutionServiceError("Anchor block not found in base version")
    return cloned


def _rewrite_change_ids_with_prefix(runs: List[Dict[str, Any]], prefix: str) -> None:
    for run in runs:
        revision = run.get("revision")
        if not isinstance(revision, dict):
            continue
        change_id = str(revision.get("change_id") or "").strip()
        if not change_id:
            continue
        revision["change_id"] = f"{prefix}:{change_id}"


def _build_deleted_block_revision(
    old_block: Dict[str, Any],
    *,
    idx: int,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    old_runs = _normalize_runs(old_block.get("runs"), str(old_block.get("text") or ""))
    old_text = _runs_text(old_runs)
    merged_runs: List[Dict[str, Any]] = []
    change_id = f"blk-del-{idx + 1}"
    for run in old_runs:
        piece = copy.deepcopy(run)
        piece["revision"] = {"change_id": change_id, "op": "delete", "status": "pending"}
        merged_runs.append(piece)
    merged_block = copy.deepcopy(old_block)
    merged_block["runs"] = merged_runs
    merged_block["text"] = _runs_text(merged_runs)
    stats = {
        "inserted_chars": 0,
        "deleted_chars": len(old_text),
        "inserted_segments": 0,
        "deleted_segments": 1 if old_text else 0,
        "total_changes": 1 if old_text else 0,
        "pending_changes": 1 if old_text else 0,
    }
    return merged_block, stats


def _build_inserted_block_revision(
    new_block: Dict[str, Any],
    *,
    idx: int,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    new_runs = _normalize_runs(new_block.get("runs"), str(new_block.get("text") or ""))
    new_text = _runs_text(new_runs)
    merged_runs: List[Dict[str, Any]] = []
    change_id = f"blk-ins-{idx + 1}"
    for run in new_runs:
        piece = copy.deepcopy(run)
        piece["revision"] = {"change_id": change_id, "op": "insert", "status": "pending"}
        merged_runs.append(piece)
    merged_block = copy.deepcopy(new_block)
    merged_block["runs"] = merged_runs
    merged_block["text"] = _runs_text(merged_runs)
    stats = {
        "inserted_chars": len(new_text),
        "deleted_chars": 0,
        "inserted_segments": 1 if new_text else 0,
        "deleted_segments": 0,
        "total_changes": 1 if new_text else 0,
        "pending_changes": 1 if new_text else 0,
    }
    return merged_block, stats


def _merge_stats(target: Dict[str, int], delta: Dict[str, int]) -> None:
    for key, value in delta.items():
        target[key] = int(target.get(key, 0)) + int(value or 0)


def _compose_document_revisions(
    *,
    old_blocks: List[Dict[str, Any]],
    candidate_blocks: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    old_blocks_ast: List[Dict[str, Any]] = []
    new_blocks_ast: List[Dict[str, Any]] = []
    merged_blocks_ast: List[Dict[str, Any]] = []
    total_stats: Dict[str, int] = {
        "inserted_chars": 0,
        "deleted_chars": 0,
        "inserted_segments": 0,
        "deleted_segments": 0,
        "total_changes": 0,
        "pending_changes": 0,
    }
    length = max(len(old_blocks), len(candidate_blocks))

    for idx in range(length):
        old_block = old_blocks[idx] if idx < len(old_blocks) and isinstance(old_blocks[idx], dict) else None
        new_block_raw = (
            candidate_blocks[idx]
            if idx < len(candidate_blocks) and isinstance(candidate_blocks[idx], dict)
            else None
        )

        if old_block is not None and new_block_raw is not None:
            old_id = str(old_block.get("id") or f"blk-{idx + 1}")
            old_runs = _normalize_runs(old_block.get("runs"), str(old_block.get("text") or ""))
            old_text = _runs_text(old_runs)
            new_text = str(new_block_raw.get("text") or "").strip()
            if not new_text:
                new_text = _runs_text(_normalize_runs(new_block_raw.get("runs"), str(new_block_raw.get("text") or "")))

            new_block = copy.deepcopy(new_block_raw)
            new_block["id"] = old_id
            if "order" not in new_block:
                new_block["order"] = old_block.get("order", idx + 1)

            merged_runs, block_stats = _compose_revision_runs(old_runs, old_text, new_text)
            _rewrite_change_ids_with_prefix(merged_runs, old_id)

            merged_block = copy.deepcopy(old_block)
            merged_block["id"] = old_id
            merged_block["type"] = new_block.get("type") or old_block.get("type") or "paragraph"
            merged_block["meta"] = copy.deepcopy(new_block.get("meta") or old_block.get("meta") or {})
            merged_block["order"] = new_block.get("order", old_block.get("order", idx + 1))
            merged_block["runs"] = copy.deepcopy(merged_runs)
            merged_block["text"] = _runs_text(merged_runs)

            old_blocks_ast.append(_build_old_block_ast(old_block, old_runs))
            new_blocks_ast.append(_build_new_block_ast(merged_block, old_runs, new_text))
            merged_blocks_ast.append(merged_block)
            _merge_stats(total_stats, block_stats)
            continue

        if old_block is not None:
            old_id = str(old_block.get("id") or f"blk-{idx + 1}")
            old_runs = _normalize_runs(old_block.get("runs"), str(old_block.get("text") or ""))
            old_blocks_ast.append(_build_old_block_ast(old_block, old_runs))
            new_blocks_ast.append(
                {
                    "id": old_id,
                    "type": old_block.get("type") or "paragraph",
                    "text": "",
                    "runs": [],
                    "meta": copy.deepcopy(old_block.get("meta") or {}),
                    "order": old_block.get("order", idx + 1),
                }
            )
            merged_block, block_stats = _build_deleted_block_revision(old_block, idx=idx)
            merged_block["id"] = old_id
            merged_blocks_ast.append(merged_block)
            _merge_stats(total_stats, block_stats)
            continue

        if new_block_raw is not None:
            new_id = f"blk-new-{idx + 1}"
            new_block = copy.deepcopy(new_block_raw)
            new_block["id"] = new_id
            if "order" not in new_block:
                new_block["order"] = idx + 1
            new_runs = _normalize_runs(new_block.get("runs"), str(new_block.get("text") or ""))
            old_blocks_ast.append(
                {
                    "id": new_id,
                    "type": new_block.get("type") or "paragraph",
                    "text": "",
                    "runs": [],
                    "meta": copy.deepcopy(new_block.get("meta") or {}),
                    "order": new_block.get("order", idx + 1),
                }
            )
            new_blocks_ast.append(_build_new_block_ast(new_block, new_runs, _runs_text(new_runs)))
            merged_block, block_stats = _build_inserted_block_revision(new_block, idx=idx)
            merged_block["id"] = new_id
            _rewrite_change_ids_with_prefix(merged_block.get("runs") or [], new_id)
            merged_blocks_ast.append(merged_block)
            _merge_stats(total_stats, block_stats)

    return old_blocks_ast, new_blocks_ast, merged_blocks_ast, total_stats


def create_resolution_proposal(
    db: Session,
    *,
    thread: SddAssetThread,
    creator_id: str,
    proposed_text: str,
    overwrite_existing_draft: bool = False,
    source_message_ids: Optional[List[str]] = None,
    version: Optional[SddAssetVersion] = None,
    effective_anchor: Optional[Dict[str, Any]] = None,
) -> SddAssetResolutionProposal:
    version = version or thread.version
    if not version:
        raise ResolutionServiceError("Thread version not found")

    anchor = effective_anchor if isinstance(effective_anchor, dict) else {}
    block_id = str(anchor.get("block_id") or thread.block_id or "").strip()
    if not block_id:
        raise ResolutionServiceError("Anchor block id is required")

    block = asset_discussion_service.get_block_by_id(version, block_id)
    if not block:
        raise ResolutionServiceError("Anchor block not found on version")

    old_runs = _normalize_runs(block.get("runs"), str(block.get("text") or ""))
    old_text = _runs_text(old_runs)
    if not old_text.strip():
        raise ResolutionServiceError("Target block text is empty", status_code=422)

    proposal_text = (proposed_text or "").strip()
    if not proposal_text:
        raise ResolutionServiceError("proposed_text is required", status_code=422)

    old_block_ast = _build_old_block_ast(block, old_runs)
    patch_json: Dict[str, Any] = {
        "thread_id": thread.id,
        "block_id": block_id,
        "selected_text": str(anchor.get("selected_text") or thread.selected_text or "").strip() or None,
        "char_start": anchor.get("char_start", thread.char_start),
        "char_end": anchor.get("char_end", thread.char_end),
        "context_version_id": version.id,
        "effective_anchor": {
            "block_id": block_id,
            "selected_text": str(anchor.get("selected_text") or thread.selected_text or "").strip() or None,
            "char_start": anchor.get("char_start", thread.char_start),
            "char_end": anchor.get("char_end", thread.char_end),
        },
        "old_text": old_text,
        "proposal_text": proposal_text,
        "old_block_ast": old_block_ast,
        "rewrite_status": "draft",
    }
    ids = source_message_ids or _collect_source_message_ids(thread)
    if ids:
        patch_json["source_message_ids"] = [str(item).strip() for item in ids if str(item).strip()]

    existing_drafts = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.thread_id == thread.id,
            SddAssetResolutionProposal.status == AssetResolutionProposalStatus.DRAFT,
        )
        .order_by(SddAssetResolutionProposal.updated_at.desc(), SddAssetResolutionProposal.created_at.desc())
        .all()
    )
    if existing_drafts:
        if not overwrite_existing_draft:
            raise ResolutionServiceError("Draft proposal already exists", status_code=409)
        primary = existing_drafts[0]
        primary.base_version_id = version.id
        primary.proposed_patch_json = patch_json
        primary.diff_text = None
        primary.status = AssetResolutionProposalStatus.DRAFT
        primary.creator_id = creator_id
        flag_modified(primary, "proposed_patch_json")
        for stale in existing_drafts[1:]:
            stale.status = AssetResolutionProposalStatus.DISCARDED
        db.flush()
        return primary

    proposal = SddAssetResolutionProposal(
        thread_id=thread.id,
        base_version_id=version.id,
        proposed_patch_json=patch_json,
        diff_text=None,
        status=AssetResolutionProposalStatus.DRAFT,
        creator_id=creator_id,
    )
    db.add(proposal)
    db.flush()
    return proposal


def update_resolution_proposal_rewrite(
    db: Session,
    *,
    thread: SddAssetThread,
    proposal: SddAssetResolutionProposal,
    proposal_text: str,
    rewritten_text: str,
    rewrite_scope: str = "anchor",
    rewritten_markdown: Optional[str] = None,
    selection_mode: bool = False,
    context_version_id: Optional[str] = None,
    relocated_anchor: Optional[Dict[str, Any]] = None,
) -> SddAssetResolutionProposal:
    if proposal.status != AssetResolutionProposalStatus.DRAFT:
        raise ResolutionServiceError("Only draft proposals can be rewritten", status_code=409)
    if proposal.thread_id != thread.id:
        raise ResolutionServiceError("Proposal does not belong to thread")

    requested_version_id = str(context_version_id or "").strip() or str(proposal.base_version_id)
    version = asset_document_service.get_asset_version(db, thread.asset_id, requested_version_id)
    if not version and str(requested_version_id) != str(proposal.base_version_id):
        version = asset_document_service.get_asset_version(db, thread.asset_id, proposal.base_version_id)
    if not version:
        raise ResolutionServiceError("Proposal base version not found")

    patch = copy.deepcopy(proposal.proposed_patch_json) if isinstance(proposal.proposed_patch_json, dict) else {}
    relocated = relocated_anchor if isinstance(relocated_anchor, dict) else {}
    block_id = str(relocated.get("block_id") or patch.get("block_id") or thread.block_id or "").strip()
    if not block_id:
        raise ResolutionServiceError("Proposal block_id is invalid")

    base_blocks = list(version.blocks_json or [])
    block = asset_discussion_service.get_block_by_id(version, block_id)
    if not block:
        raise ResolutionServiceError("Anchor block not found on version")

    old_runs = _normalize_runs(block.get("runs"), str(block.get("text") or ""))
    old_text = _runs_text(old_runs)
    if not old_text.strip():
        raise ResolutionServiceError("Target block text is empty", status_code=422)

    selected_text_for_patch = str(
        relocated.get("selected_text")
        or patch.get("selected_text")
        or thread.selected_text
        or ""
    ).strip() or None
    char_start_raw = relocated.get("char_start", patch.get("char_start", thread.char_start))
    char_end_raw = relocated.get("char_end", patch.get("char_end", thread.char_end))
    try:
        char_start = int(char_start_raw) if char_start_raw is not None else None
    except Exception:
        char_start = None
    try:
        char_end = int(char_end_raw) if char_end_raw is not None else None
    except Exception:
        char_end = None
    if (
        char_start is not None
        and char_end is not None
        and (char_start < 0 or char_end < char_start or char_end > len(old_text))
    ):
        char_start = None
        char_end = None

    patch["block_id"] = block_id
    patch["selected_text"] = selected_text_for_patch
    patch["char_start"] = char_start
    patch["char_end"] = char_end
    patch["context_version_id"] = version.id
    patch["effective_anchor"] = {
        "block_id": block_id,
        "selected_text": selected_text_for_patch,
        "char_start": char_start,
        "char_end": char_end,
    }
    if relocated:
        patch["relocated_anchor"] = {
            "block_id": block_id,
            "selected_text": selected_text_for_patch,
            "char_start": char_start,
            "char_end": char_end,
        }

    normalized_scope = str(rewrite_scope or "anchor").strip().lower()
    if normalized_scope == "document":
        markdown = str(rewritten_markdown or "").strip()
        if not markdown:
            raise ResolutionServiceError("Rewritten document markdown cannot be empty", status_code=422)
        parsed = asset_document_service.parse_document_payload("proposal-rewrite.md", markdown.encode("utf-8"))
        candidate_blocks = list(parsed.get("blocks_json") or [])
        if not candidate_blocks:
            raise ResolutionServiceError("Failed to parse rewritten document blocks", status_code=422)

        old_blocks_ast, new_blocks_ast, merged_blocks_ast, change_stats = _compose_document_revisions(
            old_blocks=base_blocks,
            candidate_blocks=candidate_blocks,
        )
        new_markdown = str(parsed.get("normalized_markdown") or "").strip() or _blocks_to_markdown(new_blocks_ast)

        anchor_merged = next(
            (item for item in merged_blocks_ast if str(item.get("id") or "") == block_id),
            merged_blocks_ast[0] if merged_blocks_ast else None,
        )
        anchor_new = next(
            (item for item in new_blocks_ast if str(item.get("id") or "") == block_id),
            new_blocks_ast[0] if new_blocks_ast else None,
        )
        patch["old_text"] = old_text
        patch["new_text"] = str((anchor_new or {}).get("text") or "")
        patch["old_block_ast"] = _build_old_block_ast(block, old_runs)
        patch["new_block_ast"] = copy.deepcopy(anchor_new) if isinstance(anchor_new, dict) else None
        patch["merged_block_ast"] = copy.deepcopy(anchor_merged) if isinstance(anchor_merged, dict) else None
        patch["old_blocks_ast"] = old_blocks_ast
        patch["new_blocks_ast"] = new_blocks_ast
        patch["merged_blocks_ast"] = merged_blocks_ast
        patch["new_markdown"] = new_markdown
        patch["change_stats"] = change_stats
        patch["rewrite_scope"] = "document"
        patch["rewrite_status"] = "ready"
        patch["proposal_text"] = str(proposal_text or "").strip() or str(patch.get("proposal_text") or "").strip()
        proposal.proposed_patch_json = patch
        flag_modified(proposal, "proposed_patch_json")
        proposal.diff_text = _build_diff(_blocks_to_markdown(base_blocks), new_markdown)
        db.flush()
        return proposal

    rewrite_result = str(rewritten_text or "").strip()
    if not rewrite_result:
        raise ResolutionServiceError("Rewritten block content cannot be empty", status_code=422)

    if selection_mode and (selected_text_for_patch or (char_start is not None and char_end is not None)):
        new_text = _apply_patch_to_block_text(
            old_text,
            selected_text=selected_text_for_patch,
            char_start=char_start,
            char_end=char_end,
            replacement_text=rewrite_result,
        )
    else:
        new_text = rewrite_result

    merged_runs, change_stats = _compose_revision_runs(old_runs, old_text, new_text)
    old_block_ast = _build_old_block_ast(block, old_runs)
    new_block_ast = _build_new_block_ast(block, old_runs, new_text)
    merged_block_ast = _build_merged_block_ast(block, merged_runs)

    patch["old_text"] = old_text
    patch["new_text"] = new_text
    patch["proposal_text"] = str(proposal_text or "").strip() or str(patch.get("proposal_text") or "").strip()
    patch["old_block_ast"] = old_block_ast
    patch["new_block_ast"] = new_block_ast
    patch["merged_block_ast"] = merged_block_ast
    patch["change_stats"] = change_stats
    patch["rewrite_scope"] = "anchor"
    patch["rewrite_status"] = "ready"

    proposal.proposed_patch_json = patch
    flag_modified(proposal, "proposed_patch_json")
    proposal.diff_text = _build_diff(old_text, new_text)
    db.flush()
    return proposal


def _try_apply_docx_text(
    base_version: SddAssetVersion,
    *,
    old_text: str,
    new_text: str,
    selected_text: Optional[str],
) -> Optional[bytes]:
    if not DocxDocument:
        return None
    base_path = (base_version.original_path or "").strip()
    if not base_path:
        return None

    try:
        doc = DocxDocument(base_path)
    except Exception:
        return None

    replaced = False
    for paragraph in doc.paragraphs:
        current = paragraph.text or ""
        if not replaced and current.strip() == old_text.strip():
            paragraph.text = new_text
            replaced = True
            break
        if not replaced and selected_text and selected_text in current:
            paragraph.text = current.replace(selected_text, new_text, 1)
            replaced = True
            break

    if not replaced:
        return None

    buffer = io.BytesIO()
    try:
        doc.save(buffer)
    except Exception:
        return None
    return buffer.getvalue()


def _refresh_task_spec_pointer_and_bootstrap(
    db: Session,
    *,
    task_id: str,
    workspace_id: str,
    asset: SddAsset,
    version: SddAssetVersion,
    refresh_mode: str = "FULL",
    refresh_context_json: Optional[Dict[str, Any]] = None,
) -> None:
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if task and version.original_path:
        task.spec_doc_path = os.path.abspath(version.original_path)

    task_cli_state_service.upsert_bootstrap_for_upload(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        spec_asset_id=asset.id,
        spec_version_id=version.id,
        refresh_mode=refresh_mode,
        refresh_context_json=refresh_context_json,
    )


def apply_resolution_proposal(
    db: Session,
    *,
    asset: SddAsset,
    thread: SddAssetThread,
    proposal: SddAssetResolutionProposal,
    actor_user_id: str,
    final_block_ast: Any,
    final_blocks_ast: Optional[List[Any]] = None,
    change_note: Optional[str] = None,
) -> SddAssetVersion:
    if proposal.status != AssetResolutionProposalStatus.DRAFT:
        raise ResolutionServiceError("Only draft proposals can be applied", status_code=409)
    if proposal.thread_id != thread.id:
        raise ResolutionServiceError("Proposal does not belong to thread")
    if proposal.base_version_id is None:
        raise ResolutionServiceError("Proposal base version is missing")

    active_version_id = str(asset.active_version_id or "").strip()
    proposal_version_id = str(proposal.base_version_id or "").strip()
    requested_base_version_id = active_version_id or proposal_version_id
    base_version = asset_document_service.get_asset_version(db, asset.id, requested_base_version_id)
    if not base_version and requested_base_version_id != proposal_version_id:
        base_version = asset_document_service.get_asset_version(db, asset.id, proposal_version_id)
    if not base_version:
        raise ResolutionServiceError("Proposal base version not found")

    patch = copy.deepcopy(proposal.proposed_patch_json) if isinstance(proposal.proposed_patch_json, dict) else {}
    base_blocks = base_version.blocks_json or []
    if not isinstance(base_blocks, list):
        raise ResolutionServiceError("Base version blocks are invalid")

    anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
        db,
        thread=thread,
        context_version=base_version,
    )
    context_anchor = (
        anchor_eval.get("effective_anchor")
        if isinstance(anchor_eval.get("effective_anchor"), dict)
        else {}
    )
    prefer_context_anchor = str(base_version.id) != proposal_version_id

    def _first_non_empty(*values: Any) -> Optional[str]:
        for value in values:
            normalized = str(value or "").strip()
            if normalized:
                return normalized
        return None

    def _first_not_none(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    if prefer_context_anchor:
        block_id = _first_non_empty(
            context_anchor.get("block_id"),
            patch.get("block_id"),
            thread.block_id,
        )
    else:
        block_id = _first_non_empty(
            patch.get("block_id"),
            context_anchor.get("block_id"),
            thread.block_id,
        )
    if not block_id:
        raise ResolutionServiceError("Proposal block_id is invalid")

    base_block = asset_discussion_service.get_block_by_id(base_version, block_id)
    if not base_block:
        raise ResolutionServiceError("Anchor block not found in base version")

    if prefer_context_anchor:
        selected_text_for_apply = _first_non_empty(
            context_anchor.get("selected_text"),
            patch.get("selected_text"),
            thread.selected_text,
        )
        char_start_for_apply = _first_not_none(
            context_anchor.get("char_start"),
            patch.get("char_start"),
            thread.char_start,
        )
        char_end_for_apply = _first_not_none(
            context_anchor.get("char_end"),
            patch.get("char_end"),
            thread.char_end,
        )
    else:
        selected_text_for_apply = _first_non_empty(
            patch.get("selected_text"),
            context_anchor.get("selected_text"),
            thread.selected_text,
        )
        char_start_for_apply = _first_not_none(
            patch.get("char_start"),
            context_anchor.get("char_start"),
            thread.char_start,
        )
        char_end_for_apply = _first_not_none(
            patch.get("char_end"),
            context_anchor.get("char_end"),
            thread.char_end,
        )

    patch["context_version_id"] = base_version.id
    patch["block_id"] = block_id
    patch["selected_text"] = selected_text_for_apply
    patch["char_start"] = char_start_for_apply
    patch["char_end"] = char_end_for_apply
    if str(base_version.id) != proposal_version_id:
        patch["rebased_from_version_id"] = proposal_version_id
        patch["rebased_to_version_id"] = base_version.id

    old_runs = _normalize_runs(base_block.get("runs"), str(base_block.get("text") or ""))
    old_text = _runs_text(old_runs)
    if not old_text.strip():
        raise ResolutionServiceError("Base block content is empty", status_code=422)

    rewrite_scope = str(patch.get("rewrite_scope") or "anchor").strip().lower()
    use_document_apply = bool(final_blocks_ast) or rewrite_scope == "document"

    if use_document_apply:
        effective_blocks = final_blocks_ast
        if not effective_blocks:
            merged_blocks = patch.get("merged_blocks_ast")
            if isinstance(merged_blocks, list) and merged_blocks:
                effective_blocks = merged_blocks
        sanitized_blocks = _sanitize_final_blocks_ast(
            effective_blocks,
            base_blocks=base_blocks,
        )
        next_blocks = copy.deepcopy(sanitized_blocks)
        next_markdown = _blocks_to_markdown(next_blocks)
        anchor_applied = next(
            (item for item in next_blocks if str(item.get("id") or "") == block_id),
            next_blocks[0] if next_blocks else None,
        )
        new_text = str((anchor_applied or {}).get("text") or "")
        patch["new_text"] = new_text
        patch["final_blocks_ast"] = copy.deepcopy(next_blocks)
        patch["final_block_ast"] = copy.deepcopy(anchor_applied) if isinstance(anchor_applied, dict) else None
        patch["rewrite_scope"] = "document"
        proposal.diff_text = _build_diff(_blocks_to_markdown(base_blocks), next_markdown)
    else:
        sanitized_block = _sanitize_final_block_ast(
            final_block_ast,
            block_id=block_id,
            fallback_block=base_block,
        )
        new_text = _runs_text(_normalize_runs(sanitized_block.get("runs"), str(sanitized_block.get("text") or "")))
        if not new_text.strip():
            raise ResolutionServiceError("Resulting block content cannot be empty", status_code=422)
        next_blocks = _replace_block_ast(base_blocks, block_id=block_id, target_block=sanitized_block)
        next_markdown = _blocks_to_markdown(next_blocks)
        patch["new_text"] = new_text
        patch["final_block_ast"] = copy.deepcopy(sanitized_block)
        patch["rewrite_scope"] = "anchor"
        proposal.diff_text = _build_diff(old_text, new_text)

    patch["old_text"] = old_text
    patch["change_stats"] = patch.get("change_stats") or {}
    proposal.proposed_patch_json = patch
    flag_modified(proposal, "proposed_patch_json")

    output_bytes: Optional[bytes] = None
    if (asset.source_ext or "").lower() == ".docx" and not use_document_apply:
        output_bytes = _try_apply_docx_text(
            base_version,
            old_text=old_text,
            new_text=new_text,
            selected_text=selected_text_for_apply,
        )

    if output_bytes is None:
        output_bytes = next_markdown.encode("utf-8")

    version = asset_document_service.create_asset_version_from_normalized_content(
        db,
        asset,
        creator_id=actor_user_id,
        normalized_markdown=next_markdown,
        blocks_json=next_blocks,
        change_note=change_note or f"Applied thread {thread.id} resolution",
        base_version_id=base_version.id,
        output_ext=asset.source_ext or base_version.original_ext or ".md",
        output_mime=asset.source_mime or base_version.original_mime or "text/markdown",
        output_file_bytes=output_bytes,
        output_file_name=asset.source_file_name or f"spec-v{base_version.version_no + 1}.md",
    )

    effective_anchor = patch.get("effective_anchor") if isinstance(patch.get("effective_anchor"), dict) else {}
    effective_block_id = str(effective_anchor.get("block_id") or block_id or "").strip() or block_id
    effective_selected_text = str(
        effective_anchor.get("selected_text")
        or patch.get("selected_text")
        or thread.selected_text
        or ""
    ).strip() or None
    effective_char_start = effective_anchor.get("char_start", patch.get("char_start", thread.char_start))
    effective_char_end = effective_anchor.get("char_end", patch.get("char_end", thread.char_end))
    try:
        effective_char_start = int(effective_char_start) if effective_char_start is not None else None
    except Exception:
        effective_char_start = None
    try:
        effective_char_end = int(effective_char_end) if effective_char_end is not None else None
    except Exception:
        effective_char_end = None

    try:
        asset_discussion_service.upsert_thread_anchor_mapping(
            db,
            thread=thread,
            version_id=version.id,
            block_id=effective_block_id,
            selected_text=effective_selected_text,
            char_start=effective_char_start,
            char_end=effective_char_end,
            actor_user_id=actor_user_id,
        )
    except ValueError:
        # Older historical data may miss stable anchor ids.
        # Applying proposal should still succeed; thread can be handled via close-hint flow.
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

    if thread.task_id:
        refresh_mode = "DELTA" if str(patch.get("rewrite_scope") or "anchor").strip().lower() == "anchor" else "FULL"
        refresh_context = {
            "scope": str(patch.get("rewrite_scope") or "anchor").strip().lower(),
            "thread_id": thread.id,
            "proposal_id": proposal.id,
            "block_id": effective_block_id,
            "selected_text": effective_selected_text,
            "old_text": old_text[:2400],
            "new_text": str(patch.get("new_text") or "")[:2400],
        }
        _refresh_task_spec_pointer_and_bootstrap(
            db,
            task_id=thread.task_id,
            workspace_id=thread.workspace_id,
            asset=asset,
            version=version,
            refresh_mode=refresh_mode,
            refresh_context_json=refresh_context,
        )

    proposal.status = AssetResolutionProposalStatus.APPLIED
    for item in list(thread.proposals or []):
        if item.id == proposal.id:
            continue
        if item.status == AssetResolutionProposalStatus.DRAFT:
            item.status = AssetResolutionProposalStatus.DISCARDED

    asset_discussion_service.add_thread_message(
        db,
        thread=thread,
        role=AssetThreadMessageRole.SYSTEM,
        content=f"已应用提案并生成文档版本 v{version.version_no}",
        creator_id=actor_user_id,
        metadata_json={"applied_version_id": version.id, "proposal_id": proposal.id},
    )
    db.flush()
    return version
