"""
文档解析子系统测试（document.payload / document.docx）

覆盖：md/txt/docx/pdf 解析分发、DOCX XML 解析（标题/编号列表/表格/批注）、
DOCX 构建回读 roundtrip、docx 字节识别。
"""

import io
import os
import sys
import zipfile

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.asset.services.document import markdown_blocks  # noqa: E402
from app.domains.asset.services.document.docx import (  # noqa: E402
    build_docx_bytes,
    looks_like_docx_bytes,
    parse_docx_payload,
)
from app.domains.asset.services.document.payload import (  # noqa: E402
    can_inline_review,
    parse_document_payload,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOCX_NS_DECL = f'xmlns:w="{W_NS}"'


def _w(tag: str) -> str:
    return f"w:{tag}"


def _run_xml(text: str, bold: bool = False) -> str:
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f"<w:r>{rpr}<w:t xml:space=\"preserve\">{text}</w:t></w:r>"


def _para_xml(
    runs: str,
    style: str = None,
    num_id: str = None,
    ilvl: int = 0,
    comment_range: tuple = None,
) -> str:
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if num_id:
        ppr += f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/></w:numPr>'
    ppr_xml = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    if comment_range is not None:
        start_id, end_id = comment_range
        runs = (
            f'<w:commentRangeStart w:id="{start_id}"/>'
            + runs
            + f'<w:commentRangeEnd w:id="{end_id}"/>'
            + f'<w:r><w:commentReference w:id="{end_id}"/></w:r>'
        )
    return f"<w:p>{ppr_xml}{runs}</w:p>"


def _table_xml(rows) -> str:
    body = ""
    for row in rows:
        cells = "".join(
            f"<w:tc><w:p>{_run_xml(cell)}</w:p></w:tc>" for cell in row
        )
        body += f"<w:tr>{cells}</w:tr>"
    return f"<w:tbl>{body}</w:tbl>"


def _numbering_decimal_xml() -> str:
    return (
        f'<w:numbering {DOCX_NS_DECL}>'
        '<w:abstractNum w:abstractNumId="0">'
        '<w:lvl w:ilvl="0">'
        '<w:start w:val="1"/>'
        '<w:numFmt w:val="decimal"/>'
        '<w:lvlText w:val="%1."/>'
        "</w:lvl>"
        "</w:abstractNum>"
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
        "</w:numbering>"
    )


def _comments_xml(comments) -> str:
    body = ""
    for comment_id, author, content in comments:
        body += (
            f'<w:comment w:id="{comment_id}" w:author="{author}" w:initials="{author[:1]}"'
            ' w:date="2026-01-01T00:00:00Z">'
            f"<w:p>{_run_xml(content)}</w:p>"
            "</w:comment>"
        )
    return f"<w:comments {DOCX_NS_DECL}>{body}</w:comments>"


def _build_docx_zip(document_body: str, comments_xml: str = None, numbering_xml: str = None) -> bytes:
    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {DOCX_NS_DECL}><w:body>{document_body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", document_xml)
        if comments_xml is not None:
            zf.writestr("word/comments.xml", comments_xml)
        if numbering_xml is not None:
            zf.writestr("word/numbering.xml", numbering_xml)
    return buffer.getvalue()


def test_parse_markdown_dispatch():
    raw = "# Title\n\nFirst paragraph.\n\n- item one\n- item two\n".encode("utf-8")
    payload = parse_document_payload("spec.md", raw)
    assert payload["source_ext"] == ".md"
    assert payload["source_mime"] == "text/markdown"
    assert payload["render_json"]["format"] == "markdown"
    types = [block["type"] for block in payload["blocks_json"]]
    assert types == ["heading", "paragraph", "list_item", "list_item"]
    assert payload["blocks_json"][0]["meta"]["level"] == 1
    assert payload["blocks_json"][2]["meta"]["marker"] == "-"


def test_parse_txt_merges_wrapped_lines():
    raw = "line one\nline two\n\nline three\n".encode("utf-8")
    payload = parse_document_payload("notes.txt", raw)
    assert payload["source_ext"] == ".txt"
    texts = [block["text"] for block in payload["blocks_json"]]
    assert texts == ["line one line two", "line three"]


def test_parse_pdf_returns_empty_payload():
    payload = parse_document_payload("doc.pdf", b"%PDF-1.4 fake")
    assert payload["normalized_markdown"] == ""
    assert payload["blocks_json"] == []
    assert payload["render_json"] == {"format": "markdown", "block_count": 0}


def test_can_inline_review_extensions():
    assert can_inline_review(".md")
    assert can_inline_review(".DOCX")
    assert not can_inline_review(".pdf")
    assert not can_inline_review(None)


def test_looks_like_docx_bytes():
    assert not looks_like_docx_bytes(b"PK\x03\x04 junk")
    assert not looks_like_docx_bytes(b"")
    assert not looks_like_docx_bytes(None)
    docx_bytes = _build_docx_zip(_para_xml(_run_xml("hello")))
    assert looks_like_docx_bytes(docx_bytes)


def test_parse_docx_headings_and_numbered_lists():
    body = "".join(
        [
            _para_xml(_run_xml("Doc Title"), style="Heading1"),
            _para_xml(_run_xml("first item"), num_id="1", ilvl=0),
            _para_xml(_run_xml("second item"), num_id="1", ilvl=0),
            _para_xml(_run_xml("plain text")),
        ]
    )
    payload = parse_docx_payload(_build_docx_zip(body, numbering_xml=_numbering_decimal_xml()))

    blocks = payload["blocks_json"]
    assert [block["type"] for block in blocks] == ["heading", "list_item", "list_item", "paragraph"]
    assert blocks[0]["meta"]["level"] == 1
    assert blocks[1]["meta"]["marker"] == "1."
    assert blocks[2]["meta"]["marker"] == "2."
    assert blocks[3]["runs"] == [{"text": "plain text"}]
    assert payload["render_json"]["format"] == "rich_doc"
    assert payload["render_json"]["features"]["runs"] is True
    assert "# Doc Title" in payload["normalized_markdown"]
    assert "1. first item" in payload["normalized_markdown"]


def test_parse_docx_bold_runs_and_markdown():
    body = _para_xml(_run_xml("bold part", bold=True) + _run_xml(" and normal"))
    payload = parse_docx_payload(_build_docx_zip(body))
    runs = payload["blocks_json"][0]["runs"]
    assert runs == [
        {"text": "bold part", "bold": True},
        {"text": " and normal"},
    ]


def test_parse_docx_comments_anchor_offsets():
    runs = (
        _run_xml("review ")
        + '<w:commentRangeStart w:id="1"/>'
        + _run_xml("this part")
        + '<w:commentRangeEnd w:id="1"/>'
        + '<w:r><w:commentReference w:id="1"/></w:r>'
    )
    payload = parse_docx_payload(
        _build_docx_zip(_para_xml(runs), comments_xml=_comments_xml([(1, "Alice", "please fix")]))
    )
    comments = payload["render_json"]["docx_comments"]
    assert len(comments) == 1
    comment = comments[0]
    assert comment["author"] == "Alice"
    assert comment["content"] == "please fix"
    assert comment["block_id"] == "blk-1"
    text = payload["blocks_json"][0]["text"]
    assert text[comment["char_start"]:comment["char_end"]] == "this part"


def test_parse_docx_table_block_and_markdown():
    body = _table_xml([["Name", "Value"], ["alpha", "1"]])
    payload = parse_docx_payload(_build_docx_zip(body))
    blocks = payload["blocks_json"]
    assert len(blocks) == 1
    assert blocks[0]["type"] == "table"
    assert blocks[0]["meta"]["row_count"] == 2
    assert blocks[0]["meta"]["column_count"] == 2
    assert payload["normalized_markdown"].startswith("| Name | Value |")


def test_build_docx_bytes_roundtrip():
    markdown = "# Spec Title\n\nBody paragraph.\n\n- bullet one\n"
    blocks = markdown_blocks.markdown_to_blocks(markdown)
    docx_bytes = build_docx_bytes(blocks, markdown)
    assert docx_bytes and looks_like_docx_bytes(docx_bytes)

    payload = parse_document_payload("rebuilt.docx", docx_bytes)
    assert payload["render_json"]["format"] == "rich_doc"
    rebuilt = payload["blocks_json"]
    assert rebuilt[0]["type"] == "heading"
    assert rebuilt[0]["text"] == "Spec Title"
    assert any(block["type"] == "list_item" for block in rebuilt)


def test_build_docx_bytes_fallback_minimal_zip():
    docx_bytes = build_docx_bytes([], "plain fallback text")
    assert docx_bytes and looks_like_docx_bytes(docx_bytes)
    payload = parse_document_payload("fallback.docx", docx_bytes)
    assert "plain fallback text" in payload["normalized_markdown"]
