"""SPEC 上传策略:.doc 与 PDF 拒绝。"""

import os

import pytest

from app.domains.task.models.task_cli_bootstrap import SddTaskCliBootstrap
from app.domains.task.services.task_workspace import specification as task_task_workspace_specification
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session


def test_upload_task_spec_rejects_doc(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _ws, task = _seed_workspace(db)
            task.project_path = str(tmp_path)
            db.commit()
            with pytest.raises(ValueError, match=r"\.doc"):
                task_task_workspace_specification.upload_task_spec(db, task.id, "spec.doc", b"legacy")
            # 不应留下任何文件/资产
            assert not os.path.exists(os.path.join(tmp_path, ".sdd", "spec", "spec.doc"))
    finally:
        engine.dispose()


def test_upload_task_spec_rejects_pdf(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _ws, task = _seed_workspace(db)
            task.project_path = str(tmp_path)
            db.commit()
            with pytest.raises(ValueError, match=r"supported formats"):
                task_task_workspace_specification.upload_task_spec(db, task.id, "spec.pdf", b"%PDF-1.4 fake")
            # 不应留下任何文件/资产，也不应创建基线
            assert not os.path.exists(os.path.join(tmp_path, ".sdd", "spec", "spec.pdf"))
            assert db.query(SddTaskCliBootstrap).filter_by(task_id=task.id).first() is None
    finally:
        engine.dispose()


def test_failed_upload_preserves_previous_task_document(tmp_path, monkeypatch):
    from pathlib import Path

    from app.domains.asset.models.asset import SddAssetVersion
    from app.domains.asset.services import asset_discussion_service

    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _ws, task = _seed_workspace(db)
            task.project_path = str(tmp_path)
            db.commit()
            path, _asset_id, _version_id = task_task_workspace_specification.upload_task_spec(
                db, task.id, "spec.md", b"# Committed\n"
            )

            def reject_comments(*_args, **_kwargs):
                raise RuntimeError("comment import failed")

            monkeypatch.setattr(asset_discussion_service, "sync_docx_comments_to_threads", reject_comments)
            with pytest.raises(RuntimeError, match="comment import failed"):
                task_task_workspace_specification.upload_task_spec(db, task.id, "spec.md", b"# Failed upload\n")
            db.rollback()
            assert task.spec_doc_path == path
            assert Path(path).read_bytes() == b"# Committed\n"
            assert db.query(SddAssetVersion).count() == 1
            assert list((tmp_path / ".sdd" / "assets").rglob("spec.md")) == [Path(path)]
    finally:
        engine.dispose()


def test_serialize_asset_includes_source_ext():
    from datetime import datetime

    from app.domains.asset.models.asset import AssetType, SddAsset
    from app.domains.asset.services.document.serializer import serialize_asset

    asset = SddAsset(
        id="a-1",
        task_id="t",
        workspace_id="ws",
        creator_id="u",
        asset_type=AssetType.SPEC,
        name="spec.pdf",
        source_ext=".pdf",
        source_mime="application/pdf",
        created_at=datetime(2026, 1, 1),
    )
    payload = serialize_asset(asset)
    assert payload.source_ext == ".pdf"
    assert payload.source_mime == "application/pdf"
