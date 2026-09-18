"""纯文本规范化：markdown / 纯文本 → 统一 block 列表。"""

from __future__ import annotations

import re
from typing import Any, Dict, List


def markdown_to_blocks(markdown: str) -> List[Dict[str, Any]]:
    """按标题/列表/段落切分 markdown → blocks（id 为 blk-N）。"""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Dict[str, Any]] = []
    current_para: List[str] = []
    block_index = 0

    def flush_paragraph() -> None:
        nonlocal block_index
        if not current_para:
            return
        text = " ".join(part.strip() for part in current_para if part.strip()).strip()
        current_para.clear()
        if not text:
            return
        block_index += 1
        blocks.append(
            {
                "id": f"blk-{block_index}",
                "type": "paragraph",
                "text": text,
                "order": block_index,
                "meta": {},
            }
        )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            block_index += 1
            level = len(heading_match.group(1))
            blocks.append(
                {
                    "id": f"blk-{block_index}",
                    "type": "heading",
                    "text": heading_match.group(2).strip(),
                    "order": block_index,
                    "meta": {"level": level},
                }
            )
            continue

        list_match = re.match(r"^([-*+]|\d+\.)\s+(.+)$", stripped)
        if list_match:
            flush_paragraph()
            block_index += 1
            marker = list_match.group(1)
            blocks.append(
                {
                    "id": f"blk-{block_index}",
                    "type": "list_item",
                    "text": list_match.group(2).strip(),
                    "order": block_index,
                    "meta": {"marker": marker},
                }
            )
            continue

        current_para.append(stripped)

    flush_paragraph()
    return blocks


def plain_text_to_markdown(text: str) -> str:
    """纯文本 → 规范 markdown（连续行合并为段落，空行分段）。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[str] = []
    buffer: List[str] = []

    def flush() -> None:
        if not buffer:
            return
        out.append(" ".join(part.strip() for part in buffer if part.strip()).strip())
        buffer.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            if out and out[-1] != "":
                out.append("")
            continue
        buffer.append(stripped)

    flush()
    while out and out[-1] == "":
        out.pop()

    return "\n".join(out).strip()
