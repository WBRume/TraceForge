"""Transition qualification, transactional HITL, and independent delivery."""

from datetime import datetime, timedelta
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
from app.domains.notification.models.task_awareness import TaskAwarenessEvent, TaskWebhookEndpoint, TaskWebhookDelivery
from app.domains.notification.services.task_awareness import capture_job, capture_business, webhook_eligible
from app.domains.notification.services import task_awareness_worker as worker, task_webhooks as hooks
from app.domains.notification.routers import task_awareness as routes
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import TaskStatus
from app.domains.task.services import task_session_control_service
from app.domains.task.routers import task_closeout as closeout_routes
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace


@pytest.fixture
def seeded():
    engine, factory = _build_db()
    with factory() as db:
        user, workspace, task = _seed_workspace(db)
        yield db, factory, user, workspace, task
    engine.dispose()


def start(db, user, workspace, task, *, seconds=30, creator_id=None):
    job = SddAiJob(id="j1", workspace_id=workspace.id, task_id=task.id, creator_id=creator_id or user.id,
                   channel=AiJobChannel.TASK_CHAT, status=AiJobStatus.RUNNING, queue_key=f"TASK_CHAT:{task.id}",
                   started_at=datetime.utcnow() - timedelta(seconds=seconds), context_json={"client_message_id": "c1"})
    db.add(job); db.flush(); capture_job(db, job, allow_start=True); db.commit()
    return job


def latest(db, kind):
    return db.query(TaskAwarenessEvent).filter(TaskAwarenessEvent.event_type == kind).order_by(TaskAwarenessEvent.created_at.desc()).first()


def endpoint(db, key, *, user_id=None, workspace_id=None, location="server", events=None):
    row = TaskWebhookEndpoint(scope_key=key, user_id=user_id, workspace_id=workspace_id, enabled=True,
        url="https://hooks.example/secret", delivery_location=location,
        events_json=events or [*routes.RUNTIME_EVENTS, *routes.BUSINESS_EVENTS],
        created_at=datetime.utcnow() - timedelta(minutes=1))
    db.add(row); db.commit()
    return row


def confirmation(db, task, user, *, id="p1", interaction="i1", job_id="j1"):
    row = ChatMessage(id=id, task_id=task.id, workspace_id=task.workspace_id, creator_id=user.id, role="assistant", content="请确认设计",
                       metadata_json={"confirmation": {"job_id": job_id, "interaction_id": interaction}}, session_generation=task.session_generation)
    db.add(row); db.commit()
    return row


def reply(db, task, user, prompt_id, interaction, *, id="r1"):
    db.add(ChatMessage(id=id, task_id=task.id, workspace_id=task.workspace_id, creator_id=user.id, role="user", content="继续",
                       metadata_json={"reply_to_message_id": prompt_id, "interaction_id": interaction}))
    db.commit()


def test_reads_and_historical_errors_never_create_events(seeded):
    db, _, user, workspace, task = seeded
    job = SddAiJob(id="old", workspace_id=workspace.id, task_id=task.id, creator_id=user.id,
                   channel=AiJobChannel.TASK_CHAT, queue_key="old", status=AiJobStatus.FAILED,
                   started_at=datetime.utcnow() - timedelta(minutes=5), finished_at=datetime.utcnow())
    db.add(job); db.commit(); db.get(SddAiJob, job.id); db.get(type(task), task.id); db.commit()
    job.message = "Progress replay"; db.commit()
    assert db.query(TaskAwarenessEvent).count() == 0


def test_transition_is_transactional_and_repeated_progress_is_inert(seeded):
    db, _, user, workspace, task = seeded
    job = start(db, user, workspace, task)
    assert job.awareness_version == 1
    capture_job(db, job); job.progress = 90; db.commit()
    assert db.query(TaskAwarenessEvent).count() == 1
    job.status = AiJobStatus.SUCCESS; job.finished_at = datetime.utcnow(); db.flush()
    assert latest(db, "AI_RUN_FINISHED") is not None
    db.rollback()
    assert db.get(SddAiJob, job.id).status == AiJobStatus.RUNNING
    assert db.query(TaskAwarenessEvent).count() == 1


@pytest.mark.parametrize("status,kind", [(AiJobStatus.SUCCESS, "AI_RUN_FINISHED"), (AiJobStatus.FAILED, "AI_RUN_ERROR"),
                                        (AiJobStatus.CANCELLED, "AI_RUN_STOPPED"), (AiJobStatus.REVERTED, "AI_RUN_STOPPED")])
