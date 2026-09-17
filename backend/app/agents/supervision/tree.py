"""受管进程树的三态采样（executor 侧纯同步函数，绝不入事件循环）。

:func:`inspect_process_tree_snapshot` 是受管进程（含 Windows Job Object /
POSIX 进程组 containment）的离环采样实现，由 :mod:`...inspection` 的
bounded executor 执行。三态聚合规则（doc §5.4.3）：

- 任一 identity 明确存活 -> LIVE；
- 无存活但存在 UNKNOWN（探测异常/Job Object 查询失败/无 psutil 能力）
  -> UNKNOWN，known_descendant_pids 必须全部保留；
- 仅当 root 明确退出、所有已登记 identity 明确不存在且 containment
  明确为空时 -> CONFIRMED_DEAD。
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.agents.supervision import windows
from app.agents.supervision.model import ProcessProbeState, ProcessTreeSnapshot


def windows_job_probe(managed) -> Tuple[ProcessProbeState, set]:
    """Probe Windows Job Object containment (executor-side only).

    - 查询成功且为空集合：该 containment 的明确空证据（CONFIRMED_DEAD）；
    - 查询失败：UNKNOWN，绝不返回 False（doc §5.4.2）；
    - 没有 Job Object：无 containment 可查，返回 CONFIRMED_DEAD（空证据，
      死亡证明由 root returncode + known identities + group probe 决定）。
    """
    if os.name != "nt" or not managed.job_handle:
        return (ProcessProbeState.CONFIRMED_DEAD, set())
    try:
        pids = windows.query_job_process_ids(
            int(managed.job_handle), exclude_pid=int(managed.pid)
        )
        if pids is None:
            return (ProcessProbeState.UNKNOWN, set())
        return (ProcessProbeState.LIVE, pids) if pids else (ProcessProbeState.CONFIRMED_DEAD, set())
    except Exception:
        return (ProcessProbeState.UNKNOWN, set())


def posix_group_probe(managed) -> Tuple[ProcessProbeState, set]:
    """Probe the POSIX process group containment (executor-side only)."""
    if os.name == "nt" or not managed.process_group_id:
        return (ProcessProbeState.CONFIRMED_DEAD, set())
    group_id = int(managed.process_group_id)
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return (ProcessProbeState.CONFIRMED_DEAD, set())
    except (PermissionError, OSError, ValueError):
        # The group may still exist; a permission failure is never a death proof.
        return (ProcessProbeState.UNKNOWN, set())
    if psutil is None:
        return (ProcessProbeState.LIVE, {group_id})
    pids: set = set()
    try:
        for proc in psutil.process_iter(["pid", "status"]):
            try:
                if proc.status() == psutil.STATUS_ZOMBIE:
                    continue
                if os.getpgid(proc.pid) == group_id:
                    pids.add(int(proc.pid))
            except (psutil.Error, OSError, ValueError):
                continue
    except (psutil.Error, OSError, ValueError):
        return (ProcessProbeState.UNKNOWN, set())
    return (ProcessProbeState.LIVE, pids)


def probe_known_pid(pid: int) -> ProcessProbeState:
    """Three-state probe of one known immutable identity (doc §5.4.2)."""
    if psutil is None:
        return ProcessProbeState.UNKNOWN
    try:
        proc = psutil.Process(int(pid))
    except psutil.NoSuchProcess:
        # 该特定 identity 明确不存在。
        return ProcessProbeState.CONFIRMED_DEAD
    except psutil.ZombieProcess:
        # 明确的已退出语义（doc §5.4.2）。
        return ProcessProbeState.CONFIRMED_DEAD
    except psutil.AccessDenied:
        return ProcessProbeState.UNKNOWN
    except (psutil.Error, OSError, ValueError):
        return ProcessProbeState.UNKNOWN
    try:
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            return ProcessProbeState.LIVE
        return ProcessProbeState.CONFIRMED_DEAD
    except psutil.ZombieProcess:
        return ProcessProbeState.CONFIRMED_DEAD
    except (psutil.Error, OSError, ValueError):
        return ProcessProbeState.UNKNOWN


def inspect_process_tree_snapshot(managed) -> ProcessTreeSnapshot:
    """Pure synchronous psutil snapshot; never call directly from the event loop.

    三态聚合规则（doc §5.4.3）：任一 identity 明确存活 -> LIVE；没有存活
    但存在 UNKNOWN -> UNKNOWN；仅当 root 明确退出、所有已登记 identity
    明确不存在且 containment 明确为空时 -> CONFIRMED_DEAD。
    """
    root_return_code = getattr(managed.process, "returncode", None)
    root_alive = root_return_code is None
    root_pid = int(managed.pid)
    live: set = set()
    unknown: set = set()
    # containment（Job Object / POSIX 进程组）探测不确定：即使没有可填写
    # 的 UNKNOWN PID 也必须保持 UNKNOWN 状态（doc 审计 P0-3A）。
    containment_unknown = False
    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    root_identity_matches: Optional[bool] = None

    if psutil is None:
        if root_alive:
            return ProcessTreeSnapshot(
                state=ProcessProbeState.LIVE,
                root_return_code=None,
                remaining_pids=(root_pid,),
            )
        return ProcessTreeSnapshot(
            state=ProcessProbeState.UNKNOWN,
            root_return_code=root_return_code,
            failure_code="PROCESS_INSPECTION_UNAVAILABLE",
            error_message="psutil is unavailable; descendant death cannot be confirmed",
        )

    # 1. Windows Job Object containment。
    job_state, job_pids = windows_job_probe(managed)
    if job_state == ProcessProbeState.LIVE:
        live.update(job_pids)
    elif job_state == ProcessProbeState.UNKNOWN:
        containment_unknown = True
        failure_code = failure_code or "JOB_OBJECT_QUERY_FAILED"
        error_message = error_message or "Windows Job Object query failed; containment unknown"

    # 2. POSIX process group containment。
    group_state, group_pids = posix_group_probe(managed)
    if group_state == ProcessProbeState.LIVE:
        live.update(group_pids)
    elif group_state == ProcessProbeState.UNKNOWN:
        containment_unknown = True
        failure_code = failure_code or "PROCESS_GROUP_UNKNOWN"
        error_message = error_message or "POSIX process group probe failed; containment unknown"

    # 3. Root liveness（asyncio returncode 是 root 存活/退出的权威来源）。
    if root_alive:
        live.add(root_pid)
        try:
            proc = psutil.Process(root_pid)
            if managed.process_start_time is not None:
                root_identity_matches = (
                    abs(float(proc.create_time()) - managed.process_start_time) <= 2.0
                )
            else:
                root_identity_matches = True
        except (psutil.Error, OSError, ValueError):
            root_identity_matches = None

    # 4. 已登记 immutable identities。
    for pid in list(managed.known_descendant_pids):
        if pid == root_pid or pid in live:
            continue
        probe = probe_known_pid(int(pid))
        if probe == ProcessProbeState.LIVE:
            live.add(int(pid))
        elif probe == ProcessProbeState.UNKNOWN:
            unknown.add(int(pid))
            failure_code = failure_code or "PROCESS_TREE_UNKNOWN"
            error_message = error_message or f"Descendant pid {int(pid)} could not be probed"

    # 5. Root 存活时枚举后代（root 已退出时无法枚举，包含关系由上面两项决定）。
    if root_alive:
        try:
            root = psutil.Process(root_pid)
            for child in root.children(recursive=True):
                live.add(int(child.pid))
        except psutil.NoSuchProcess:
            pass
        except (psutil.Error, OSError, ValueError):
            failure_code = failure_code or "PROCESS_TREE_UNKNOWN"
            error_message = error_message or "Root child enumeration failed"

    if live:
        state = ProcessProbeState.LIVE
    elif unknown or containment_unknown:
        # 任一存活 -> LIVE；没有存活但存在 UNKNOWN（探测异常或 containment
        # 无法核实）-> UNKNOWN；只有全部来源明确死亡才允许 CONFIRMED_DEAD。
        state = ProcessProbeState.UNKNOWN
    else:
        state = ProcessProbeState.CONFIRMED_DEAD
    return ProcessTreeSnapshot(
        state=state,
        live_descendant_pids=tuple(sorted(p for p in live if p != root_pid)),
        unknown_descendant_pids=tuple(sorted(unknown)),
        root_return_code=root_return_code,
        root_identity_matches=root_identity_matches,
        remaining_pids=tuple(sorted(live)),
        failure_code=failure_code if state != ProcessProbeState.CONFIRMED_DEAD else None,
        error_message=error_message if state != ProcessProbeState.CONFIRMED_DEAD else None,
    )
