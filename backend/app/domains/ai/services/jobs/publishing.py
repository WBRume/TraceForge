"""作业负载的对外发布：WS 广播、状态回放与入队入口。

广播规则：非终态（RUNNING/WAITING_HITL/TERMINATING/
ORPHANED/INTERRUPTED）只产生 ``*_update``；``*_done``/``*_failed`` 只允许
真正的 FINAL 状态。调用方无权覆盖 final 判定。
"""

from __future__ import annotations

from typing import Any

from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.ai.services.jobs import constants
from app.domains.ai.services.jobs.registry import runtime
from app.domains.ai.services.jobs.store import serialize_job
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.websocket.ws.manager import manager as task_ws_manager


async def broadcast_job_payload(payload: dict[str, Any]) -> None:
    """Broadcast one job payload."""
    status = str(payload.get("status") or "")
    final = status in {item.value for item in constants.FINAL_STATUSES}
    channel = str(payload.get("channel") or "")
    if channel == AiJobChannel.BACKGROUND.value and (payload.get("context_json") or {}).get("job_kind") in {
        "SKILL_ANALYSIS",
        "API_MOCK",
        "PROVISION",
    }:
        await publish_domain_snapshot(str(payload["id"]))
        return
    if (payload.get("context_json") or {}).get("job_kind") in {
        "REQUIREMENT_IMPORT_PREVIEW",
        "REQUIREMENT_SPLIT_PREVIEW",
    }:
        from app.domains.notification.ws.notification_manager import notification_ws_manager

        context = payload.get("context_json") or {}
        await notification_ws_manager.send_message_to_user(
            str(payload["creator_id"]),
            {
                "type": "requirement_preview_updated",
                "job": {
                    "job_id": payload["id"],
                    "workspace_id": payload["workspace_id"],
                    "status": status,
                    "progress": payload.get("progress", 0),
                    "message": payload.get("message"),
                    "error": payload.get("error_message"),
                    "job_kind": context.get("job_kind"),
                    "requirement_id": context.get("requirement_id"),
                    "requirement_title": context.get("requirement_title"),
                    "domain_milestones": context.get("domain_milestones", []),
                },
            },
        )
    if (payload.get("context_json") or {}).get("job_kind") == "TASK_REPOSITORY_ADAPT":
        from app.core.distributed_lock import lock_task
        from app.core.offload import run_db_txn
        from app.domains.task.services.repository_updates.adaptation import settle

        if final or status == AiJobStatus.INTERRUPTED.value:
            if status == AiJobStatus.SUCCESS.value and (payload.get("context_json") or {}).get("auto_apply"):
                async with lock_task(str(payload["task_id"]), ttl=600, blocking_timeout=30):
                    await run_db_txn(lambda db: settle(db, payload["id"]))
            else:
                # Interrupt/stop callers may already hold the task lock. These
                # outcomes only settle the preview; they never install code.
                await run_db_txn(lambda db: settle(db, payload["id"]))
        await task_ws_manager.send_message_to_room(
            str(payload["task_id"]),
            WSMessage(
                type="task_repository_update",
                payload={"task_id": payload["task_id"], "job_id": payload["id"], "job_status": status},
            ),
        )
    if (payload.get("context_json") or {}).get("job_kind") == "PLAYBOOK_PROMOTION":
        from app.domains.notification.ws.notification_manager import notification_ws_manager

        await notification_ws_manager.send_message_to_user(
            str(payload["creator_id"]),
            {
                "type": "playbook_promotion_updated",
                "job_id": payload["id"],
                "workspace_id": payload["workspace_id"],
                "status": status,
                "review_state": (payload.get("result_json") or {}).get("review_state"),
            },
        )
        return
    if channel == AiJobChannel.ASSET_THREAD.value:
        asset_id = str(payload.get("asset_id") or "")
        if not asset_id:
            return
        await asset_discussion_ws_manager.broadcast(
            asset_id,
            {
                "type": "ai_job_update",
                "asset_id": asset_id,
                "thread_id": payload.get("thread_id"),
                "job": payload,
            },
        )
        if final:
            done_type = "ai_job_done" if status == AiJobStatus.SUCCESS.value else "ai_job_failed"
            await asset_discussion_ws_manager.broadcast(
                asset_id,
                {
                    "type": done_type,
                    "asset_id": asset_id,
                    "thread_id": payload.get("thread_id"),
                    "job": payload,
                    "error": payload.get("error_message"),
                },
            )
        return

    if channel == AiJobChannel.TASK_CHAT.value:
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            return
        if (payload.get("context_json") or {}).get("job_kind") == "TASK_BASELINE":
            from app.domains.task.services.task_cli_state_service import publish_bootstrap_snapshot

            await publish_bootstrap_snapshot(task_id)
        if status in {"SUCCESS", "FAILED", "CANCELLED", "INTERRUPTED", "ORPHANED"}:
            from app.domains.workspace_collaboration.hooks import settle_job

            await settle_job(str(payload["id"]))
        await task_ws_manager.send_message_to_room(
            task_id,
            WSMessage(
                type="chat_job_update",
                payload={"task_id": task_id, "job": payload},
            ),
        )
        if final:
            done_type = "chat_job_done" if status == AiJobStatus.SUCCESS.value else "chat_job_failed"
            await task_ws_manager.send_message_to_room(
                task_id,
                WSMessage(
                    type=done_type,
                    payload={
                        "task_id": task_id,
                        "job": payload,
                        "error": payload.get("error_message"),
                    },
                ),
            )
            # 公开 READ 分享页的实时 nudge：chat 作业终态意味着助手回复已落库
            from app.domains.websocket.ws.public_share_manager import (
                notify_task_shares_history_changed,
            )

            await notify_task_shares_history_changed(task_id)


