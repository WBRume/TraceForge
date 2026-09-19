"""
文档版本工作流测试（document.versioning / document.repair）

覆盖：SPEC 上传 upsert 与版本递增、诊断文档上传复用与 CLI 副本、
产物类资产字节落盘、规范化内容出 docx、版本兜底与损坏修复。
"""

import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.asset.models.asset import AssetType, SddAsset, SddAssetVersion  # noqa: E402
from app.domains.asset.services.document.docx import looks_like_docx_bytes  # noqa: E402
from app.domains.asset.services.document.repair import repair_docx_version_if_needed  # noqa: E402
from app.domains.asset.services.document.versioning import (  # noqa: E402
    create_asset_version_from_normalized_content,
    create_asset_version_from_upload,
    create_diagnosis_doc_asset_version,
    create_task_asset_version_from_bytes,
    ensure_asset_has_version,
    ensure_spec_asset_backfilled,
)
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


SPEC_MD = "# Requirement\n\nLogin must work.\n".encode("utf-8")


def _seed_task_with_project(db, tmp_path, workspace_id="ws-docver", task_id="task-docver"):
    _user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.project_path = str(tmp_path)
    db.commit()
    return workspace, task


def test_create_asset_version_from_upload_upserts_spec_and_increments_versions(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)

            asset1, version1 = create_asset_version_from_upload(
                db, task, creator_id=task.creator_id, file_name="spec.md", file_content=SPEC_MD
            )
            assert asset1.asset_type == AssetType.SPEC
            assert version1.version_no == 1
            assert asset1.active_version_id == version1.id
            assert asset1.content_text.startswith("# Requirement")
            assert os.path.isfile(version1.original_path)
            with open(version1.original_path, "rb") as f:
                assert f.read() == SPEC_MD

            asset2, version2 = create_asset_version_from_upload(
                db, task, creator_id=task.creator_id, file_name="spec-v2.md", file_content=b"# Updated\n"
            )
            assert asset2.id == asset1.id
            assert version2.version_no == 2
            assert version2.base_version_id == version1.id
            assert asset2.active_version_id == version2.id
            assert asset2.content_text == "# Updated\n"

            assets = db.query(SddAsset).filter(SddAsset.task_id == task.id).all()
            assert len(assets) == 1
    finally:
        engine.dispose()


def test_create_diagnosis_doc_reuses_asset_by_name_and_writes_cli_copy(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)

            asset, version, cli_path = create_diagnosis_doc_asset_version(
                db, task, creator_id=task.creator_id, file_name="error log.txt", file_content=b"stack trace"
            )
            assert asset.asset_type == AssetType.DIAGNOSIS_DOC
            assert asset.name == "error_log.txt"
            assert version.version_no == 1
            assert cli_path == os.path.join(str(tmp_path), ".sdd", "diagnosis", "error_log.txt")
            assert os.path.isfile(cli_path)

            asset_again, version_again, _cli = create_diagnosis_doc_asset_version(
                db, task, creator_id=task.creator_id, file_name="error log.txt", file_content=b"stack trace v2"
            )
            assert asset_again.id == asset.id
            assert version_again.version_no == 2

            _asset_other, version_other, _cli2 = create_diagnosis_doc_asset_version(
                db, task, creator_id=task.creator_id, file_name="req.md", file_content=b"# req"
            )
            assert version_other.version_no == 1

            assets = db.query(SddAsset).filter(SddAsset.task_id == task.id).all()
            assert len(assets) == 2
    finally:
        engine.dispose()


def test_create_task_asset_version_from_bytes_stores_artifact(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)

            asset, version = create_task_asset_version_from_bytes(
                db,
                task,
                creator_id=task.creator_id,
                asset_type=AssetType.CODE_DIFF,
                asset_name="Diff #1",
                file_name="change.patch",
                file_content=b"diff --git a/x b/x",
                content_text="diff excerpt",
                change_note="unit test",
            )
            assert asset.asset_type == AssetType.CODE_DIFF
            assert asset.source_ext == ".patch"
            assert version.version_no == 1
            assert asset.active_version_id == version.id
            assert version.render_json["format"] == "artifact"
            assert version.render_json["size_bytes"] == len(b"diff --git a/x b/x")
            assert os.path.isfile(version.original_path)
    finally:
        engine.dispose()


