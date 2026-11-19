import asyncio
import io
import zipfile
from codecs import BOM_UTF8
from types import SimpleNamespace

import pytest
from docx import Document

from app.agents.domain_tools.runtime import DomainTool, DomainToolError, DomainToolLookup, DomainToolRun
from app.domains.asset.schemas.revision import DocxRegionsReply, DocxRevisionRequest
from app.domains.asset.services.document.docx import parse_docx_payload
from app.domains.asset.services.review import native_revision
from app.protocols.schema import validate_schema


def test_source_hunks_keep_crlf_bom_unedited_spacing_and_unicode(tmp_path):
    source = "😀 标题\r\n\r\n  第一项 30\r\n\r\n  代码  \n\n审计 A\r\n"
    revised = "😀 标题\n\n  第一项 45\n\n  代码  \n\n审计 B\n"
    path = tmp_path / "source.md"
    path.write_bytes(BOM_UTF8 + source.encode())
    version = SimpleNamespace(original_path=str(path))
    revision = native_revision.build_text_revision(source, revised)
    changes = revision["changes"]
    assert [change["line"] for change in changes] == [3, 7]
    selection = native_revision.selected_changes(revision, [changes[0]["id"]])
    assert native_revision.render_text_revision(version, revision, selection) == (
        BOM_UTF8 + source.replace("30", "45").encode()
    )
    with pytest.raises(ValueError, match="duplicate or unknown"):
        native_revision.selected_changes(revision, ["unknown"])


def test_docx_exact_range_append_and_selection_preserve_original_package(tmp_path):
    path = tmp_path / "source.docx"
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Existing header"
    document.add_heading("Original heading", 1)
    paragraph = document.add_paragraph("Main ")
    paragraph.add_run("30").bold = True
    paragraph.add_run(" backup ")
    paragraph.add_run("30").italic = True
    document.add_paragraph("Remove me")
    document.save(path)
    before = path.read_bytes()
    version = SimpleNamespace(original_path=str(path), blocks_json=parse_docx_payload(before)["blocks_json"])
    replace = {"kind": "replace", "region_id": "blk-2", "old_text": "30", "new_text": "45"}
    ambiguous = DocxRevisionRequest(action="apply", changes=[replace], change_summary="Adjust main limit")
    with pytest.raises(ValueError, match="Repeated text"):
        native_revision.build_docx_revision(version, ambiguous)
    request = DocxRevisionRequest(
        action="apply",
        changes=[
            {**replace, "start": 5},
            {"kind": "replace", "region_id": "blk-3", "old_text": "Remove me", "new_text": ""},
            {"kind": "append", "title": "Appended heading", "level": 1, "paragraphs": ["Appended body"]},
        ],
        change_summary="Update the original and add a section",
    )
    revision = native_revision.build_docx_revision(version, request)
    _, _, all_markers = native_revision.render_docx_revision(version, revision["changes"], preview=True)
    deleted = next(marker for marker in all_markers if marker["id"] == "docx-2")
    assert deleted["start"] == deleted["end"] == 0
    selected = native_revision.selected_changes(revision, ["docx-1", "docx-3"])
    after, _, markers = native_revision.render_docx_revision(version, selected, preview=True)
    original_zip, updated_zip = (zipfile.ZipFile(io.BytesIO(content)) for content in (before, after))
    with original_zip, updated_zip:
        assert original_zip.namelist() == updated_zip.namelist()
        assert all(
            original_zip.read(name) == updated_zip.read(name)
            for name in original_zip.namelist()
            if name != "word/document.xml"
        )
    result = Document(io.BytesIO(after))
    assert result.paragraphs[1].text == "Main 45 backup 30"
    assert result.paragraphs[1].runs[1].bold and result.paragraphs[1].runs[3].italic
    assert result.paragraphs[2].text == "Remove me"
    assert result.paragraphs[-2].style.name == "Heading 1"
    assert result.paragraphs[-1].text == "Appended body"
    assert {marker["id"] for marker in markers} == {"docx-1", "docx-3"}
    assert path.read_bytes() == before


def test_one_document_tool_can_read_before_terminal_apply():
    def lookup(value):
        return DocxRegionsReply(regions=[], more_matches=False) if value.action == "read" else None

    tool = DomainTool(
        "docx_revision",
        "Read or apply",
        DocxRevisionRequest,
        lookup=DomainToolLookup(DocxRegionsReply, lookup),
    )
    run = DomainToolRun(tool)

    async def exercise():
        reply = await run.invoke("docx_revision", {"action": "read", "query": "target"}, "read")
        validate_schema(tool.definition().output_schema, reply.data)
        assert reply.data["kind"] == "docx_regions"
        with pytest.raises(DomainToolError, match="DOMAIN_RESULT_MISSING"):
            run.require_result()
        reply = await run.invoke("docx_revision", {"action": "apply", "change_summary": "Unchanged"}, "apply")
        validate_schema(tool.definition().output_schema, reply.data)
        assert reply.data["kind"] == "accepted"
        assert run.require_result().action == "apply"

    asyncio.run(exercise())
