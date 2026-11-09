import pytest
from sqlalchemy.orm import sessionmaker

from app.agents import current_agent_attempt
from app.agents.errors import AgentCancelledError
from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.ai.services.jobs import attempts, domain_jobs
from app.domains.api_mock.models.api_mock import (
    SddApiMockJob,
    SddApiMockProject,
    SddApiMockRule,
    SddApiMockSourceVersion,
)
from app.domains.api_mock.services.api_mock import auto_mock_service, cli_sync_service, job_service
from tests.ai.jobs.domain_job_test_utils import bound_domain_attempt
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
    monkeypatch.setattr(job_service, "SessionLocal", sessionmaker(bind=db.get_bind(), autoflush=False))
    if kind != "provider_cancel":
        job_service.request_job_cancel(db, project.id, job_id)
    else:
        monkeypatch.setattr(auto_mock_service, "resolve_workspace_backend", lambda *_args: "opencode")

        async def cancelled_provider(*_args, **_kwargs):
            job_service.request_job_cancel(db, project.id, job_id)
            raise job_service.JobCancelledError("Provider stopped after cancellation")

        monkeypatch.setattr(auto_mock_service, "run_domain_turn", cancelled_provider)
    with bound_domain_attempt(db, job_id):
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
        except AgentCancelledError:
            pass
        assert domain_jobs.begin_cancel_finalization(job_id)
        attempts.finish_termination_sync(
            job_id, current_agent_attempt().run_token, confirmed_dead=True, reason="USER_CANCEL", failure_code=None
        )
    try:
        db.expire_all()
        stored = db.get(SddApiMockJob, job_id)
        assert stored.status == AiJobStatus.CANCELLED
        assert stored.finished_at is not None and stored.progress == 100
        assert stored.execution.cancel_requested_at is not None
        assert job_service.list_jobs(db, project.id, active_only=True) == []
        assert db.query(SddApiMockRule).count() == 0
        assert db.query(SddApiMockSourceVersion).count() == versions
    finally:
        job_service._clear_cancel_event(job_id)