def test_runtime_does_not_emit_business_terminal_events(seeded, status, kind):
    db, _, user, workspace, task = seeded
    job = start(db, user, workspace, task); job.status = status; job.finished_at = datetime.utcnow(); db.commit()
    assert latest(db, kind) is not None
    assert task.business_state == "TASK_IN_PROGRESS"
    assert latest(db, "TASK_COMPLETED") is None and latest(db, "TASK_FAILED") is None and latest(db, "TASK_CANCELLED") is None


def test_confirmation_messages_project_hitl_and_clear_only_when_all_replied(seeded):
    db, _, user, workspace, task = seeded
    job = start(db, user, workspace, task)
    confirmation(db, task, user); confirmation(db, task, user, id="p2", interaction="i2")
    assert job.status == AiJobStatus.RUNNING
    assert job.awareness_state == "AI_HITL_SUSPENDED" and job.awareness_version == 2
    reply(db, task, user, "p1", "i1")
    assert job.awareness_state == "AI_HITL_SUSPENDED" and job.awareness_pending_json == ["i2"]
    reply(db, task, user, "p2", "i2", id="r2")
    assert job.awareness_state == "AI_RUNNING" and job.awareness_version == 3
    assert not webhook_eligible(latest(db, "AI_HITL_SUSPENDED"), job)


def test_short_run_never_becomes_long_due_to_delivery_delay(seeded):
    db, _, user, workspace, task = seeded
    job = start(db, user, workspace, task, seconds=2); job.status = AiJobStatus.SUCCESS; job.finished_at = datetime.utcnow(); db.commit()
    assert not webhook_eligible(latest(db, "AI_RUN_FINISHED"), job, datetime.utcnow() + timedelta(days=1))


def test_old_hitl_does_not_reappear_when_a_new_confirmation_occurs(seeded):
    db, _, user, workspace, task = seeded
    job = start(db, user, workspace, task); confirmation(db, task, user)
    old = latest(db, "AI_HITL_SUSPENDED"); reply(db, task, user, "p1", "i1")
    confirmation(db, task, user, id="p2", interaction="i2")
    assert not webhook_eligible(old, job)
    assert webhook_eligible(latest(db, "AI_HITL_SUSPENDED"), job)


def test_manual_business_event_is_distinct_and_idempotent(seeded):
    db, _, user, workspace, task = seeded
    kind = "TASK_COMPLETED"
    start(db, user, workspace, task)
    capture_business(db, task, user.id, kind, "人工收尾"); db.commit()
    capture_business(db, task, user.id, kind); db.commit()
    row = latest(db, kind)
    assert row.payload_json["actor"]["id"] == user.id
    assert db.query(TaskAwarenessEvent).filter_by(event_type=kind).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", [2, 30])
@pytest.mark.parametrize("confirmed_dead", [True, False])
async def test_existing_interrupt_ends_only_the_run_and_broadcasts_if_opted_in(seeded, monkeypatch, seconds, confirmed_dead):
    from app.agents.supervision import TerminationResult
    from app.domains.ai.services.jobs import publishing, registry
    from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db

    db, factory, user, workspace, task = seeded
    default_endpoint = endpoint(db, "user:me", user_id=user.id, events=routes.DEFAULT_EVENTS.copy())
    opted_in = endpoint(db, "workspace:ws", workspace_id=workspace.id, events=["AI_RUN_INTERRUPTED"])
    job = start(db, user, workspace, task, seconds=seconds)
    task.status = TaskStatus.CODING
    job.run_token = "interrupt-attempt"
    job.worker_boot_id = registry.WORKER_BOOT_ID
    job.session_id = "preserved-session"
    db.commit()
    confirmation(db, task, user)
    patch_ai_job_db(monkeypatch, factory)

    class Engine:
        current_job_id = job.id
        running = True
        session_id = job.session_id

        async def interrupt(self):
            return TerminationResult(confirmed_dead=confirmed_dead, root_return_code=0 if confirmed_dead else None)

    async def ignore(*args):
        pass

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _: Engine())
    monkeypatch.setattr(task_session_control_service, "_broadcast_task_event", ignore)
    monkeypatch.setattr(publishing, "publish_job", ignore)
    await task_session_control_service.interrupt_task(db, task=task, actor_user_id=user.id, reason="暂停本轮，稍后继续")
    db.refresh(job); db.refresh(task)
    assert task.status == TaskStatus.INTERRUPTED and task.business_state == "TASK_IN_PROGRESS"
    assert db.query(ChatMessage).count() == 1
    assert latest(db, "TASK_COMPLETED") is None and latest(db, "TASK_CANCELLED") is None
    assert job.status == (AiJobStatus.INTERRUPTED if confirmed_dead else AiJobStatus.ORPHANED)
    row = latest(db, "AI_RUN_INTERRUPTED" if confirmed_dead else "AI_RUN_ERROR")
    assert row is not None and job.awareness_pending_json == []
    if confirmed_dead:
        assert row.payload_json["summary"] == "暂停本轮，稍后继续"
        assert job.session_id == "preserved-session" and job.run_token is None
        assert latest(db, "AI_RUN_FINISHED") is None and latest(db, "AI_RUN_ERROR") is None
    else:
        assert latest(db, "AI_RUN_INTERRUPTED") is None
    hooks.prepare_deliveries(db, row, datetime.utcnow()); db.commit()
    expected = [opted_in.id if confirmed_dead else default_endpoint.id] if seconds >= 10 else []
    assert [item.endpoint_id for item in db.query(TaskWebhookDelivery).all()] == expected


