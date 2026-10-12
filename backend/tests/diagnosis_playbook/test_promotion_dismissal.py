from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import publishing
from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
from app.domains.diagnosis_playbook import promotion
from app.domains.diagnosis_playbook.models import PlaybookSpec
from tests.diagnosis_playbook.test_business_flow import seed_case
from tests.diagnosis_playbook.test_library_management import client_for
from tests.diagnosis_playbook.test_promotion_review import generated


@pytest.mark.parametrize("action", ["dismiss", "cancel"])
def test_closing_draft_is_durable_and_prevents_later_confirmation(db, monkeypatch, action):
    user, ws, _, job, draft = generated(db, monkeypatch)
    publish = AsyncMock()
    monkeypatch.setattr(publishing, "publish_job_state", publish)
    user_id, job_id = user.id, job.id
    url = f"/workspaces/{ws.id}/cases/playbook-promotions"
    revision = job.result_json["draft_revision"]
    client = client_for(db, user)
    response = client.post(f"{url}/{job_id}/{action}")
    assert response.status_code == 200, response.text
    assert response.json()["dismissed"] is True
    assert response.json()["result"]["review_state"] == "DISCARDED"
    publish.assert_awaited_once_with(job_id)
    assert client.post(f"{url}/{job_id}/{action}").json() == response.json()

    # A new DB session and HTTP client have no browser-local dismissal state.
    with Session(db.get_bind()) as other_db:
        other = client_for(other_db, other_db.get(User, user_id))
        assert other.get("/cases/playbook-promotions/active").json()["items"] == []
        assert other.get(url).json()["items"] == []
        assert other.get(url, params={"job_id": job_id}).json()["items"][0]["dismissed"] is True
        stale_confirm = other.post(
            f"{url}/{job_id}/confirm", json={"draft_revision": revision, "draft": draft.model_dump()}
        )
        assert stale_confirm.status_code == 409
        assert other_db.query(PlaybookSpec).count() == 0


def test_failed_dismissal_preserves_error_and_does_not_hide_other_jobs(db, monkeypatch):
    user, ws, _, case = seed_case(db)
    failed = promotion.create(db, ws.id, [case.id], user.id, "failed")
    failed.status = AiJobStatus.FAILED
    failed.error_message = "Provider connection failed"
    active = promotion.create(db, ws.id, [case.id], user.id, "active")
    db.commit()
    monkeypatch.setattr(publishing, "publish_job_state", AsyncMock())
    client = client_for(db, user)
    url = f"/workspaces/{ws.id}/cases/playbook-promotions"
    assert len(client.get(url).json()["items"]) == 2
    response = client.post(f"{url}/{failed.id}/dismiss")
    assert response.status_code == 200, response.text
    assert response.json()["error"] == "Provider connection failed"
    db.expire_all()
    assert db.get(SddAiJob, failed.id).status == AiJobStatus.FAILED
    assert [item["job_id"] for item in client.get(url).json()["items"]] == [active.id]
    assert [item["job_id"] for item in client.get("/cases/playbook-promotions/active").json()["items"]] == [active.id]


@pytest.mark.parametrize(
    "status", [AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.TERMINATING, AiJobStatus.ORPHANED]
)
def test_active_jobs_cannot_bypass_cancellation_by_dismissal(db, status):
    user, ws, _, case = seed_case(db)
    job = promotion.create(db, ws.id, [case.id], user.id, "active")
    job.status = status
    db.commit()
    response = client_for(db, user).post(f"/workspaces/{ws.id}/cases/playbook-promotions/{job.id}/dismiss")
    assert response.status_code == 409
    db.refresh(job)
    assert not promotion.view(job)["dismissed"]


def test_queued_job_close_really_cancels_and_disappears_from_restore(db, monkeypatch):
    user, ws, _, case = seed_case(db)
    job = promotion.create(db, ws.id, [case.id], user.id, "queued")
    db.commit()
    monkeypatch.setattr(publishing, "publish_job_state", AsyncMock())
    client = client_for(db, user)
    response = client.post(f"/workspaces/{ws.id}/cases/playbook-promotions/{job.id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"
    assert client.get("/cases/playbook-promotions/active").json()["items"] == []
    db.refresh(job)
    assert job.status == AiJobStatus.CANCELLED


def test_other_workspace_member_cannot_close_creators_promotion(db, monkeypatch):
    user, ws, _, job, _ = generated(db, monkeypatch)
    other = User(email="other@example.test", display_name="Other", hashed_password="unused")
    db.add(other)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=other.id, role=WorkspaceRole.DEVELOPER))
    db.commit()
    client = client_for(db, other)
    url = f"/workspaces/{ws.id}/cases/playbook-promotions/{job.id}"
    assert client.post(f"{url}/dismiss").status_code == 404
    assert client.post(f"{url}/cancel").status_code == 404
    assert job.result_json["review_state"] == "PENDING"
