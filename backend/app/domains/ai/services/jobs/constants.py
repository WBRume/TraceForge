"""AI 作业共享词汇：状态集合、作业类别、队列键与纯函数工具。"""

from __future__ import annotations

from typing import Any

from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.task.models.task import TaskStatus

ACTIVE_STATUSES = {
    AiJobStatus.PENDING,
    AiJobStatus.RUNNING,
    AiJobStatus.WAITING_HITL,
    AiJobStatus.INTERRUPTED,
    AiJobStatus.TERMINATING,
    AiJobStatus.ORPHANED,
}
FINAL_STATUSES = {AiJobStatus.SUCCESS, AiJobStatus.FAILED, AiJobStatus.CANCELLED, AiJobStatus.REVERTED}
BLOCKING_STATUSES = {
    AiJobStatus.RUNNING,
    AiJobStatus.WAITING_HITL,
    AiJobStatus.INTERRUPTED,
    AiJobStatus.TERMINATING,
    AiJobStatus.ORPHANED,
}
SESSION_GUARD_STATUSES = {
    AiJobStatus.PENDING,
    AiJobStatus.RUNNING,
    AiJobStatus.WAITING_HITL,
    AiJobStatus.TERMINATING,
    AiJobStatus.ORPHANED,
}
# 任务处于这些状态时，其聊天队列暂停取队（由停止/失败流程显式置入）。
TASK_QUEUE_PAUSED_STATUSES = {TaskStatus.INTERRUPTED, TaskStatus.FAILED}

JOB_KIND_THREAD_AI_REPLY = "THREAD_AI_REPLY"
JOB_KIND_RESOLUTION_PROPOSAL = "RESOLUTION_PROPOSAL"
JOB_KIND_RESOLUTION_REWRITE = "RESOLUTION_REWRITE"
JOB_KIND_DIAGNOSIS_SUMMARY = "DIAGNOSIS_SUMMARY"
JOB_KIND_TASK_BASELINE = "TASK_BASELINE"

# 队列键前缀（键格式：``<PREFIX>:<resource_id>``）。
QUEUE_KEY_TASK_CHAT = "TASK_CHAT"
QUEUE_KEY_ASSET_THREAD = "ASSET_THREAD"
QUEUE_KEY_DIAGNOSIS_SUMMARY = "DIAGNOSIS_SUMMARY"
QUEUE_KEY_TASK_BASELINE = "TASK_BASELINE"

# A productive turn can legitimately run longer than ten minutes now.  Stale
# cleanup must never race the hard runtime watchdog and mark a live job failed.
_TIMEOUT_TEXT_MARKERS = (
    "request timed out",
    "timed out",
    "timeout",
    "etimedout",
    "network timeout",
    "连接超时",
    "请求超时",
)


def as_status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def looks_like_timeout_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _TIMEOUT_TEXT_MARKERS)


def queue_key_for_task(task_id: str) -> str:
    return f"{QUEUE_KEY_TASK_CHAT}:{task_id}"


def queue_key_for_thread(thread_id: str) -> str:
    return f"{QUEUE_KEY_ASSET_THREAD}:{thread_id}"


def queue_key_for_diagnosis_summary(task_id: str) -> str:
    # 总结与聊天各自独立队列：任务 INTERRUPTED/FAILED 时聊天队列会暂停、
    # INTERRUPTED 会话 job 也会阻塞取队，若共用队列「停止会话→一键总结」
    # 将永远无法执行。会话/总结的互斥不由队列保证，而由创建期守卫保证：
    # 所有会话/总结创建入口都会拒绝对方处于进行中（PENDING/RUNNING/WAITING_HITL），
    # 因此同一任务同一时刻最多只有一个非终态 AI job 在执行。
    return f"{QUEUE_KEY_DIAGNOSIS_SUMMARY}:{task_id}"


def queue_key_for_task_baseline(task_id: str) -> str:
    return f"{QUEUE_KEY_TASK_BASELINE}:{task_id}"


def task_id_from_queue_key(queue_key: str) -> str | None:
    """从任务维度队列键中解析 task_id；非任务维度键返回 None。"""
    normalized = str(queue_key or "")
    prefixes = (f"{QUEUE_KEY_TASK_CHAT}:", f"{QUEUE_KEY_TASK_BASELINE}:")
    prefix = next((candidate for candidate in prefixes if normalized.startswith(candidate)), None)
    if prefix is None:
        return None
    task_id = normalized[len(prefix):].strip()
    return task_id or None