def test_task_cancel_is_not_a_business_event_or_route(seeded):
    db, _, user, workspace, task = seeded
    with pytest.raises(ValueError):
        capture_business(db, task, user.id, "TASK_CANCELLED")
    app = FastAPI(); app.include_router(closeout_routes.router, prefix="/api")
    client = TestClient(app)
    assert client.post(f"/api/workspaces/{workspace.id}/tasks/{task.id}/closeout/cancel", json={}).status_code == 404
    assert task.business_state == "TASK_IN_PROGRESS" and db.query(TaskAwarenessEvent).count() == 0


def test_workspace_broadcasts_other_member_but_personal_is_initiator_scoped(seeded):
    db, _, user, workspace, task = seeded
    member = User(id="member", email="member@example.com", hashed_password="x", display_name="团队成员")
    db.add(member); db.add(WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role=WorkspaceRole.DEVELOPER)); db.commit()
    own = endpoint(db, "user:owner", user_id=user.id)
    team = endpoint(db, "workspace:ws", workspace_id=workspace.id)
    job = start(db, user, workspace, task, creator_id=member.id)
    job.status = AiJobStatus.SUCCESS; job.finished_at = datetime.utcnow(); db.commit()
    row = latest(db, "AI_RUN_FINISHED"); hooks.prepare_deliveries(db, row, datetime.utcnow()); db.commit()
    assert [item.endpoint_id for item in db.query(TaskWebhookDelivery).all()] == [team.id]
    assert row.payload_json["initiator"]["id"] == member.id
    assert row.payload_json["task"]["url"].endswith(f"/workspaces/{workspace.id}/chat/{task.id}")


def test_desktop_claim_is_exclusive_scoped_and_revocation_skips_delivery(seeded):
    db, _, user, workspace, task = seeded
    config = endpoint(db, "user:me", user_id=user.id, location="desktop")
    job = start(db, user, workspace, task); confirmation(db, task, user)
    row = latest(db, "AI_HITL_SUSPENDED"); hooks.prepare_deliveries(db, row, datetime.utcnow()); db.commit()
    assert hooks.claim_deliveries(db, location="desktop", user_id="other") == []
    first = hooks.claim_deliveries(db, location="desktop", user_id=user.id); db.commit()
    assert len(first) == 1 and hooks.claim_deliveries(db, location="desktop", user_id=user.id) == []
    assert not hooks.finish_delivery(db, first[0]["id"], "wrong", True, user_id=user.id)
    assert hooks.finish_delivery(db, first[0]["id"], first[0]["lease_token"], False, "NetworkError", user_id=user.id)
    config.enabled = False; db.query(TaskWebhookDelivery).one().available_at = datetime.utcnow(); db.commit()
    assert hooks.claim_deliveries(db, location="desktop", user_id=user.id) == []
    assert db.query(TaskWebhookDelivery).one().status == "SKIPPED"


def test_expired_lease_is_reclaimed_and_old_ack_cannot_overwrite_new_claim(seeded):
    db, _, user, workspace, task = seeded
    endpoint(db, "user:me", user_id=user.id)
    job = start(db, user, workspace, task); confirmation(db, task, user)
    hooks.prepare_deliveries(db, latest(db, "AI_HITL_SUSPENDED"), datetime.utcnow()); db.commit()
    first = hooks.claim_deliveries(db, location="server")[0]; db.commit()
    row = db.query(TaskWebhookDelivery).one(); row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    second = hooks.claim_deliveries(db, location="server")[0]; db.commit()
    assert first["lease_token"] != second["lease_token"] and row.attempts == 2
    assert not hooks.finish_delivery(db, row.id, first["lease_token"], True)
    assert hooks.finish_delivery(db, row.id, second["lease_token"], True)
    assert job.status == AiJobStatus.RUNNING


