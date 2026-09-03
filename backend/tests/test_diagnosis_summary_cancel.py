"""「一键总结问题案例」取消链路与会话/总结互斥测试。

背景（2026-09 一键总结缺陷修复）：
- mark_task_chat_jobs_cancelled 曾经「先置位取消事件、又立刻清除」，导致
  run_cli_single_turn 的 cancel monitor 永远看不到取消信号，CLI 进程继续跑完，
  结束后执行器仍反填错误卡片（用户点停止无效、过一会冒出非 JSON 内容）。
- 会话与总结必须强互斥：聊天进行中（含排队、HITL 挂起）不能总结；
  总结进行中不能聊天/恢复会话/HITL 回复。

覆盖：
- 取消事件置位后不被 mark_task_chat_jobs_cancelled 立刻清除（回归）；
- 总结执行器在取消/已终态时丢弃结果：不反填卡片、不广播；
- 取消型 RuntimeError 被静默收敛；
- 会话/总结互斥守卫（API 409 与服务层异常）。
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.ai.services import ai_job_service  # noqa: E402
from app.domains.task.models.task import TaskStatus, TaskType  # noqa: E402
from app.domains.task.routers import task as task_router  # noqa: E402
from app.domains.task.services import task_session_control_service  # noqa: E402
from app.domains.task.services import task_session_service  # noqa: E402
from test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


def _build_app(SessionLocal, user, monkeypatch):
    @asynccontextmanager
    async def _fake_lock_task(_task_id):
        yield

    monkeypatch.setattr(task_router, "lock_task", _fake_lock_task)

    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(task_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = lambda: user
    return app


def _seed_diagnosis_task(db, workspace_id, task_id):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.task_type = TaskType.DIAGNOSIS.value
    task.task_meta_json = {"phenomenon": "接口偶发超时", "priority": "P1"}
    db.commit()
    return user, workspace, task


def _add_job(db, workspace, task, creator_id, *, status, job_kind=None, queue_key=None):
    context = {"source": "task_chat"}
    if job_kind:
        context["job_kind"] = job_kind
    job = SddAiJob(
        workspace_id=workspace.id,
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=queue_key or f"TASK_CHAT:{task.id}",
        status=status,
        creator_id=creator_id,
        context_json=context,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ────────────────────────── 取消链路 ──────────────────────────


def test_mark_task_chat_jobs_cancelled_keeps_cancel_event():
    """回归：取消事件必须先置位、执行结束才回收，不能在取消请求时立刻清除。

    事件被立刻清除会导致 cancel monitor 轮询 _is_cancel_requested 永远为 False，
    bridge.cancel() 不会被调用，CLI 进程继续跑完。
    """
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-cancel-ev", "task-cancel-ev")
            job = _add_job(
                db,
                workspace,
                task,
                user.id,
                status=AiJobStatus.RUNNING,
                job_kind="DIAGNOSIS_SUMMARY",
                queue_key=f"DIAGNOSIS_SUMMARY:{task.id}",
            )
            job_id = job.id

        with _session(SessionLocal) as db:
            cancelled_ids = ai_job_service.mark_task_chat_jobs_cancelled(
                db,
                workspace_id=workspace.id,
                task_id=task.id,
                message="Task execution stopped",
            )

        assert job_id in cancelled_ids
        try:
            assert ai_job_service._is_cancel_requested(job_id) is True
            # DB 状态仍被标记为 CANCELLED（前端立即收敛 UI）
            with _session(SessionLocal) as db:
                assert db.query(SddAiJob).filter(SddAiJob.id == job_id).first().status == (
                    AiJobStatus.CANCELLED
                )
        finally:
            ai_job_service._clear_cancel_event(job_id)
    finally:
        engine.dispose()


def _prepare_summary_job(db, workspace_id, task_id, *, session_id=None):
    user, workspace, task = _seed_diagnosis_task(db, workspace_id, task_id)
    if session_id:
        task.session_id = session_id
    db.commit()
    summary = ai_job_service.create_diagnosis_summary_job(
        db,
        workspace_id=workspace.id,
        task_id=task.id,
        creator_id=user.id,
    )
    return user, workspace, task, summary


def _patch_executor_common(monkeypatch, SessionLocal, *, run_impl):
    calls = {"upsert": 0, "broadcast": 0}

    async def _ignore_broadcast(*_args, **_kwargs):
        calls["broadcast"] += 1

    def _fail_upsert(*_args, **_kwargs):
        calls["upsert"] += 1
        raise AssertionError("cancelled summary must not upsert diagnosis card")

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_job_service, "run_cli_single_turn", run_impl)
    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _ignore_broadcast)
    monkeypatch.setattr(
        ai_job_service.diagnosis_result_service,
        "upsert_diagnosis_result_from_ai",
        _fail_upsert,
    )
    monkeypatch.setattr(
        ai_job_service.diagnosis_result_service,
        "extract_payload_from_text",
        lambda _text: SimpleNamespace(summary="x", root_cause="y"),
    )
    return calls


def test_diagnosis_summary_discards_result_when_cancel_event_set(monkeypatch):
    """停止按钮竞态：取消事件已置位（DB 仍 RUNNING），跑完后必须丢弃结果。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _workspace, _task, summary = _prepare_summary_job(
                db, "ws-cancel-run", "task-cancel-run"
            )
            summary_id = summary.id
        ai_job_service._request_job_cancel(summary_id)

        async def _fake_run(*_args, **_kwargs):
            return {"text": "```json\n{\"summary\": \"x\"}\n```", "session_id": "s"}

        calls = _patch_executor_common(monkeypatch, SessionLocal, run_impl=_fake_run)
        try:
            asyncio.run(ai_job_service._execute_diagnosis_summary_job(summary_id))
            assert calls["upsert"] == 0
        finally:
            ai_job_service._clear_cancel_event(summary_id)
    finally:
        engine.dispose()


