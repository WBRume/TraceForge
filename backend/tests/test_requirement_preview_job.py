import asyncio
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.workspace_asset.models.workspace_asset import (  # noqa: E402
    SddRequirementImportBatch,
)
from app.domains.workspace_asset.services import workspace_asset_service as service  # noqa: E402


def _build_session(*, expire_on_commit=False):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=expire_on_commit)


def _seed_workspace(db, project_path):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(
        id="ws-1",
        name="Workspace",
        owner_id=user.id,
        project_path=str(project_path),
    )
    db.add_all([user, workspace])
    db.commit()
    return workspace


def _create_preview_job(db, raw: bytes, *, file_name="requirements.md"):
    return service.create_requirement_import_preview_job(
        db,
        "ws-1",
        "user-1",
        file_name=file_name,
        raw=raw,
    )


def test_create_import_preview_job_persists_parsed_content(tmp_path):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)

    response = _create_preview_job(db, b"# Feature A\n\nBody text\n")

    job = db.query(SddAiJob).filter(SddAiJob.id == response.job_id).one()
    context = job.context_json
    assert job.queue_key == "REQUIREMENT_PREVIEW:ws-1"
    assert job.status == service.AiJobStatus.PENDING
    assert context["job_kind"] == "REQUIREMENT_IMPORT_PREVIEW"
    assert "Feature A" in str(context["normalized_markdown"])
    assert context["source_ext"] == ".md"
    assert context["source_mime"]
    assert context["render_json"]
    assert context["source_filename"] == "requirements.md"


def test_create_import_preview_job_rejects_unsupported_and_oversize(tmp_path):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)

    with pytest.raises(service.WorkspaceAssetWriteError) as unsupported:
        _create_preview_job(db, b"# x\n", file_name="requirements.pdf")
    assert unsupported.value.status_code == 415

    original_limit = service.REQUIREMENT_IMPORT_MAX_BYTES
    service.REQUIREMENT_IMPORT_MAX_BYTES = 10
    try:
        with pytest.raises(service.WorkspaceAssetWriteError) as oversize:
            _create_preview_job(db, b"# too large content beyond limit\n")
        assert oversize.value.status_code == 413
    finally:
        service.REQUIREMENT_IMPORT_MAX_BYTES = original_limit


def test_run_import_preview_job_executes_from_persisted_context(tmp_path, monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)
    response = _create_preview_job(db, b"# Feature A\n\nBody text\n")
    job_id = response.job_id

    prompts = []

    async def fake_cli(prompt, project_path, max_attempts=1, backend_name=None):
        prompts.append({"prompt": prompt, "project_path": project_path})
        return {
            "text": '{"items": [{"title": "Feature A", "body": "Body text", "acceptance_criteria": [], "source_ref": "r1"}]}',
            "session_id": "sess-1",
        }

    monkeypatch.setattr(service, "run_cli_single_turn", fake_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    asyncio.run(service.run_requirement_import_preview_job(job_id))

    db.expire_all()
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert job.status == service.AiJobStatus.SUCCESS
    assert len(prompts) == 1
    assert "Feature A" in prompts[0]["prompt"]

    batch = (
        db.query(SddRequirementImportBatch)
        .filter(SddRequirementImportBatch.workspace_id == "ws-1")
        .one()
    )
    assert batch.item_count == 1
    assert batch.source_metadata_json["ai_preview"] is True
    assert batch.source_metadata_json["session_id"] == "sess-1"
    assert "preview_batch_id" in (job.context_json or {})


def test_run_import_preview_job_fails_when_content_missing(tmp_path, monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)

    job = SddAiJob(
        id="legacy-job",
        workspace_id="ws-1",
        channel=service.AiJobChannel.ASSET_THREAD,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        status=service.AiJobStatus.PENDING,
        context_json={"job_kind": "REQUIREMENT_IMPORT_PREVIEW", "source_filename": "requirements.md"},
        creator_id="user-1",
    )
    db.add(job)
    db.commit()

    async def unexpected_cli(*_args, **_kwargs):
        raise AssertionError("CLI must not be called without persisted content")

    monkeypatch.setattr(service, "run_cli_single_turn", unexpected_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    asyncio.run(service.run_requirement_import_preview_job(job.id))

    db.expire_all()
    failed = db.query(SddAiJob).filter(SddAiJob.id == job.id).one()
    assert failed.status == service.AiJobStatus.FAILED
    assert "re-upload" in str(failed.error_message)


def test_execute_job_dispatches_split_preview(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, "G:/tmp/does-not-matter")

    job = SddAiJob(
        id="split-job-1",
        workspace_id="ws-1",
        channel=service.AiJobChannel.ASSET_THREAD,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        status=service.AiJobStatus.RUNNING,
        context_json={"job_kind": "REQUIREMENT_SPLIT_PREVIEW"},
        creator_id="user-1",
    )
    db.add(job)
    db.commit()

    calls = []

    class _FakePreviewService:
        @staticmethod
        async def run_requirement_split_preview_job(job_id):
            calls.append(job_id)

        @staticmethod
        async def run_requirement_import_preview_job(job_id):
            raise AssertionError("import runner must not be used for split jobs")

    from app.domains.ai.services import ai_job_service

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(
        service,
        "run_requirement_split_preview_job",
        _FakePreviewService.run_requirement_split_preview_job,
    )
    monkeypatch.setattr(
        service,
        "run_requirement_import_preview_job",
        _FakePreviewService.run_requirement_import_preview_job,
    )

    asyncio.run(ai_job_service._execute_job("split-job-1"))
    assert calls == ["split-job-1"]