def test_short_hitl_waits_for_qualification_and_desktop_nudges_do_not_delay_claim(seeded):
    db, _, user, workspace, task = seeded
    endpoint(db, "user:me", user_id=user.id, location="desktop")
    job = start(db, user, workspace, task, seconds=2); confirmation(db, task, user)
    event = latest(db, "AI_HITL_SUSPENDED")
    hooks.prepare_deliveries(db, event, datetime.utcnow()); db.commit()
    row = db.query(TaskWebhookDelivery).one()
    assert not webhook_eligible(event, job)
    assert webhook_eligible(event, job, job.started_at + timedelta(seconds=10))
    assert hooks.claim_deliveries(db, location="desktop", user_id=user.id) == []
    assert worker._desktop_recipients(db) == set()
    row.available_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    gate = row.available_at
    assert worker._desktop_recipients(db) == {user.id}; db.commit()
    assert row.available_at == gate and worker._desktop_recipients(db) == set()


def test_unreachable_endpoint_exhausts_bounded_retries_without_mutating_ai(seeded):
    db, _, user, workspace, task = seeded
    endpoint(db, "user:me", user_id=user.id)
    job = start(db, user, workspace, task); job.status = AiJobStatus.SUCCESS; job.finished_at = datetime.utcnow(); db.commit()
    hooks.prepare_deliveries(db, latest(db, "AI_RUN_FINISHED"), datetime.utcnow()); db.commit()
    for attempt in range(1, 4):
        row = db.query(TaskWebhookDelivery).one(); row.available_at = datetime.utcnow(); db.commit()
        item = hooks.claim_deliveries(db, location="server")[0]; db.commit()
        hooks.finish_delivery(db, row.id, item["lease_token"], False, "TimeoutError"); db.commit()
        assert row.attempts == attempt
    assert row.status == "FAILED" and job.status == AiJobStatus.SUCCESS


def test_relay_never_replays_superseded_transient_states_as_fresh_long_runs(seeded):
    db, _, user, workspace, task = seeded
    job = start(db, user, workspace, task, seconds=2); confirmation(db, task, user)
    reply(db, task, user, "p1", "i1")
    job.status = AiJobStatus.SUCCESS; job.finished_at = datetime.utcnow(); db.commit()
    claimed = worker._claim_events(db)
    assert [item["payload"]["event_type"] for item in claimed if item["notify"]] == ["AI_RUN_FINISHED"]
    assert not webhook_eligible(latest(db, "AI_RUN_FINISHED"), job)


def test_standard_json_retains_metadata_and_full_bounded_summary(seeded):
    db, _, user, workspace, task = seeded
    endpoint(db, "user:me", user_id=user.id)
    job = start(db, user, workspace, task)
    confirmation(db, task, user)
    row = latest(db, "AI_HITL_SUSPENDED")
    row.payload_json = {**row.payload_json, "summary": "等待人工确认数据库结构变更" * 30}
    hooks.prepare_deliveries(db, row, datetime.utcnow()); db.commit()
    claimed = hooks.claim_deliveries(db, location="server")[0]
    assert claimed["body"] == row.payload_json
    assert claimed["body"]["event_type"] == "AI_HITL_SUSPENDED"
    assert claimed["body"]["run"]["id"] == job.id and claimed["body"]["task"]["url"].endswith(f"/chat/{task.id}")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:secret@host/path", "http://169.254.169.254/latest", "https://host/#fragment"])
def test_invalid_urls_are_rejected(url):
    with pytest.raises(ValueError): hooks.validate_url(url)


@pytest.mark.asyncio
async def test_worker_network_failure_never_changes_successful_ai_job(seeded, monkeypatch):
    db, factory, user, workspace, task = seeded
    endpoint(db, "user:me", user_id=user.id)
    job = start(db, user, workspace, task); job.status = AiJobStatus.SUCCESS; job.finished_at = datetime.utcnow(); db.commit()
    async def txn(callback):
        with factory() as session:
            result = callback(session); session.commit(); return result
    async def fail(*args, **kwargs): return False, "ConnectError"
    async def push(*args): return False
    monkeypatch.setattr(worker, "run_db_txn", txn); monkeypatch.setattr(worker, "post_webhook", fail)
    monkeypatch.setattr(worker.notification_ws_manager, "send_message_to_user", push)
    await worker.relay_once(); db.expire_all()
    assert db.get(SddAiJob, job.id).status == AiJobStatus.SUCCESS
    assert db.query(TaskWebhookDelivery).one().status == "PENDING"
    assert latest(db, "AI_RUN_FINISHED").published_at is not None