def test_diagnosis_summary_discards_result_when_job_already_final(monkeypatch):
    """DB 已被标 CANCELLED（无取消事件）时同样丢弃结果，不反填卡片。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _workspace, _task, summary = _prepare_summary_job(
                db, "ws-cancel-db", "task-cancel-db"
            )
            summary_id = summary.id
            summary.status = AiJobStatus.CANCELLED
            db.commit()

        async def _fake_run(*_args, **_kwargs):
            return {"text": "```json\n{\"summary\": \"x\"}\n```", "session_id": "s"}

        calls = _patch_executor_common(monkeypatch, SessionLocal, run_impl=_fake_run)
        asyncio.run(ai_job_service._execute_diagnosis_summary_job(summary_id))
        assert calls["upsert"] == 0
    finally:
        engine.dispose()


def test_diagnosis_summary_swallows_cancel_runtime_error(monkeypatch):
    """cancel monitor 触发 bridge.cancel 后 run 抛取消型 RuntimeError，应静默收敛。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _workspace, _task, summary = _prepare_summary_job(
                db, "ws-cancel-err", "task-cancel-err"
            )
            summary_id = summary.id
        ai_job_service._request_job_cancel(summary_id)

        async def _fake_run(*_args, **_kwargs):
            raise RuntimeError("AI job cancelled by user")

        calls = _patch_executor_common(monkeypatch, SessionLocal, run_impl=_fake_run)
        try:
            # 不应抛出异常（_execute_job 的 FINAL_STATUSES 兜底也不应被触发）
            asyncio.run(ai_job_service._execute_diagnosis_summary_job(summary_id))
            assert calls["upsert"] == 0
        finally:
            ai_job_service._clear_cancel_event(summary_id)
    finally:
        engine.dispose()


def test_execute_task_chat_job_clears_cancel_event_after_run(monkeypatch):
    """执行入口 finally 必须回收取消事件，避免事件字典泄漏。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _user, _workspace, _task, summary = _prepare_summary_job(
                db, "ws-cancel-fin", "task-cancel-fin"
            )
            summary_id = summary.id
        ai_job_service._request_job_cancel(summary_id)

        async def _fake_run(*_args, **_kwargs):
            return {"text": "```json\n{\"summary\": \"x\"}\n```", "session_id": "s"}

        _patch_executor_common(monkeypatch, SessionLocal, run_impl=_fake_run)
        try:
            asyncio.run(ai_job_service._execute_task_chat_job(summary_id))
            assert ai_job_service._is_cancel_requested(summary_id) is False
            assert ai_job_service._JOB_CANCEL_EVENTS.get(summary_id) is None
        finally:
            ai_job_service._clear_cancel_event(summary_id)
    finally:
        engine.dispose()


# ────────────────────────── 会话/总结互斥 ──────────────────────────


def test_diagnosis_summary_rejected_while_chat_running(monkeypatch):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-mx-run", "task-mx-run")
            _add_job(db, workspace, task, user.id, status=AiJobStatus.RUNNING)
        client = TestClient(_build_app(SessionLocal, user, monkeypatch))
        resp = client.post(f"/api/workspaces/{workspace.id}/tasks/{task.id}/diagnosis-summary")
        assert resp.status_code == 409, resp.text
        assert "会话进行中" in resp.json()["detail"]
    finally:
        engine.dispose()


def test_diagnosis_summary_rejected_while_chat_waiting_hitl(monkeypatch):
    """WAITING_HITL（AI 暂停等输入）视为会话进行中，同样禁止总结。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-mx-hitl", "task-mx-hitl")
            _add_job(db, workspace, task, user.id, status=AiJobStatus.WAITING_HITL)
        client = TestClient(_build_app(SessionLocal, user, monkeypatch))
        resp = client.post(f"/api/workspaces/{workspace.id}/tasks/{task.id}/diagnosis-summary")
        assert resp.status_code == 409, resp.text
        assert "会话进行中" in resp.json()["detail"]
    finally:
        engine.dispose()


