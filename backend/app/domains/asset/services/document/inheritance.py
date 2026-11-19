"""Carry proven review selections forward without guessing at repeated text."""

from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAssetVersion
from app.domains.asset.services import asset_discussion_service as discussions
from app.domains.asset.services.document.text_source import SOURCE_BLOCK_ID, review_source


def _unique_offset(text: str, value: str) -> int | None:
    first = text.find(value)
    return first if first >= 0 and text.find(value, first + 1) < 0 else None


def _locate(old: str, new: str, quote: str, start: int | None) -> tuple[int | None, str | None]:
    if quote not in new:
        return None, "anchor_missing"
    old_unique = _unique_offset(old, quote)
    new_unique = _unique_offset(new, quote)
    if start is None or start < 0 or old[start : start + len(quote)] != quote:
        start = old_unique
    if old == new and start is not None:
        return start, None
    if old_unique is not None and new_unique is not None:
        return new_unique, None
    if start is not None:
        first = max(0, start - 32)
        excerpt = old[first : start + len(quote) + 32]
        match = _unique_offset(new, excerpt)
        if match is not None and len(excerpt) > len(quote):
            return match + start - first, None
    return None, "anchor_ambiguous"


def _locate_table_selection(
    old_block: dict,
    new_block: dict,
    quote: str,
    start: int | None,
) -> tuple[int | None, str | None]:
    old_text = old_block["text"]
    if start is None or start < 0 or old_text[start : start + len(quote)] != quote:
        start = _unique_offset(old_text, quote)
    if start is None:
        return None, "anchor_ambiguous"
    end = start + len(quote)
    old_spans = old_block.get("docx_spans") or []
    first = next((span for span in old_spans if span["start"] <= start < span["end"]), None)
    last = next((span for span in old_spans if span["start"] < end <= span["end"]), None)
    if not first or not last:
        return None, "anchor_missing"
    new_spans = {span["paragraph"]: span for span in new_block.get("docx_spans") or []}
    new_first = new_spans.get(first["paragraph"])
    new_last = new_spans.get(last["paragraph"])
    if not new_first or not new_last:
        return None, "anchor_missing"
    offset, reason = _locate(
        old_text[first["start"] : last["end"]],
        new_block["text"][new_first["start"] : new_last["end"]],
        quote,
        start - first["start"],
    )
    return (new_first["start"] + offset if offset is not None else None), reason


def _target(
    base: SddAssetVersion, version: SddAssetVersion, anchor: dict
) -> tuple[str, str | None, int | None, str | None]:
    block_id = anchor["block_id"]
    old_block = str(anchor.get("block_text") or "")
    quote = anchor.get("selected_text")
    start = anchor.get("char_start")
    if anchor.get("reason"):
        return block_id, quote, None, anchor["reason"]
    source = review_source(version)
    if source is not None:
        old = review_source(base) or ""
        if block_id != SOURCE_BLOCK_ID:
            location = _unique_offset(old, old_block) if old_block else None
            start = location + start if location is not None and start is not None else None
        quote = quote or old_block.strip()
        if not quote:
            return SOURCE_BLOCK_ID, None, None, "anchor_missing"
        start, reason = _locate(old, source, quote, start)
        return SOURCE_BLOCK_ID, quote, start, reason

    block = discussions.get_block_by_id(version, block_id)
    if not block:
        return block_id, quote, None, "anchor_missing"
    if quote:
        base_block = discussions.get_block_by_id(base, block_id)
        if base_block and base_block.get("type") == "table" and block.get("type") == "table":
            start, reason = _locate_table_selection(base_block, block, quote, start)
        else:
            start, reason = _locate(old_block, str(block.get("text") or ""), quote, start)
        return block_id, quote, start, reason
    return block_id, None, None, None


def inherit_anchors(db: Session, base: SddAssetVersion, version: SddAssetVersion, user_id: str) -> None:
    for thread in discussions.list_threads(db, asset_id=base.asset_id):
        evaluation = discussions.resolve_thread_anchor_for_version(db, thread=thread, context_version=base)
        anchor = evaluation["effective_anchor"]
        if evaluation["anchor_status"] != "valid":
            anchor.setdefault("reason", "anchor_missing")
        block_id, quote, start, reason = _target(base, version, anchor)
        discussions.upsert_thread_anchor_mapping(
            db,
            thread=thread,
            version_id=version.id,
            block_id=block_id,
            selected_text=quote,
            char_start=start,
            char_end=start + len(quote) if start is not None and quote else None,
            actor_user_id=user_id,
            unresolved_reason=reason,
        )
