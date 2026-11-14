"""Verify a task's native session once per committed address change."""

import asyncio

from app.agents.errors import AgentError
from app.agents.selection import default_backend_name, normalize_backend_name, resolve_workspace_backend
from app.agents.service_binding import SERVER_AGENTS, agent_address_generation, configured_service, same_directory
from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.domains.auth.models.user import Workspace
from app.domains.local_resource.service import is_local
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services.task_workspace.repositories import resolve_task_cli_dir

UNAVAILABLE = "原 Agent 会话在当前服务上不可用。历史记录仍可查看。新建会话后，请重新提供所需背景。"
SESSION_CHECK_FAILED = "Agent 服务连接异常"
CONTINUABLE_STATUSES = (
    TaskStatus.RUNNING,
    TaskStatus.ROUND_COMPLETED,
    TaskStatus.AWAITING_INPUT,
    TaskStatus.INTERRUPTED,
)
SESSION_CHECK_CONCURRENCY = 4
logger = get_logger(__name__, category="task_execution")
_primed_versions: dict[str, int] = {}
_priming_versions: set[tuple[str, int]] = set()


class SessionSwitchError(ValueError):
    def __init__(self, *, changed=False, key=None):
        super().__init__("Agent 会话或服务配置已变更，请重新发送消息" if changed else UNAVAILABLE)
        self.code = "AGENT_SESSION_CHANGED" if changed else "AGENT_SESSION_UNAVAILABLE"
        self.key = key


def session_key(backend, generation, session_id, directory):
    return {"backend": backend, "generation": generation, "session_id": session_id, "directory": directory}


def _target(db, task_id, *, preview=False):
    task = db.get(SddTask, task_id)
    if not task or not task.session_id or is_local(task):
        return None
    if preview and (task.status not in CONTINUABLE_STATUSES or task.baselined_at is not None):
        return None
    backend = task.agent_backend or resolve_workspace_backend(db, task.workspace_id)
    if backend not in SERVER_AGENTS:
        return None
    generation = agent_address_generation(db, backend)
    if not generation:
        return None
    return _verification_target(db, task, backend, generation)


def _verification_target(db, task, backend, generation):
    key = session_key(backend, generation, task.session_id, resolve_task_cli_dir(db, task))
    previous = task.agent_session_verification or {}
    return key, previous.get("key") == key and previous.get("status") == "verified"


def _owned_by_task(db, task_id, key):
    # Task.session_id is the authoritative association. Also reject an ID
    # currently bound to another task on the same provider and directory.
    return (
        not db.query(SddTask.id)
        .filter(
            SddTask.id != task_id,
            SddTask.agent_backend == key["backend"],
            SddTask.project_path == key["directory"],
            SddTask.session_id == key["session_id"],
        )
        .first()
    )


def _record_verified(db, task_id, key):
    target = _target(db, task_id)
    if not target or target[0] != key:
        return False
    db.get(SddTask, task_id).agent_session_verification = {"key": key, "status": "verified"}
    return True


async def inspect_native_session(service, key):
    adapter = None
    try:
        adapter = service.adapter()
        async with asyncio.timeout(8):
            native = await adapter.native_session(key["session_id"])
        if native and not native.get("directory"):
            raise ValueError("Agent did not report a session directory")
        return (
            "verified"
            if native
            and native.get("readable", True)
            and same_directory(
                native["directory"],
                key["directory"],
            )
            else "unavailable"
        )
    finally:
        if adapter:
            await adapter.close()


async def check_task_session(task_id, *, new_session=False, run_txn=run_db_txn, preview=False, expected_version=None):
    """Check a pending address change under the task lock.

    A key with no status records a failed probe for this turn only. The worker
    settles that turn through the ordinary interruption path.
    """
    target = await run_txn(lambda db: _target(db, task_id, preview=preview))
    if not target:
        if new_session:
            raise SessionSwitchError(changed=True)
        return None, None
    key, verified = target
    if expected_version is not None and (key["backend"], key["generation"]) != expected_version:
        return None, None
    status = "verified" if verified else None
    if not verified:
        service, owned = await run_txn(
            lambda db: (configured_service(db, key["backend"]), _owned_by_task(db, task_id, key))
        )
        if service.generation == key["generation"]:
            try:
                status = await inspect_native_session(service, key) if owned else "unavailable"
            except Exception:
                pass
        if status == "verified":
            if not await run_txn(lambda db: _record_verified(db, task_id, key)):
                status = None
        elif status == "unavailable" and await run_txn(lambda db: _target(db, task_id, preview=preview)) != target:
            status = None
    if status == "unavailable" and not new_session:
        raise SessionSwitchError(key=key)
    if new_session and status != "unavailable":
        raise SessionSwitchError(changed=True)
    return key, status


