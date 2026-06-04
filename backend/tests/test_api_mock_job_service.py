import os
import sys
from types import SimpleNamespace

import pytest

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.api_mock.models.api_mock import ApiMockJobStatus
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
    monkeypatch.setattr(job_service, "_get_or_create_cancel_event", lambda *_args, **_kwargs: cancel_signal)
    monkeypatch.setattr(job_service, "_mark_job_cancel_requested", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(job_service, "_append_job_log", lambda *_args, **_kwargs: None)

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
    monkeypatch.setattr(job_service, "_get_or_create_cancel_event", lambda *_args, **_kwargs: cancel_signal)
    monkeypatch.setattr(job_service, "_mark_job_cancel_requested", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(job_service, "_append_job_log", lambda *_args, **_kwargs: None)
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
