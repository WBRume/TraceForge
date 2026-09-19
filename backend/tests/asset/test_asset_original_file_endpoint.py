# backend/tests/test_asset_original_file_endpoint.py
"""GET /workspaces/{ws}/assets/{asset}/file 原文件下载端点。"""

import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import get_current_user, get_db  # noqa: E402
from app.domains.asset.models.asset import AssetType, SddAsset, SddAssetVersion  # noqa: E402
from app.domains.asset.routers import asset as asset_router_module  # noqa: E402
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


def _seed_pdf_asset(db, tmp_path):
    _user, _ws, task = _seed_workspace(db)
    task.project_path = str(tmp_path)
    pdf_path = tmp_path / "spec.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test-bytes")
    asset = SddAsset(
        task_id=task.id, workspace_id=task.workspace_id, creator_id=task.creator_id,
        asset_type=AssetType.SPEC, name="spec.pdf",
        source_file_name="spec.pdf", source_ext=".pdf", source_mime="application/pdf",
    )
    db.add(asset)
    db.flush()
    version = SddAssetVersion(
        asset_id=asset.id, version_no=1, original_path=str(pdf_path),
        original_ext=".pdf", original_mime="application/pdf",
        normalized_markdown="", blocks_json=[], render_json={"format": "markdown", "block_count": 0},
        created_by=task.creator_id,
    )
    db.add(version)
    db.commit()
    return task, asset, version


def _build_client(db):
    from app.domains.auth.models.user import User

    app = FastAPI()
    app.include_router(asset_router_module.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    user = db.query(User).filter_by(id="user-1").first()
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_download_original_file_streams_bytes(tmp_path):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            task, asset, version = _seed_pdf_asset(db, tmp_path)
            client = _build_client(db)

            resp = client.get(f"/api/workspaces/{task.workspace_id}/assets/{asset.id}/file")
            assert resp.status_code == 200
            assert resp.content == b"%PDF-1.4 test-bytes"
            assert resp.headers["content-type"].startswith("application/pdf")

            # 指定 version_id
            resp2 = client.get(
                f"/api/workspaces/{task.workspace_id}/assets/{asset.id}/file?version_id={version.id}"
            )
            assert resp2.status_code == 200

            # 不存在的资产
            resp3 = client.get(f"/api/workspaces/{task.workspace_id}/assets/no-such/file")
            assert resp3.status_code == 404
    finally:
        engine.dispose()