@pytest.mark.asyncio
async def test_slow_webhook_does_not_hold_up_runtime_relay(seeded, monkeypatch):
    db, factory, user, workspace, task = seeded
    endpoint(db, "user:me", user_id=user.id)
    start(db, user, workspace, task); confirmation(db, task, user)
    hooks.prepare_deliveries(db, latest(db, "AI_HITL_SUSPENDED"), datetime.utcnow()); db.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    messages = []
    async def txn(callback):
        with factory() as session:
            result = callback(session); session.commit(); return result
    async def slow(*args):
        entered.set(); await release.wait(); return True, None
    async def push(user_id, payload):
        messages.append(payload); return True
    monkeypatch.setattr(worker, "run_db_txn", txn); monkeypatch.setattr(worker, "post_webhook", slow)
    monkeypatch.setattr(worker.notification_ws_manager, "send_message_to_user", push)
    delivery = asyncio.create_task(worker.deliver_webhooks_once())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        reply(db, task, user, "p1", "i1")
        await asyncio.wait_for(worker.relay_events_once(), 1)
        assert not delivery.done()
        assert any(item.get("event", {}).get("event_type") == "AI_RUNNING" for item in messages)
    finally:
        release.set(); await delivery


@pytest.mark.asyncio
async def test_generic_http_status_acknowledges_without_parsing_service_specific_body(monkeypatch):
    original = httpx.AsyncClient
    for status, body, expected in [(503, {}, (False, "HTTP 503")), (200, {"code": 42, "detail": "custom endpoint"}, (True, None)), (202, {}, (True, None))]:
        transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        monkeypatch.setattr(hooks.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
        assert await hooks.post_webhook("https://hooks.example/secret", {}, "event") == expected


def test_settings_permissions_defaults_and_snapshot_visibility(seeded):
    db, _, user, workspace, task = seeded
    app = FastAPI(); app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.get_db] = lambda: db
    current = [user]
    app.dependency_overrides[routes.get_current_user] = lambda: current[0]
    client = TestClient(app)
    response = client.get("/api/users/me/task-webhook"); assert response.status_code == 200
    assert response.json()["events"] == ["AI_HITL_SUSPENDED", "AI_RUN_FINISHED", "AI_RUN_ERROR"]
    assert "format" not in response.json()
    assert client.put("/api/users/me/task-webhook", json={"format": "custom"}).status_code == 422
    assert client.put("/api/users/me/task-webhook", json={"events": [*routes.RUNTIME_EVENTS, *routes.BUSINESS_EVENTS]}).status_code == 200
    assert client.put("/api/users/me/task-webhook", json={"events": ["AI_RUN_INTERRUPTED"]}).status_code == 200
    assert client.put("/api/users/me/task-webhook", json={"events": ["TASK_CANCELLED"]}).status_code == 422
    assert client.put(f"/api/workspaces/{workspace.id}/task-webhook", json={"url": "http://127.0.0.1/hook", "delivery_location": "desktop"}).status_code == 422
    job = start(db, user, workspace, task)
    assert len(client.get("/api/task-awareness/runs", params={"job_ids": job.id}).json()["runs"]) == 1
    assert len(client.get("/api/task-awareness/runs", params={"client_message_ids": "c1"}).json()["runs"]) == 1
    current[0] = SimpleNamespace(id="intruder")
    assert client.get(f"/api/workspaces/{workspace.id}/task-webhook").status_code == 403
    assert client.get("/api/task-awareness/runs", params={"job_ids": job.id}).json()["runs"] == []
    assert client.get("/api/task-awareness/runs", params={"client_message_ids": "c1"}).json()["runs"] == []


def test_explicit_test_message_uses_draft_without_creating_task_events_or_saving_settings(seeded, monkeypatch):
    db, _, user, workspace, task = seeded
    sent = []
    async def post(**request):
        sent.append(request); return True, None
    monkeypatch.setattr(routes, "post_webhook", post)
    app = FastAPI(); app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.get_db] = lambda: db
    app.dependency_overrides[routes.get_current_user] = lambda: user
    client = TestClient(app)
    result = client.post("/api/users/me/task-webhook/test", json={"url": "http://127.0.0.1:9000/hook"})
    assert result.json() == {"ok": True, "error": None}
    assert sent[0]["body"]["event_type"] == "WEBHOOK_TEST" and sent[0]["body"]["initiator"]["id"] == user.id
    assert db.query(TaskAwarenessEvent).count() == 0 and db.query(TaskWebhookEndpoint).count() == 0