def test_diagnosis_summary_rejected_while_chat_pending(monkeypatch):
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-mx-pend", "task-mx-pend")
            _add_job(db, workspace, task, user.id, status=AiJobStatus.PENDING)
        client = TestClient(_build_app(SessionLocal, user, monkeypatch))
        resp = client.post(f"/api/workspaces/{workspace.id}/tasks/{task.id}/diagnosis-summary")
        assert resp.status_code == 409, resp.text
    finally:
        engine.dispose()


def test_chat_turn_rejected_while_summary_active():
    """总结进行中（PENDING）禁止创建新的聊天 turn。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-mx-sum", "task-mx-sum")
            _add_job(
                db,
                workspace,
                task,
                user.id,
                status=AiJobStatus.PENDING,
                job_kind="DIAGNOSIS_SUMMARY",
                queue_key=f"DIAGNOSIS_SUMMARY:{task.id}",
            )
            with pytest.raises(task_session_service.TaskSessionUndoError) as excinfo:
                asyncio.run(
                    task_session_service.create_task_chat_turn(
                        db,
                        task=task,
                        actor_user_id=user.id,
                        content="继续排查",
                    )
                )
            assert excinfo.value.code == "DIAGNOSIS_SUMMARY_BUSY"
    finally:
        engine.dispose()


def test_resume_interrupted_rejected_while_summary_active():
    """总结进行中禁止恢复被中断的会话。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-mx-resume", "task-mx-resume")
            task.status = TaskStatus.INTERRUPTED
            task.session_id = "source-session"
            db.commit()
            _add_job(db, workspace, task, user.id, status=AiJobStatus.INTERRUPTED)
            _add_job(
                db,
                workspace,
                task,
                user.id,
                status=AiJobStatus.RUNNING,
                job_kind="DIAGNOSIS_SUMMARY",
                queue_key=f"DIAGNOSIS_SUMMARY:{task.id}",
            )
            with pytest.raises(task_session_control_service.TaskSessionControlError) as excinfo:
                asyncio.run(
                    task_session_control_service.resume_interrupted_task(
                        db,
                        task=task,
                        actor_user_id=user.id,
                        prompt="继续",
                    )
                )
            assert excinfo.value.status_code == 409
    finally:
        engine.dispose()


def test_hitl_resume_rejected_while_summary_active(monkeypatch):
    """总结进行中禁止 HITL 回复恢复会话。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-mx-hitl2", "task-mx-hitl2")
            _add_job(db, workspace, task, user.id, status=AiJobStatus.WAITING_HITL)
            _add_job(
                db,
                workspace,
                task,
                user.id,
                status=AiJobStatus.RUNNING,
                job_kind="DIAGNOSIS_SUMMARY",
                queue_key=f"DIAGNOSIS_SUMMARY:{task.id}",
            )
        monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
        with pytest.raises(ai_job_service.AiJobConflictError):
            asyncio.run(
                ai_job_service.resume_waiting_hitl_job(
                    task_id=task.id,
                    response="继续",
                )
            )
    finally:
        engine.dispose()


def test_summary_still_allowed_after_chat_interrupted():
    """核心场景：会话被停止（任务 INTERRUPTED）后仍允许一键总结。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, "ws-mx-stop", "task-mx-stop")
            task.status = TaskStatus.INTERRUPTED
            db.commit()
            _add_job(db, workspace, task, user.id, status=AiJobStatus.INTERRUPTED)
            active_chat = ai_job_service.find_active_chat_job(db, task.id)
            assert active_chat is None
            assert ai_job_service.find_active_summary_job(db, task.id) is None
    finally:
        engine.dispose()
