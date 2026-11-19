"""
人工编辑（manual_edit_block）服务层测试。

覆盖：段落/标题块编辑生成新版本、样式继承、空文本与未知块/表格拦截、
并发版本校验、thread 锚点重映射与 close_hint 对账、DOCX 原位编辑。
"""

from base64 import b64decode
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.domains.asset.models.asset import (
    SddAssetVersion,
)
from app.domains.asset.services import (
    asset_discussion_service,
)
from app.domains.asset.services.asset_resolution_service import (
    ResolutionServiceError,
    manual_edit_block,
)
from app.domains.asset.services.document.versioning import (
    create_asset_version_from_normalized_content,
    create_asset_version_from_upload,
)
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session

SPEC_MD = "# Requirement\n\nLogin must work.\n\n- item one\n\nSecond paragraph.\n"


def _seed_task_with_project(db, tmp_path, workspace_id="ws-manual", task_id="task-manual"):
    _user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.project_path = str(tmp_path)
    db.commit()
    return workspace, task


def _seed_spec(db, task, tmp_path, markdown=SPEC_MD):
    asset, version = create_asset_version_from_upload(
        db, task, creator_id=task.creator_id, file_name="spec.md", file_content=markdown.encode("utf-8")
    )
    return asset, version


def _block_text(version, block_id):
    for block in version.blocks_json or []:
        if str(block.get("id")) == str(block_id):
            return str(block.get("text") or "")
    return None


def test_manual_edit_paragraph_creates_new_version(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, v1 = _seed_spec(db, task, tmp_path)

            version, affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-2",
                new_text="Login must work with SSO.",
                actor_user_id=task.creator_id,
                change_note="manual fix",
            )

            assert version.version_no == 2
            assert version.base_version_id == v1.id
            assert affected == []
            assert asset.active_version_id == version.id
            assert version.change_note == "manual fix"
            assert _block_text(version, "blk-2") == "Login must work with SSO."

            # 其他块保持不变，id/type/meta/order 不变
            v1_blocks = {b["id"]: b for b in v1.blocks_json}
            v2_blocks = {b["id"]: b for b in version.blocks_json}
            assert set(v1_blocks.keys()) == set(v2_blocks.keys())
            for block_id, old_block in v1_blocks.items():
                new_block = v2_blocks[block_id]
                if block_id == "blk-2":
                    assert new_block["type"] == old_block["type"]
                    assert new_block["order"] == old_block["order"]
                    continue
                assert new_block["text"] == old_block["text"]

            # runs 为单 run 且继承首 run 样式（旧块无样式 run，样式为空 dict）
            target = v2_blocks["blk-2"]
            assert len(target["runs"]) == 1
            assert target["runs"][0]["text"] == "Login must work with SSO."

            # markdown 与磁盘文件更新
            assert "Login must work with SSO." in version.normalized_markdown
            with open(version.original_path, "rb") as f:
                assert b"Login must work with SSO." in f.read()
    finally:
        engine.dispose()


def test_manual_edit_heading_keeps_markdown_prefix(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, _v1 = _seed_spec(db, task, tmp_path)

            version, _affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-1",
                new_text="Requirement v2",
                actor_user_id=task.creator_id,
            )

            assert version.blocks_json[0]["type"] == "heading"
            assert version.normalized_markdown.startswith("# Requirement v2")
    finally:
        engine.dispose()


