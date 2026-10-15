import pytest

from app.domains.api_mock.models.api_mock import (
    ApiMockJobStatus,
    SddApiMockJob,
    SddApiMockProject,
    SddApiMockRule,
    SddApiMockSourceVersion,
)
from app.domains.api_mock.services.api_mock import auto_mock_service, cli_sync_service, job_service
from tests.api_mock.test_api_mock_editor_routes import editor as editor_fixture
from tests.api_mock.test_api_mock_editor_routes import endpoint

editor = editor_fixture


@pytest.mark.parametrize("kind", ["auto", "import", "sync", "provider_cancel"])
def test_cancelled_worker_persists_terminal_state_without_partial_outputs(editor, db, monkeypatch, kind):
    client, _ = editor
    ep = endpoint(client)
    project = db.get(SddApiMockProject, "p")
    monkeypatch.setattr(job_service, "_broadcast_job_state", lambda *_args, **_kwargs: None)
    job = job_service.create_job(db, project, creator_id="u", job_type="AUTO_GENERATE_MOCK_CASES")
    job_id = job.id
    versions = db.query(SddApiMockSourceVersion).count()
    job.status = ApiMockJobStatus.RUNNING
    db.commit()
    if kind != "provider_cancel":
        job_service.request_job_cancel(db, project.id, job_id)
    else:
        monkeypatch.setattr(auto_mock_service, "resolve_workspace_backend", lambda *_args: "opencode")

        async def cancelled_provider(*_args, **_kwargs):
            job_service.request_job_cancel(db, project.id, job_id)
            raise job_service.JobCancelledError("Provider stopped after cancellation")

        monkeypatch.setattr(auto_mock_service, "run_agent_session", cancelled_provider)
    try:
        if kind in {"auto", "provider_cancel"}:
            auto_mock_service.auto_generate_mock_cases_for_endpoint(
                db, project, job_id=job_id, endpoint_id=ep["id"], creator_id="u", workspace_sync_needed=False
            )
        elif kind == "import":
            cli_sync_service.run_import_job_internal(
                db,
                project,
                job_id=job_id,
                source_name="cancel.json",
                source_url=None,
                raw_content="{}",
                creator_id="u",
            )
        else:
            cli_sync_service.analyze_workspace_and_sync(db, project, job_id=job_id, creator_id="u")
        db.expire_all()
        stored = db.get(SddApiMockJob, job_id)
        assert stored.status == ApiMockJobStatus.FAILED
        assert stored.finished_at is not None and stored.progress == 100
        assert stored.result_json["cancel_requested"] is True
        assert stored.result_json["cancelled"] is True
        assert job_service.list_jobs(db, project.id, active_only=True) == []
        assert db.query(SddApiMockRule).count() == 0
        assert db.query(SddApiMockSourceVersion).count() == versions
    finally:
        job_service._clear_cancel_event(job_id)