def test_create_asset_version_from_normalized_content_rebuilds_docx(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, _v1 = create_asset_version_from_upload(
                db, task, creator_id=task.creator_id, file_name="spec.md", file_content=SPEC_MD
            )

            markdown = "# Rewritten\n\nNew content.\n"
            version = create_asset_version_from_normalized_content(
                db,
                asset,
                creator_id=task.creator_id,
                normalized_markdown=markdown,
                change_note="rewrite to docx",
                output_ext=".docx",
                output_file_name="spec-export.docx",
            )
            assert version.original_ext == ".docx"
            assert version.version_no == 2
            with open(version.original_path, "rb") as f:
                assert looks_like_docx_bytes(f.read())
            assert version.render_json["format"] == "rich_doc"
            assert version.blocks_json[0]["type"] == "heading"
            assert asset.content_text == version.normalized_markdown
    finally:
        engine.dispose()


def test_ensure_asset_has_version_activates_newest_version(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, v1 = create_asset_version_from_upload(
                db, task, creator_id=task.creator_id, file_name="spec.md", file_content=SPEC_MD
            )
            _asset, v2 = create_asset_version_from_upload(
                db, task, creator_id=task.creator_id, file_name="spec.md", file_content=b"# v2\n"
            )
            asset.active_version_id = None
            db.flush()

            resolved = ensure_asset_has_version(db, asset)
            assert resolved.id == v2.id
            assert asset.active_version_id == v2.id
            assert v1.id != v2.id
    finally:
        engine.dispose()


def test_ensure_asset_has_version_backfills_from_legacy_content(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset = SddAsset(
                task_id=task.id,
                workspace_id=task.workspace_id,
                creator_id=task.creator_id,
                asset_type=AssetType.SPEC,
                name="legacy-spec.md",
                content_text="# Legacy\n\nOld content.\n",
                source_file_name="legacy-spec.md",
                source_ext=".md",
                source_mime="text/markdown",
            )
            db.add(asset)
            db.flush()

            version = ensure_asset_has_version(db, asset)
            assert version is not None
            assert version.version_no == 1
            assert version.normalized_markdown.startswith("# Legacy")
            assert asset.active_version_id == version.id
            assert os.path.isfile(version.original_path)
    finally:
        engine.dispose()


def test_ensure_spec_asset_backfilled_from_task_spec_doc_path(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            spec_file = tmp_path / "task-spec.md"
            spec_file.write_bytes(SPEC_MD)
            task.spec_doc_path = str(spec_file)
            db.commit()

            asset = ensure_spec_asset_backfilled(db, task)
            assert asset is not None
            assert asset.asset_type == AssetType.SPEC
            assert asset.content_text.startswith("# Requirement")

            assert ensure_spec_asset_backfilled(db, task).id == asset.id
    finally:
        engine.dispose()


def test_repair_docx_version_if_needed_rebuilds_corrupt_version(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _ws, task = _seed_task_with_project(db, tmp_path)
            asset, _v1 = create_asset_version_from_upload(
                db, task, creator_id=task.creator_id, file_name="spec.md", file_content=SPEC_MD
            )

            corrupt_path = os.path.join(str(tmp_path), "corrupt.docx")
            with open(corrupt_path, "wb") as f:
                f.write(b"this is not a zip")
            version = SddAssetVersion(
                asset_id=asset.id,
                version_no=2,
                original_path=corrupt_path,
                original_ext=".docx",
                original_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                normalized_markdown="PK\x03\x04 broken dump",
                blocks_json=[{"type": "paragraph", "text": "recovered text", "order": 1}],
                render_json={"format": "markdown", "block_count": 1},
                created_by=task.creator_id,
            )
            db.add(version)
            db.flush()
            asset.active_version_id = version.id

            repaired = repair_docx_version_if_needed(db, asset, version)
            assert repaired is True
            assert version.render_json["format"] == "rich_doc"
            with open(version.original_path, "rb") as f:
                assert looks_like_docx_bytes(f.read())
            assert asset.content_json["block_count"] >= 1

            assert repair_docx_version_if_needed(db, asset, _v1) is False
    finally:
        engine.dispose()
