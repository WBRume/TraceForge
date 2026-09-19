"""
人工编辑（manual_edit_block）服务层测试。

覆盖：段落/标题块编辑生成新版本、样式继承、空文本与未知块/表格拦截、
并发版本校验、thread 锚点重映射与 close_hint 对账、docx 重建。
"""

import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.asset.models.asset import (  # noqa: E402
    SddAsset,
    SddAssetThreadAnchorMapping,
    SddAssetVersion,
)
from app.domains.asset.services import asset_discussion_service  # noqa: E402
from app.domains.asset.services import asset_resolution_service  # noqa: E402
from app.domains.asset.services.asset_resolution_service import (  # noqa: E402
    ResolutionServiceError,
    manual_edit_block,
)
from app.domains.asset.services.document.docx import looks_like_docx_bytes  # noqa: E402
from app.domains.asset.services.document.versioning import (  # noqa: E402
    create_asset_version_from_normalized_content,
    create_asset_version_from_upload,
)
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


SPEC_MD = (
    "# Requirement\n"
    "\n"
    "Login must work.\n"
    "\n"
    "- item one\n"
    "\n"
    "Second paragraph.\n"
)


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
            mapping = asset_discussion_service.get_thread_anchor_mapping(
                db, thread_id=thread.id, version_id=version.id
            )
            assert mapping is not None
            assert mapping.selected_text == "must work"
            new_text = _block_text(version, "blk-2")
            assert new_text[mapping.char_start:mapping.char_end] == "must work"

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
            mapping = asset_discussion_service.get_thread_anchor_mapping(
                db, thread_id=thread.id, version_id=version.id
            )
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
                asset_discussion_service.get_thread_anchor_mapping(
                    db, thread_id=thread.id, version_id=version.id
                )
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
                asset_discussion_service.resolve_thread_anchor_for_version(
                    db, thread=thread, context_version=v1
                )["anchor_status"]
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


def test_manual_edit_rebuilds_docx_for_docx_asset(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, _v1 = _seed_spec(db, task, tmp_path)

            docx_version = create_asset_version_from_normalized_content(
                db,
                asset,
                creator_id=task.creator_id,
                normalized_markdown=SPEC_MD,
                change_note="convert to docx",
                output_ext=".docx",
                output_file_name="spec-export.docx",
            )
            db.commit()

            version, _affected = manual_edit_block(
                db,
                asset=asset,
                block_id="blk-2",
                new_text="Login must work with SSO.",
                actor_user_id=task.creator_id,
            )

            assert version.version_no == docx_version.version_no + 1
            with open(version.original_path, "rb") as f:
                assert looks_like_docx_bytes(f.read())
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