def test_manual_edit_empty_text_rejected(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, _v1 = _seed_spec(db, task, tmp_path)

            try:
                manual_edit_block(
                    db,
                    asset=asset,
                    block_id="blk-2",
                    new_text="   ",
                    actor_user_id=task.creator_id,
                )
                raise AssertionError("expected ResolutionServiceError")
            except ResolutionServiceError as exc:
                assert exc.status_code == 422
    finally:
        engine.dispose()


def test_manual_edit_unknown_block_rejected(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, _v1 = _seed_spec(db, task, tmp_path)

            try:
                manual_edit_block(
                    db,
                    asset=asset,
                    block_id="blk-999",
                    new_text="whatever",
                    actor_user_id=task.creator_id,
                )
                raise AssertionError("expected ResolutionServiceError")
            except ResolutionServiceError as exc:
                assert exc.status_code == 404
    finally:
        engine.dispose()


def test_manual_edit_stale_context_version_rejected(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, v1 = _seed_spec(db, task, tmp_path)

            # 产生 v2，使 v1 成为历史版本
            create_asset_version_from_normalized_content(
                db,
                asset,
                creator_id=task.creator_id,
                normalized_markdown="# Requirement\n\nUpdated.\n",
                change_note="bump",
            )

            try:
                manual_edit_block(
                    db,
                    asset=asset,
                    block_id="blk-2",
                    new_text="stale edit",
                    actor_user_id=task.creator_id,
                    context_version_id=v1.id,
                )
                raise AssertionError("expected ResolutionServiceError")
            except ResolutionServiceError as exc:
                assert exc.status_code == 409
    finally:
        engine.dispose()


def test_manual_edit_remaps_thread_anchor_when_selection_kept(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, v1 = _seed_spec(db, task, tmp_path)

            thread = asset_discussion_service.create_thread(
                db,
                asset=asset,
                version=v1,
                creator_id=task.creator_id,
                block_id="blk-2",
                body="please clarify",
                selected_text="must work",
                char_start=6,
                char_end=15,
            )
            db.commit()

            version, affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-2",
                new_text="Login must work with SSO.",
                actor_user_id=task.creator_id,
            )

            assert [t.id for t in affected] == [thread.id]
            mapping = asset_discussion_service.get_thread_anchor_mapping(db, thread_id=thread.id, version_id=version.id)
            assert mapping is not None
            assert mapping.selected_text == "must work"
            new_text = _block_text(version, "blk-2")
            assert new_text[mapping.char_start : mapping.char_end] == "must work"

            anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
                db, thread=thread, context_version=version
            )
            assert anchor_eval["anchor_status"] == "valid"
            assert thread.close_hint_state in (None, "", "none")
    finally:
        engine.dispose()


def test_manual_edit_drops_anchor_selection_when_deleted(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, v1 = _seed_spec(db, task, tmp_path)

            thread = asset_discussion_service.create_thread(
                db,
                asset=asset,
                version=v1,
                creator_id=task.creator_id,
                block_id="blk-2",
                body="please clarify",
                selected_text="must work",
                char_start=6,
                char_end=15,
            )
            db.commit()

            version, affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-2",
                new_text="Login flow changed.",
                actor_user_id=task.creator_id,
            )

            assert [t.id for t in affected] == [thread.id]
            mapping = asset_discussion_service.get_thread_anchor_mapping(db, thread_id=thread.id, version_id=version.id)
            assert mapping is not None
            assert not mapping.selected_text
            assert mapping.char_start is None
            assert mapping.char_end is None

            # 块级锚点仍然有效（block 未消失）
            anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
                db, thread=thread, context_version=version
            )
            assert anchor_eval["anchor_status"] == "valid"
    finally:
        engine.dispose()


def test_manual_edit_skips_threads_on_other_blocks(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, v1 = _seed_spec(db, task, tmp_path)

            thread = asset_discussion_service.create_thread(
                db,
                asset=asset,
                version=v1,
                creator_id=task.creator_id,
                block_id="blk-1",
                body="heading comment",
            )
            db.commit()

            version, affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-2",
                new_text="Login must work with SSO.",
                actor_user_id=task.creator_id,
            )

            assert affected == []
            assert (
                asset_discussion_service.get_thread_anchor_mapping(db, thread_id=thread.id, version_id=version.id)
                is None
            )
    finally:
        engine.dispose()


def test_manual_edit_restores_missing_anchor_clears_close_hint(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, v1 = _seed_spec(db, task, tmp_path)

            thread = asset_discussion_service.create_thread(
                db,
                asset=asset,
                version=v1,
                creator_id=task.creator_id,
                block_id="blk-4",
                body="about second paragraph",
            )
            # 模拟历史版本演进后选区词失效 → anchor missing
            thread.selected_text = "Third paragraph."
            thread.char_start = 0
            thread.char_end = 17
            asset_discussion_service.set_thread_close_hint(
                db, thread=thread, state="pending", reason="anchor_missing", version_id=v1.id
            )
            db.commit()
            assert (
                asset_discussion_service.resolve_thread_anchor_for_version(db, thread=thread, context_version=v1)[
                    "anchor_status"
                ]
                == "missing"
            )

            version, affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-4",
                new_text="Second paragraph. Third paragraph.",
                actor_user_id=task.creator_id,
            )

            assert [t.id for t in affected] == [thread.id]
            # 编辑后选区词重新出现在新文本中，锚点恢复 valid，close_hint 被清
            anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
                db, thread=thread, context_version=version
            )
            assert anchor_eval["anchor_status"] == "valid"
            assert str(thread.close_hint_state or "") == "none"
            assert thread.close_hint_reason is None
    finally:
        engine.dispose()


