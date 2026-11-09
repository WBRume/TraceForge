from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.agents.domain_tools.contracts import MockSubmission
from app.domains.api_mock.services.api_mock import auto_mock_service as service
from app.domains.api_mock.services.api_mock import job_service


@pytest.mark.parametrize("failure", ["second_insert", "cancel_after_insert"])
def test_mock_batch_rolls_back_before_terminal_job_commit(db, monkeypatch, failure):
    db.execute(text("CREATE TABLE domain_batch_probe (id INTEGER PRIMARY KEY)"))
    db.commit()
    job = SimpleNamespace(id="job")
    project = SimpleNamespace(id="project", workspace_id="workspace", task_id="task")
    endpoint = SimpleNamespace(
        id="endpoint", method="GET", path="/test", parameters_json=[], request_schema_json={}, responses_json={}
    )
    terminal = []
    inserted = 0

    async def run(*_args, **_kwargs):
        return {
            "artifact": MockSubmission(
                cases=[
                    {"name": "one", "mode": "STATIC", "status_code": 200, "static_body_json": {}},
                    {"name": "two", "mode": "STATIC", "status_code": 200, "static_body_json": {}},
                ]
            ),
            "domain_milestones": [],
        }

    def create(*_args, **kwargs):
        nonlocal inserted
        assert kwargs["commit"] is False
        inserted += 1
        db.execute(text("INSERT INTO domain_batch_probe (id) VALUES (:id)"), {"id": inserted})
        if failure == "second_insert" and inserted == 2:
            raise RuntimeError("Second insert failed")
        return SimpleNamespace(id=str(inserted))

    def finish(state):
        def commit(*_args, **_kwargs):
            terminal.append(state)
            db.commit()

        return commit

    for name in ("_set_job_running", "_set_job_progress"):
        monkeypatch.setattr(service, name, lambda *_args, **_kwargs: None)
    # Cancellation logging commits the job; pending business writes must have
    # been rolled back before that independent commit.
    monkeypatch.setattr(
        job_service, "_is_cancel_requested", lambda _: failure == "cancel_after_insert" and inserted == 2
    )
    monkeypatch.setattr(service, "get_job", lambda *_: job)
    monkeypatch.setattr(service, "get_endpoint", lambda *_: endpoint)
    monkeypatch.setattr(service, "resolve_workspace_backend", lambda *_: "opencode")
    monkeypatch.setattr(service, "_temp_workspace_path", lambda *_: "unused")
    monkeypatch.setattr(service, "run_domain_turn", run)
    monkeypatch.setattr(service, "list_mock_cases_for_endpoint", lambda *_: [])
    monkeypatch.setattr(service, "create_mock_case", create)
    monkeypatch.setattr(service, "_set_job_failed", finish("failed"))
    monkeypatch.setattr(service, "_set_job_cancelled", finish("cancelled"))
    monkeypatch.setattr(
        "app.domains.api_mock.services.api_mock.mock_case_service.next_mock_case_sort_order", lambda *_: 0
    )
    service.auto_generate_mock_cases_for_endpoint(
        db, project, job_id="job", endpoint_id="endpoint", creator_id="user", workspace_sync_needed=False
    )
    assert inserted == 2
    assert terminal == ["failed" if failure == "second_insert" else "cancelled"]
    assert db.scalar(text("SELECT count(*) FROM domain_batch_probe")) == 0
