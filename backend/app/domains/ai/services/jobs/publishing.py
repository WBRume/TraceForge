"""作业负载的对外发布：WS 广播、状态回放与入队入口。

广播规则（doc §5 C5/§9.2）：非终态（RUNNING/WAITING_HITL/TERMINATING/
ORPHANED/INTERRUPTED）只产生 ``*_update``；``*_done``/``*_failed`` 只允许
真正的 FINAL 状态。调用方无权覆盖 final 判定。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.ai.services.jobs import constants
from app.domains.ai.services.jobs.registry import runtime
from app.domains.ai.services.jobs.store import serialize_job
from app.domains.websocket.ws.manager import manager as task_ws_manager


async def broadcast_job_payload(payload: Dict[str, Any]) -> None:
    """Broadcast one job payload."""
    status = str(payload.get("status") or "")
    final = status in {item.value for item in constants.FINAL_STATUSES}
    channel = str(payload.get("channel") or "")
    if (payload.get('context_json') or {}).get('job_kind') == 'PLAYBOOK_PROMOTION':
        from app.domains.notification.ws.notification_manager import notification_ws_manager
        await notification_ws_manager.send_message_to_user(str(payload['creator_id']), {
            'type': 'playbook_promotion_updated', 'job_id': payload['id'], 'workspace_id': payload['workspace_id']})
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


def _load_job_payload_sync(job_id: str) -> Optional[Dict[str, Any]]:
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


def reschedule_if_pending(payload: Dict[str, Any]) -> None:
    """收敛结果把作业打回 PENDING（如重试入队）时立即唤醒对应队列 runner。"""
    if str(payload.get("status") or "") == AiJobStatus.PENDING.value:
        runtime.schedule_queue(str(payload.get("queue_key") or ""))


# ────────────────────────── 入队入口 ──────────────────────────


def _load_enqueue_state_sync(job_id: str, expected_channel: Optional[AiJobChannel]) -> Optional[Dict[str, Any]]:
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


async def enqueue_job(job_id: str, expected_channel: Optional[AiJobChannel] = None) -> Optional[Dict[str, Any]]:
    state = await run_db(_load_enqueue_state_sync, job_id, expected_channel)
    if state is None:
        return None
    payload = state["payload"]
    queue_key = state["queue_key"]

    await broadcast_job_payload(payload)
    if queue_key:
        runtime.schedule_queue(queue_key)
    return payload


async def enqueue_asset_thread_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await enqueue_job(job_id, expected_channel=AiJobChannel.ASSET_THREAD)


async def enqueue_task_chat_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)


async def publish_job(job_id: str) -> None:
    """Broadcast the durable job payload; final 判定由 payload 状态决定。"""
    await publish_job_state(job_id)


async def enqueue_task_baseline_job(
    *,
    workspace_id: str,
    task_id: str,
    creator_id: str,
) -> Optional[Dict[str, Any]]:
    from app.core.distributed_lock import lock_ai_queue
    from app.core.offload import run_db_txn
    from app.domains.ai.services.jobs.store import create_task_baseline_job

    key = constants.queue_key_for_task_baseline(task_id)
    # The durable row is the source of truth; the queue lock closes the
    # cross-process create/retry race before the database unique boundary is
    # reached, while the input revision in context makes the key explicit.
    async with lock_ai_queue(key):
        job_id = await run_db_txn(
            lambda db: create_task_baseline_job(
                db,
                workspace_id=workspace_id,
                task_id=task_id,
                creator_id=creator_id,
            ).id
        )
    return await enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)