def test_manual_edit_preserves_original_docx_parts_and_paragraph_styles(tmp_path):
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Requirement header"
    document.sections[0].footer.paragraphs[0].text = "Requirement footer"
    document.add_paragraph("Repeated words")
    document.add_paragraph()  # Source paragraph ordinals also count blank paragraphs.
    paragraph = document.add_paragraph(style="List Number")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(16)
    heading = paragraph.add_run("  Deadline: ")
    heading.bold = True
    heading.font.color.rgb = RGBColor.from_string("8F2020")
    paragraph.add_run("700 ms").italic = True
    paragraph.add_run().add_tab()
    paragraph.add_run("Reject on timeout").underline = True
    image = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X9V0AAAAASUVORK5CYII=")
    paragraph.add_run().add_picture(BytesIO(image))
    paragraph.add_run().add_break(WD_BREAK.LINE)
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), "audit")
    link.append(paragraph.add_run("Audit record")._r)
    paragraph._p.append(link)
    paragraph.add_run().add_break(WD_BREAK.PAGE)
    paragraph.add_run("Continued")
    document.add_heading("Appendix", level=1)
    table = document.add_table(rows=2, cols=2)
    table.style = "Light Shading Accent 1"
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Merged heading"
    original = BytesIO()
    document.save(original)

    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, docx_version = create_asset_version_from_upload(
                db,
                task,
                creator_id=task.creator_id,
                file_name="spec.docx",
                file_content=original.getvalue(),
            )
            db.commit()

            edited_text = "  Deadline: 950 ms\tReject on timeout\nAudit record\nContinued"
            version, _affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-2",
                new_text=edited_text,
                actor_user_id=task.creator_id,
            )

            assert version.version_no == docx_version.version_no + 1
            assert _block_text(version, "blk-2") == edited_text
            assert version.blocks_json[1]["docx_spans"][0]["paragraph"] == 2
            assert Path(docx_version.original_path).read_bytes() == original.getvalue()
            with ZipFile(original) as source, ZipFile(version.original_path) as result:
                assert set(source.namelist()) == set(result.namelist())
                for part in source.namelist():
                    if part != "word/document.xml":
                        assert result.read(part) == source.read(part), part

            saved = Document(version.original_path)
            edited = saved.paragraphs[2]
            assert saved.paragraphs[0].text == "Repeated words"
            assert edited.style.name == "List Number"
            assert edited.alignment == WD_ALIGN_PARAGRAPH.CENTER
            assert edited.paragraph_format.space_after == Pt(16)
            assert edited.runs[0].bold and edited.runs[0].font.color.rgb == RGBColor.from_string("8F2020")
            assert edited.runs[1].text == "950 ms" and edited.runs[1].italic
            assert edited.runs[3].text == "Reject on timeout" and edited.runs[3].underline
            assert len(edited._p.xpath(".//w:drawing")) == 1
            assert len(edited._p.xpath('.//w:br[@w:type="page"]')) == 1
            assert edited._p.xpath('w:hyperlink[@w:anchor="audit"]/w:r/w:t')[0].text == "Audit record"

            db.commit()
            with pytest.raises(ResolutionServiceError, match="page or column break") as error:
                manual_edit_block(
                    db,
                    asset=asset,
                    block_id="blk-2",
                    new_text=edited_text.replace("\nContinued", " Continued"),
                    actor_user_id=task.creator_id,
                )
            assert error.value.status_code == 422
            assert asset.active_version_id == version.id
            assert db.query(SddAssetVersion).filter_by(asset_id=asset.id).count() == 2
    finally:
        engine.dispose()


def test_manual_edit_table_block_rejected(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            markdown = "# T\n\n| a | b |\n"
            asset, _v1 = _seed_spec(db, task, tmp_path, markdown=markdown)

            # markdown_to_blocks 不产 table 块；直接注入一个 table 块模拟 docx 解析产物
            version_obj = db.query(SddAssetVersion).first()
            blocks = list(version_obj.blocks_json or [])
            blocks.append({"id": "blk-table", "type": "table", "text": "", "order": len(blocks) + 1, "table": {}})
            version_obj.blocks_json = blocks
            db.commit()

            try:
                manual_edit_block(
                    db,
                    asset=asset,
                    block_id="blk-table",
                    new_text="cell text",
                    actor_user_id=task.creator_id,
                )
                raise AssertionError("expected ResolutionServiceError")
            except ResolutionServiceError as exc:
                assert exc.status_code == 422
    finally:
        engine.dispose()
