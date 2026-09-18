"""DOCX 构建：blocks/markdown → docx 字节（python-docx 优先，最小 zip 兜底）。"""

from __future__ import annotations

import html
import io
import re
import zipfile
from typing import Any, Dict, List, Optional

try:
    from docx import Document as DocxDocument  # type: ignore
except Exception:
    DocxDocument = None

from app.domains.asset.services.document import markdown_blocks
from app.domains.asset.services.document.docx.xml_utils import safe_int

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _extract_block_text_for_export(block: Dict[str, Any]) -> str:
    text = str(block.get("text") or "").strip()
    if text:
        return text

    runs = block.get("runs")
    if isinstance(runs, list):
        merged = "".join(str(item.get("text") or "") for item in runs if isinstance(item, dict)).strip()
        if merged:
            return merged

    cells = block.get("cells")
    if isinstance(cells, list):
        row_chunks: List[str] = []
        for row in cells:
            if not isinstance(row, list):
                continue
            cell_texts: List[str] = []
            for cell in row:
                if isinstance(cell, dict):
                    value = str(cell.get("text") or "").strip()
                    if value:
                        cell_texts.append(value)
            if cell_texts:
                row_chunks.append(" | ".join(cell_texts))
        if row_chunks:
            return "\n".join(row_chunks)

    return ""


def _normalize_export_paragraphs(
    blocks: List[Dict[str, Any]],
    markdown: str,
) -> List[Dict[str, Any]]:
    source_blocks: List[Dict[str, Any]] = [item for item in (blocks or []) if isinstance(item, dict)]
    if not source_blocks and str(markdown or "").strip():
        source_blocks = markdown_blocks.markdown_to_blocks(str(markdown or ""))

    paragraphs: List[Dict[str, Any]] = []
    for block in source_blocks:
        text = _extract_block_text_for_export(block)
        if not text:
            continue
        paragraphs.append(
            {
                "type": str(block.get("type") or "paragraph").strip().lower(),
                "text": text,
                "meta": block.get("meta") if isinstance(block.get("meta"), dict) else {},
            }
        )

    if paragraphs:
        return paragraphs

    fallback = str(markdown or "").strip()
    if not fallback:
        return [{"type": "paragraph", "text": "", "meta": {}}]
    return [{"type": "paragraph", "text": fallback, "meta": {}}]


def _format_export_line(paragraph: Dict[str, Any]) -> str:
    text = str(paragraph.get("text") or "")
    p_type = str(paragraph.get("type") or "paragraph").strip().lower()
    meta = paragraph.get("meta") if isinstance(paragraph.get("meta"), dict) else {}
    if p_type == "list_item":
        marker = str(meta.get("marker") or "-").strip() or "-"
        return f"{marker} {text}".strip()
    return text


def _build_minimal_docx_bytes(paragraphs: List[Dict[str, Any]]) -> bytes:
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    body_parts: List[str] = []
    for paragraph in paragraphs:
        text = _format_export_line(paragraph).replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n") if text else [""]
        for line in lines:
            if line:
                body_parts.append(
                    f'<w:p><w:r><w:t xml:space="preserve">{html.escape(line)}</w:t></w:r></w:p>'
                )
            else:
                body_parts.append("<w:p/>")
    if not body_parts:
        body_parts.append("<w:p/>")

    document_xml = (
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>"""
        """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">"""
        f"""<w:body>{''.join(body_parts)}<w:sectPr/></w:body>"""
        """</w:document>"""
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _build_docx_via_python_docx(paragraphs: List[Dict[str, Any]]) -> Optional[bytes]:
    if DocxDocument is None:
        return None
    try:
        doc = DocxDocument()
        if len(doc.paragraphs) == 1 and not str(doc.paragraphs[0].text or "").strip():
            element = doc.paragraphs[0]._element
            element.getparent().remove(element)

        for paragraph in paragraphs:
            text = str(paragraph.get("text") or "")
            p_type = str(paragraph.get("type") or "paragraph").strip().lower()
            meta = paragraph.get("meta") if isinstance(paragraph.get("meta"), dict) else {}
            if p_type == "heading":
                level = min(max(safe_int(meta.get("level"), default=1), 1), 6)
                doc.add_heading(text, level=level)
                continue
            if p_type == "list_item":
                marker = str(meta.get("marker") or "-").strip()
                style = "List Number" if re.match(r"^\d+\.$", marker) else "List Bullet"
                para = doc.add_paragraph(style=style)
                para.add_run(text)
                continue
            doc.add_paragraph(text)

        if not doc.paragraphs:
            doc.add_paragraph("")
        output = io.BytesIO()
        doc.save(output)
        return output.getvalue()
    except Exception:
        return None


def build_docx_bytes(blocks: List[Dict[str, Any]], markdown: str) -> Optional[bytes]:
    """由 blocks/markdown 构建 docx 字节；两条路径都失败时返回 None。"""
    paragraphs = _normalize_export_paragraphs(blocks, markdown)
    docx_bytes = _build_docx_via_python_docx(paragraphs)
    if docx_bytes:
        return docx_bytes
    try:
        return _build_minimal_docx_bytes(paragraphs)
    except Exception:
        return None
