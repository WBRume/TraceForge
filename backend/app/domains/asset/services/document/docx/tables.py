"""DOCX 表格解析：w:tbl → 表格 block 与批注锚点偏移换算，以及表格 → Markdown。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import xml.etree.ElementTree as ET

from app.domains.asset.services.document.docx.paragraphs import parse_paragraph_content
from app.domains.asset.services.document.docx.runs import merge_adjacent_runs
from app.domains.asset.services.document.docx.xml_utils import DOCX_NS_MAP


def parse_table_block(
    table_el: ET.Element,
    comments_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """解析 w:tbl → (table block, comment anchors)。

    单元格内多段落换行拼接，锚点偏移按 "段落\n单元格 | 单元格" 的
    行文本布局（分隔符 " | "、行间 "\n"）逐级累加。
    """
    rows_payload: List[Dict[str, Any]] = []
    row_line_texts: List[str] = []
    table_anchors: List[Dict[str, Any]] = []
    table_offset = 0

    for row in table_el.findall("./w:tr", DOCX_NS_MAP):
        row_cells: List[Dict[str, Any]] = []
        row_text_parts: List[str] = []
        row_anchor_items: List[Dict[str, Any]] = []
        row_cursor = 0

        for cell in row.findall("./w:tc", DOCX_NS_MAP):
            cell_runs: List[Dict[str, Any]] = []
            cell_text_parts: List[str] = []
            cell_anchors: List[Dict[str, Any]] = []
            cell_cursor = 0

            for paragraph in cell.findall("./w:p", DOCX_NS_MAP):
                paragraph_data = parse_paragraph_content(paragraph, comments_by_id)
                paragraph_text = str(paragraph_data.get("text") or "")
                if not paragraph_text:
                    continue

                if cell_text_parts:
                    cell_text_parts.append("\n")
                    cell_runs.append({"text": "\n"})
                    cell_cursor += 1

                cell_text_parts.append(paragraph_text)
                cell_runs.extend(list(paragraph_data.get("runs") or []))
                for anchor in list(paragraph_data.get("comment_anchors") or []):
                    mapped = dict(anchor)
                    if isinstance(mapped.get("char_start"), int):
                        mapped["char_start"] = cell_cursor + int(mapped["char_start"])
                    if isinstance(mapped.get("char_end"), int):
                        mapped["char_end"] = cell_cursor + int(mapped["char_end"])
                    cell_anchors.append(mapped)
                cell_cursor += len(paragraph_text)

            cell_text = "".join(cell_text_parts).strip()
            row_cells.append({"text": cell_text, "runs": merge_adjacent_runs(cell_runs)})
            row_text_parts.append(cell_text)

            for anchor in cell_anchors:
                mapped = dict(anchor)
                if isinstance(mapped.get("char_start"), int):
                    mapped["char_start"] = row_cursor + int(mapped["char_start"])
                if isinstance(mapped.get("char_end"), int):
                    mapped["char_end"] = row_cursor + int(mapped["char_end"])
                row_anchor_items.append(mapped)

            row_cursor += len(cell_text) + 3  # " | "

        rows_payload.append({"cells": row_cells})
        row_text = " | ".join(row_text_parts)
        row_line_texts.append(row_text)
        for anchor in row_anchor_items:
            mapped = dict(anchor)
            if isinstance(mapped.get("char_start"), int):
                mapped["char_start"] = table_offset + int(mapped["char_start"])
            if isinstance(mapped.get("char_end"), int):
                mapped["char_end"] = table_offset + int(mapped["char_end"])
            table_anchors.append(mapped)
        table_offset += len(row_text) + 1

    table_text = "\n".join(row_line_texts).strip()
    block = {
        "type": "table",
        "text": table_text,
        "table": {"rows": rows_payload},
        "meta": {
            "row_count": len(rows_payload),
            "column_count": max((len(row.get("cells") or []) for row in rows_payload), default=0),
        },
    }
    return block, table_anchors


def table_to_markdown(table_rows: List[Dict[str, Any]]) -> str:
    if not table_rows:
        return ""

    rows: List[List[str]] = []
    max_cols = 0
    for row in table_rows:
        cols = [str(cell.get("text") or "").replace("\n", "<br>").strip() for cell in (row.get("cells") or [])]
        rows.append(cols)
        max_cols = max(max_cols, len(cols))

    if max_cols <= 1:
        return "\n".join((item[0] if item else "") for item in rows).strip()

    padded_rows = [cols + [""] * (max_cols - len(cols)) for cols in rows]
    header = padded_rows[0]
    divider = ["---"] * max_cols
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(divider) + " |",
    ]
    for row in padded_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines).strip()