async def preview_task_session(task_id, run_txn, *, expected_version=None):
    try:
        async with lock_task(task_id, blocking_timeout=1):
            return await check_task_session(task_id, run_txn=run_txn, preview=True, expected_version=expected_version)
    except SessionSwitchError as exc:
        return exc.key, "unavailable"
    except LockAcquireTimeout:
        pass
    return None, None


def _pending_sessions(db, backend, generation, excluded_task_id, after):
    if agent_address_generation(db, backend) != generation:
        return [], None
    tasks = (
        db.query(SddTask, Workspace.agent_backend)
        .join(Workspace, Workspace.id == SddTask.workspace_id)
        .filter(
            SddTask.id > after,
            SddTask.id != excluded_task_id,
            (SddTask.agent_backend == backend) | SddTask.agent_backend.is_(None),
            SddTask.session_id.is_not(None),
            SddTask.execution_location != "LOCAL",
            SddTask.baselined_at.is_(None),
            SddTask.status.in_(CONTINUABLE_STATUSES),
        )
        .order_by(SddTask.id)
        .limit(100)
        .all()
    )
    pending = [
        task.id
        for task, workspace_backend in tasks
        if (task.agent_backend or normalize_backend_name(workspace_backend) or default_backend_name()) == backend
        and not _verification_target(db, task, backend, generation)[1]
    ]
    return pending, tasks[-1][0].id if len(tasks) == 100 else None


async def prime_session_version(key, task_id, run_txn):
    """Share positive checks for existing sessions under the same service version."""
    backend, generation = key["backend"], key["generation"]
    identity = (backend, generation)
    if _primed_versions.get(backend, 0) >= generation or identity in _priming_versions:
        return
    _priming_versions.add(identity)
    try:
        cursor = ""
        while cursor is not None:
            pending, cursor = await run_txn(
                lambda db, after=cursor: _pending_sessions(db, backend, generation, task_id, after)
            )
            for start in range(0, len(pending), SESSION_CHECK_CONCURRENCY):
                await asyncio.gather(
                    *(
                        preview_task_session(candidate, run_txn, expected_version=identity)
                        for candidate in pending[start : start + SESSION_CHECK_CONCURRENCY]
                    )
                )
        _primed_versions[backend] = max(generation, _primed_versions.get(backend, 0))
    except Exception:
        logger.exception("Agent session verification batch failed: backend={}, generation={}", backend, generation)
    finally:
        _priming_versions.discard(identity)


async def verify_pending_dispatch(service, task_id, key, *, failed_check=None):
    if failed_check == key:
        raise AgentError(SESSION_CHECK_FAILED)
    owned = await run_db_txn(lambda db: _owned_by_task(db, task_id, key))
    try:
        status = await inspect_native_session(service, key) if owned else "unavailable"
    except Exception:
        raise AgentError(SESSION_CHECK_FAILED) from None
    if status == "unavailable":
        raise SessionSwitchError
    await run_db_txn(lambda db: _record_verified(db, task_id, key))


def verified_for_dispatch(task, service, session_id):
    if not session_id or not service.generation:
        return True
    verification = task.agent_session_verification or {}
    key = session_key(service.name, service.generation, session_id, str(task.project_path or "").strip() or ".")
    return verification.get("key") == key and verification.get("status") == "verified"


def replace_session_in_txn(db, task, check, submission):
    target = _target(db, task.id)
    if not target or target != (check, False):
        raise SessionSwitchError(changed=True)
    task.session_generation += 1
    task.session_id = None
    task.agent_session_verification = None
    if submission is not None:
        submission.session_generation = task.session_generation
    return task.session_generation
