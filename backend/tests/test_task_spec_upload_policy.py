"""SPEC 上传策略:.doc 拒绝、PDF 跳过基线。"""

import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import pytest  # noqa: E402

from app.domains.task.models.task_cli_bootstrap import SddTaskCliBootstrap  # noqa: E402
from app.domains.task.services import task_service  # noqa: E402
from test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


def test_upload_task_spec_rejects_doc(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _ws, task = _seed_workspace(db)
            task.project_path = str(tmp_path)
            db.commit()
            with pytest.raises(ValueError, match=r"\.doc"):
                task_service.upload_task_spec(db, task.id, "spec.doc", b"legacy")
            # 不应留下任何文件/资产
            assert not os.path.exists(os.path.join(tmp_path, ".sdd", "spec", "spec.doc"))
    finally:
        engine.dispose()


def test_upload_task_spec_accepts_pdf_and_stores_original(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _ws, task = _seed_workspace(db)
            task.project_path = str(tmp_path)
            db.commit()
            _path, asset_id, version_id = task_service.upload_task_spec(
                db, task.id, "spec.pdf", b"%PDF-1.4 fake"
            )
            from app.domains.asset.services.document.repository import get_asset_version
            version = get_asset_version(db, asset_id, version_id)
            assert version.original_ext == ".pdf"
            assert os.path.isfile(version.original_path)
            # 服务层不建基线(基线由路由层按策略决定)
            assert db.query(SddTaskCliBootstrap).filter_by(task_id=task.id).first() is None
    finally:
        engine.dispose()


def test_spec_bootstrap_enabled_for_ext():
    assert task_service.spec_bootstrap_enabled_for_ext(".docx") is True
    assert task_service.spec_bootstrap_enabled_for_ext(".md") is True
    assert task_service.spec_bootstrap_enabled_for_ext(".txt") is True
    assert task_service.spec_bootstrap_enabled_for_ext(".pdf") is False


def test_serialize_asset_includes_source_ext():
    from datetime import datetime

    from app.domains.asset.models.asset import AssetType, SddAsset
    from app.domains.asset.services.document.serializer import serialize_asset

    asset = SddAsset(
        id="a-1", task_id="t", workspace_id="ws", creator_id="u",
        asset_type=AssetType.SPEC, name="spec.pdf",
        source_ext=".pdf", source_mime="application/pdf",
        created_at=datetime(2026, 1, 1),
    )
    payload = serialize_asset(asset)
    assert payload.source_ext == ".pdf"
    assert payload.source_mime == "application/pdf"
