from datetime import datetime
from types import SimpleNamespace

import pytest

from app.domains.api_mock.models.api_mock import ApiMockJobStatus
from app.domains.api_mock.schemas.api_mock import ApiMockJobResponse
from app.domains.api_mock.services.api_mock import job_service


class _CancelSignal:
    def __init__(self) -> None:
        self.set_called = False

    def set(self) -> None:
        self.set_called = True


def _build_job(*, status: ApiMockJobStatus) -> SimpleNamespace:
    return SimpleNamespace(
        id="job-1",
        status=status,
        result_json={},
        message=None,
        finished_at=None,
    )


def test_request_job_cancel_pending_marks_failed_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    db = object()
    project_id = "project-1"
    job_id = "job-1"
    job = _build_job(status=ApiMockJobStatus.PENDING)
    cancel_signal = _CancelSignal()

    failed_calls = []
    commit_calls = []
    mark_cancelled_calls = []

    monkeypatch.setattr(job_service, "get_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(job_service.domain_jobs, "request_cancel", lambda *_: None)
    monkeypatch.setattr(job_service, "_get_or_create_cancel_event", lambda *_args, **_kwargs: cancel_signal)
    monkeypatch.setattr(job_service, "_mark_job_cancel_requested", lambda *_args, **_kwargs: None)

    def _fake_set_job_failed(*args, **_kwargs):
        failed_calls.append(args)
        job.status = ApiMockJobStatus.FAILED

    def _fake_mark_job_cancelled(*args, **_kwargs):
        mark_cancelled_calls.append(args)

    def _fake_commit_job_state(*args, **kwargs):
        commit_calls.append((args, kwargs))

    monkeypatch.setattr(job_service, "_set_job_failed", _fake_set_job_failed)
    monkeypatch.setattr(job_service, "_mark_job_cancelled", _fake_mark_job_cancelled)
    monkeypatch.setattr(job_service, "_commit_job_state", _fake_commit_job_state)

    result = job_service.request_job_cancel(db, project_id, job_id)

    assert result is job
    assert cancel_signal.set_called is True
    assert len(failed_calls) == 1
    assert failed_calls[0] == (db, project_id, job, "Job cancelled before execution")
    assert len(mark_cancelled_calls) == 1
    assert mark_cancelled_calls[0] == (job,)
    assert len(commit_calls) == 1
    assert commit_calls[0][0] == (db, project_id, job)
    assert commit_calls[0][1] == {"done": True}


def test_request_job_cancel_running_only_marks_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    db = object()
    project_id = "project-1"
    job_id = "job-1"
    job = _build_job(status=ApiMockJobStatus.RUNNING)
    cancel_signal = _CancelSignal()

    failed_calls = []
    mark_cancelled_calls = []
    commit_calls = []

    monkeypatch.setattr(job_service, "get_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(job_service.domain_jobs, "request_cancel", lambda *_: None)
    monkeypatch.setattr(job_service, "_get_or_create_cancel_event", lambda *_args, **_kwargs: cancel_signal)
    monkeypatch.setattr(job_service, "_mark_job_cancel_requested", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(job_service, "_set_job_failed", lambda *args, **_kwargs: failed_calls.append(args))
    monkeypatch.setattr(job_service, "_mark_job_cancelled", lambda *args, **_kwargs: mark_cancelled_calls.append(args))
    monkeypatch.setattr(
        job_service,
        "_commit_job_state",
        lambda *args, **kwargs: commit_calls.append((args, kwargs)),
    )

    result = job_service.request_job_cancel(db, project_id, job_id)

    assert result is job
    assert cancel_signal.set_called is True
    assert failed_calls == []
    assert mark_cancelled_calls == []
    assert len(commit_calls) == 1
    assert commit_calls[0][0] == (db, project_id, job)
    assert commit_calls[0][1] == {"done": False}


def test_job_snapshots_only_expose_business_results():
    job = _build_job(status=ApiMockJobStatus.SUCCESS)
    job.project_id = "project"
    job.creator_id = "user"
    job.job_type = "AUTO_GENERATE_MOCK_CASES"
    job.progress = 100
    job.created_at = datetime.now()
    job.updated_at = job.started_at = None
    job.result_json = {
        "target_endpoint_id": "endpoint",
        "created_count": 3,
        "cancel_requested": False,
        "live_logs": ["old CLI log"],
        "live_events": [{"type": "domain_milestone"}],
        "latest_log": "old",
        "latest_event_type": "domain_milestone",
        "latest_event_at": "old",
    }
    expected = {"target_endpoint_id": "endpoint", "created_count": 3, "cancel_requested": False}
    assert job_service._serialize_job(job)["result_json"] == expected
    assert ApiMockJobResponse.model_validate(job).result_json == expected
    # Existing records are preserved; neither HTTP nor WS returns historical execution output.
    assert "live_events" in job.result_json


def test_current_phase_replaces_status_without_appending_execution_content(monkeypatch):
    job = _build_job(status=ApiMockJobStatus.RUNNING)
    job.result_json = {"target_endpoint_id": "endpoint"}
    snapshots = []
    monkeypatch.setattr(
        job_service, "_commit_job_state", lambda *_: snapshots.append((job.message, dict(job.result_json)))
    )
    for message in ["正在生成 Mock 场景", "正在校验业务产物", "正在保存 Mock 用例"]:
        job_service._set_job_progress(object(), "project", job, 30, message)
    assert [entry[0] for entry in snapshots] == ["正在生成 Mock 场景", "正在校验业务产物", "正在保存 Mock 用例"]
    assert all(entry[1] == {"target_endpoint_id": "endpoint"} for entry in snapshots)