async def publish_domain_snapshot(job_id: str) -> None:
    from app.domains.notification.ws.notification_manager import notification_ws_manager

    def load():
        with SessionLocal() as db:
            job = db.get(SddAiJob, job_id)
            if job is None:
                return None
            if job.queue_source == "api_mock":
                from app.domains.api_mock.models.api_mock import SddApiMockJob
                from app.domains.api_mock.services.api_mock.job_service import _serialize_job

                row = db.get(SddApiMockJob, job_id)
                return ("api_mock", row.project_id, _serialize_job(row)) if row else None
            if job.queue_source == "skill_analysis":
                from app.domains.skill.models.skill import SddSkillAnalysis
                from app.domains.skill.services.skill_analysis_service import serialize_analysis

                row = db.get(SddSkillAnalysis, job_id)
                from app.domains.skill.services.catalog import policy as skill_policy
                from app.domains.workspace.services import workspace_service

                if not row or not workspace_service.get_workspace_member(db, row.workspace_id, job.creator_id):
                    return None
                if not row.skill or not skill_policy.ensure_skill_visible_in_workspace(row.skill, row.workspace_id):
                    return None
                return ("skill_analysis", job.creator_id, serialize_analysis(row)) if row else None
            return None

    snapshot = await run_db(load)
    if snapshot is None:
        return
    kind, recipient, data = snapshot
    from fastapi.encoders import jsonable_encoder

    data = jsonable_encoder(data)
    if kind == "api_mock":
        from app.domains.api_mock.ws.api_mock_manager import api_mock_ws_manager

        final = data["status"] in {s.value for s in constants.FINAL_STATUSES}
        await api_mock_ws_manager.broadcast_job_state(
            recipient,
            {
                "type": "job_done" if final else "job_update",
                "project_id": recipient,
                "job": data,
            },
        )
    else:
        await notification_ws_manager.send_message_to_user(
            recipient, {"type": "skill_analysis_updated", "analysis": data}
        )


async def publish_pending_job_events() -> int:
    """Retry committed notifications after a worker or transport failure.

    Duplicate delivery is expected: snapshots carry monotonically increasing
    versions. Delivery never re-executes a business operation.
    """
    from datetime import datetime

    from app.domains.ai.models.job_history import JobEvent

    def pending():
        with SessionLocal() as db:
            return [
                (e.id, e.job_id)
                for e in db.query(JobEvent)
                .filter(
                    JobEvent.published_at.is_(None),
                )
                .order_by(JobEvent.created_at, JobEvent.id)
                .limit(100)
                .all()
            ]

    count = 0
    for event_id, job_id in await run_db(pending):
        payload = await run_db(_load_job_payload_sync, job_id)
        if payload:
            await broadcast_job_payload(payload)

        def acknowledge(event_id=event_id):
            with SessionLocal() as db:
                db.query(JobEvent).filter_by(id=event_id).update({"published_at": datetime.utcnow()})
                db.commit()

        await run_db(acknowledge)
        count += 1
    return count


def _load_job_payload_sync(job_id: str) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        return serialize_job(job)
    finally:
        db.close()


async def publish_job_state(job_id: str) -> None:
    payload = await run_db(_load_job_payload_sync, job_id)
    if not payload:
        return
    await broadcast_job_payload(payload)


def reschedule_if_pending(payload: dict[str, Any]) -> None:
    """收敛结果把作业打回 PENDING（如重试入队）时立即唤醒对应队列 runner。"""
    if str(payload.get("status") or "") == AiJobStatus.PENDING.value:
        runtime.schedule_queue(str(payload.get("queue_key") or ""))


# ────────────────────────── 入队入口 ──────────────────────────


def _load_enqueue_state_sync(job_id: str, expected_channel: AiJobChannel | None) -> dict[str, Any] | None:
    """入队前置查询（线程内执行，由 run_db 包装）。"""
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        if expected_channel and job.channel != expected_channel:
            raise ValueError(f"Job {job_id} channel mismatch")
        return {
            "payload": serialize_job(job),
            "queue_key": job.queue_key,
        }
    finally:
        db.close()


async def enqueue_job(job_id: str, expected_channel: AiJobChannel | None = None) -> dict[str, Any] | None:
    state = await run_db(_load_enqueue_state_sync, job_id, expected_channel)
    if state is None:
        return None
    payload = state["payload"]
    queue_key = state["queue_key"]

    await broadcast_job_payload(payload)
    if queue_key:
        runtime.schedule_queue(queue_key)
    return payload


async def enqueue_asset_thread_job(job_id: str) -> dict[str, Any] | None:
    return await enqueue_job(job_id, expected_channel=AiJobChannel.ASSET_THREAD)


async def enqueue_task_chat_job(job_id: str) -> dict[str, Any] | None:
    return await enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)


async def publish_job(job_id: str) -> None:
    """Broadcast the durable job payload; final 判定由 payload 状态决定。"""
    await publish_job_state(job_id)


async def enqueue_task_baseline_job(
    *,
    workspace_id: str,
    task_id: str,
    creator_id: str,
) -> dict[str, Any] | None:
    from app.core.distributed_lock import lock_ai_queue
    from app.core.offload import run_db_txn
    from app.domains.ai.services.jobs.store import create_task_baseline_job

    key = constants.queue_key_for_task_baseline(task_id)
    # The durable row is the source of truth; the queue lock closes the
    # cross-process create/retry race before the database unique boundary is
    # reached, while the input revision in context makes the key explicit.
    async with lock_ai_queue(key):
        job_id = await run_db_txn(
            lambda db: (
                create_task_baseline_job(
                    db,
                    workspace_id=workspace_id,
                    task_id=task_id,
                    creator_id=creator_id,
                ).id
            )
        )
    return await enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)
