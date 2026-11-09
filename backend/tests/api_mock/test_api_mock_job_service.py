from datetime import datetime
from types import SimpleNamespace

from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.api_mock.models.api_mock import SddApiMockJob
from app.domains.api_mock.schemas.api_mock import ApiMockJobResponse
from app.domains.api_mock.services.api_mock import job_service
from tests.ai.jobs.domain_job_test_utils import bound_domain_attempt
from tests.ai.jobs.test_domain_jobs import claim, create_mock
from tests.ai.jobs.test_domain_jobs import execution_db as execution_fixture

execution_db = execution_fixture


def test_cancel_pending_records_intent_without_claiming_it_stopped(execution_db):
    factory, _ = execution_db
    job_id = create_mock(factory)
    with factory() as db:
        row = job_service.request_job_cancel(db, "project", job_id)
        assert row.status == AiJobStatus.PENDING
        assert row.finished_at is None
        assert row.execution.cancel_requested_at is not None
        assert row.execution.completion_json is None
    job_service._clear_cancel_event(job_id)


def test_cancel_running_preserves_attempt_until_cleanup(execution_db):
    factory, _ = execution_db
    job_id = create_mock(factory)
    _, attempt = claim(factory, job_id)
    with factory() as db:
        row = job_service.request_job_cancel(db, "project", job_id)
        assert row.status == AiJobStatus.RUNNING
        assert row.execution.run_token == attempt.run_token
        assert row.finished_at is None
    job_service._clear_cancel_event(job_id)


def test_replayed_inputs_cannot_replace_the_current_execution_identity(execution_db):
    from app.domains.ai.models.ai_job import SddAiJob

    factory, _ = execution_db
    job_id = create_mock(factory, inputs={"user_id": "previous-actor", "workspace_id": "other", "task_id": "other"})
    with factory() as db:
        inputs = db.get(SddAiJob, job_id).context_json["inputs"]
        assert inputs["user_id"] == "user"
        assert inputs["workspace_id"] == "workspace"
        assert inputs["task_id"] == "task"


def test_job_snapshots_only_expose_business_results():
    job = SimpleNamespace(
        id="job",
        project_id="project",
        creator_id="user",
        job_type="AUTO_GENERATE_MOCK_CASES",
        status=AiJobStatus.SUCCESS,
        cancel_requested=False,
        progress=100,
        message=None,
        created_at=datetime.now(),
        updated_at=None,
        started_at=None,
        finished_at=None,
        execution=SimpleNamespace(version=4, attempt_count=1, completion_json=None),
        result_json={"target_endpoint_id": "endpoint", "created_count": 3, "live_logs": ["old log"]},
    )
    expected = {"target_endpoint_id": "endpoint", "created_count": 3}
    assert job_service._serialize_job(job)["result_json"] == expected
    assert ApiMockJobResponse.model_validate(job).result_json == expected
    assert "live_logs" in job.result_json


def test_current_phase_replaces_status_without_appending_execution_content(execution_db):
    factory, _ = execution_db
    job_id = create_mock(factory)
    with factory() as db, bound_domain_attempt(db, job_id):
        row = db.get(SddApiMockJob, job_id)
        seen = []
        for message in ["正在生成 Mock 场景", "正在校验业务产物", "正在保存 Mock 用例"]:
            job_service._set_job_progress(db, "project", row, 30, message)
            seen.append((row.message, row.execution.version))
        assert [item[0] for item in seen] == ["正在生成 Mock 场景", "正在校验业务产物", "正在保存 Mock 用例"]
        assert seen[0][1] < seen[1][1] < seen[2][1]
        assert row.result_json == {}
