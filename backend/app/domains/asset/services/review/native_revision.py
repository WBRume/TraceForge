"""Build and replay revisions against the original document version."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from app.domains.asset.models.asset import SddAssetVersion
from app.domains.asset.schemas.revision import (
    AppendDocxChapter,
    DocxRegionsReply,
    DocxRevisionRequest,
    EditableDocxRegion,
)
from app.domains.asset.services.document.docx import parse_docx_payload
from app.domains.asset.services.document.docx.paragraph_edit import (
    DocxChapter,
    diff_text_replacements,
    docx_edit_regions,
    edit_docx_ranges,
)
from app.domains.asset.services.document.text_source import decode_source, read_original

LINE_ENDING = re.compile(r"\r\n|\r|\n")
SOURCE_LINES = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


def selected_changes(revision: dict, change_ids: list[str]) -> list[dict]:
    ids = set(change_ids)
    changes = revision["changes"]
    if len(ids) != len(change_ids) or not ids.issubset({change["id"] for change in changes}):
        raise ValueError("The selection contains duplicate or unknown revisions")
    return [change for change in changes if change["id"] in ids]


def build_text_revision(original: str, candidate: str) -> dict:
    if "\0" in candidate:
        raise ValueError("The revised source contains invalid text")
    old_lines = SOURCE_LINES.findall(original)
    new_lines = SOURCE_LINES.findall(candidate)
    match = SequenceMatcher(
        a=[LINE_ENDING.sub("\n", line) for line in old_lines],
        b=[LINE_ENDING.sub("\n", line) for line in new_lines],
        autojunk=max(len(old_lines), len(new_lines)) > 2000,
    )
    starts = [0]
    for line in old_lines:
        starts.append(starts[-1] + len(line))
    endings = Counter(LINE_ENDING.findall(original))
    default_ending = endings.most_common(1)[0][0] if endings else "\n"
    changes = []
    for operation, start, end, new_start, new_end in match.get_opcodes():
        if operation == "equal":
            continue
        changed_lines = []
        for i, line in enumerate(new_lines[new_start:new_end], start):
            previous = LINE_ENDING.search(old_lines[i]) if i < end else None
            ending = previous.group() if previous else default_ending
            changed_lines.append(LINE_ENDING.sub(ending, line))
        changes.append(
            {
                "id": f"text-{len(changes) + 1}",
                "start": starts[start],
                "end": starts[end],
                "line": start + 1,
                "before": "".join(old_lines[start:end]),
                "after": "".join(changed_lines),
            }
        )
    return {"kind": "text", "original": original, "changes": changes}


def render_text_revision(version: SddAssetVersion, revision: dict, changes: list[dict]) -> bytes:
    original, encoding, bom = decode_source(read_original(version))
    if original != revision["original"]:
        raise ValueError("The original source no longer matches the revision")
    pieces = []
    cursor = 0
    for change in changes:
        pieces.extend((original[cursor : change["start"]], change["after"]))
        cursor = change["end"]
    pieces.append(original[cursor:])
    try:
        return bom + "".join(pieces).encode(encoding)
    except UnicodeEncodeError as exc:
        raise ValueError(f"The revised text contains characters outside the original {encoding} encoding") from exc


def read_docx_regions(blocks: list[dict], focus: list[str], request: DocxRevisionRequest) -> DocxRegionsReply:
    regions = docx_edit_regions(blocks)
    focus_ids = set(focus)
    query = re.compile(re.escape(request.query), re.IGNORECASE) if request.query else None
    ordered = sorted(regions.values(), key=lambda region: region.block_id not in focus_ids)
    matches = []
    for region in ordered:
        if request.region_id and region.id != request.region_id:
            continue
        match = query.search(region.text) if query else None
        if query and not match:
            continue
        start = max(0, match.start() - 900) if match else 0
        matches.append(
            EditableDocxRegion(
                region_id=region.id,
                block_id=region.block_id,
                text=region.text[start : start + 3000],
                start=start,
                total_characters=len(region.text),
                in_table=region.in_table,
            )
        )
        if len(matches) == 9:
            break
    return DocxRegionsReply(regions=matches[:8], more_matches=len(matches) > 8)


def build_docx_revision(version: SddAssetVersion, request: DocxRevisionRequest) -> dict:
    regions = docx_edit_regions(version.blocks_json or [])
    changes = []
    for index, operation in enumerate(request.changes, 1):
        change_id = f"docx-{index}"
        if isinstance(operation, AppendDocxChapter):
            if not operation.title.strip() or any(not paragraph.strip() for paragraph in operation.paragraphs):
                raise ValueError("Appended chapter titles and paragraphs must contain text")
            changes.append(
                {
                    "id": change_id,
                    **operation.model_dump(),
                    "before": "",
                    "after": "\n".join([operation.title, *operation.paragraphs]),
                }
            )
            continue
        region = regions.get(operation.region_id)
        if region is None:
            raise ValueError(f"Unknown editable region {operation.region_id}")
        start = operation.start
        if start is None:
            start = region.text.find(operation.old_text)
            if start >= 0 and region.text.find(operation.old_text, start + 1) >= 0:
                raise ValueError(f"Repeated text in {region.id}. Supply its exact start offset")
        end = start + len(operation.old_text)
        if start < 0 or region.text[start:end] != operation.old_text:
            raise ValueError(f"Original text at the requested range in {region.id} does not match")
        new_text = LINE_ENDING.sub("\n", operation.new_text)
        if new_text == operation.old_text:
            continue
        changes.append(
            {
                "id": change_id,
                "kind": "replace",
                "region_id": region.id,
                "start": start,
                "end": end,
                "before": operation.old_text,
                "after": new_text,
            }
        )
    revision = {"kind": "docx", "changes": changes}
    render_docx_revision(version, changes)
    return revision


def render_docx_revision(
    version: SddAssetVersion, changes: list[dict], *, preview: bool = False
) -> tuple[bytes, list[dict], list[dict]]:
    if not version.original_path:
        raise ValueError("The original DOCX is unavailable")
    regions = docx_edit_regions(version.blocks_json or [])
    replacements = defaultdict(list)
    chapters = []
    marks = {}
    for change in changes:
        if change["kind"] == "append":
            chapters.append(change)
        else:
            replacements[change["region_id"]].append(change)
    edits = []
    for region_id, group in replacements.items():
        region = regions[region_id]
        spans = []
        delta = 0
        cursor = 0
        for change in sorted(group, key=lambda item: item["start"]):
            start, end, after = change["start"], change["end"], change["after"]
            if start < cursor:
                raise ValueError("The requested DOCX text ranges overlap")
            if region.text[start:end] != change["before"]:
                raise ValueError("The original DOCX text no longer matches the revision")
            spans.extend(diff_text_replacements(change["before"], after, offset=start))
            marks[change["id"]] = (region.paragraph, start + delta, start + delta + len(after))
            delta += len(after) - (end - start)
            cursor = end
        edits.append((region.paragraph, region.text, spans))
    try:
        if changes:
            content, headings = edit_docx_ranges(
                version.original_path,
                edits,
                [DocxChapter(item["title"], item["level"], item["paragraphs"]) for item in chapters],
            )
        else:
            content, headings = read_original(version), []
    except (OSError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    if not preview:
        return content, [], []
    for change, ordinal in zip(chapters, headings, strict=True):
        marks[change["id"]] = (ordinal, 0, len(change["title"]))
    blocks = parse_docx_payload(content)["blocks_json"]
    by_ordinal = {region.paragraph: region for region in docx_edit_regions(blocks).values()}
    markers = []
    for change_id, (ordinal, start, end) in marks.items():
        region = by_ordinal.get(ordinal)
        if region is None:
            # An emptied paragraph still has a place on the page.
            block_id = f"revision-empty-{ordinal}"
            blocks.append(
                {
                    "id": block_id,
                    "type": "paragraph",
                    "text": "",
                    "docx_spans": [{"paragraph": ordinal, "start": 0, "end": 0}],
                }
            )
            region = by_ordinal[ordinal] = docx_edit_regions([blocks[-1]])[block_id]
        markers.append(
            {
                "id": change_id,
                "block_id": region.block_id,
                "region_id": region.id,
                "start": region.block_start + start,
                "end": region.block_start + end,
            }
        )
    return content, blocks, markers
