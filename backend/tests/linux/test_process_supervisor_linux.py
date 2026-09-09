"""Linux persisted process supervisor 验收（doc 修复方案 §5/§6/§7/§12.1）。

覆盖：
- P0-1：root PID 消失但同 PGID 子进程仍存活时，绝不允许 confirmed_dead=True；
- P0-2：权限/探测错误与不完整 token 扫描只能产生 UNKNOWN；
- P1-1：persisted/reaper 的进程检查不阻塞事件循环；
- PID/PGID 复用保护：不误杀复用 PID；
- token 精确匹配：只杀目标 token，不碰同 UID 的其他进程。

所有真实进程测试：
- 使用短超时轮询，不使用无界 sleep()；
- 在 finally 中对明确的测试 PGID 执行清理；
- 绝不向当前 pytest 进程组发送信号；
- 先断言 pgid == spawned_root_pid，再执行 killpg()；
- 为 PID/PGID 复用保留 create-time 校验。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psutil
import pytest

import app.agents.process_supervisor as supervisor_module
from app.agents.process_supervisor import (
    PROCESS_GROUP_UNKNOWN,
    PROCESS_TREE_UNKNOWN,
    TOKEN_DISCOVERY_UNKNOWN,
    ProcessProbeState,
    process_supervisor,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="requires Linux /proc and POSIX process-group semantics",
)


def kill_test_group(pgid: int) -> None:
    """Safety-capped cleanup helper: never signal the pytest process group."""
    if pgid <= 1 or pgid == os.getpgrp():
        raise AssertionError(f"unsafe test pgid: {pgid}")
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# wrapper 先 fork child 再立即退出：child 留在 wrapper 创建的进程组中
# （doc §3.3 的 Linux 真实复现）。
_WRAPPER_SOURCE = """
import os, time
child = os.fork()
if child == 0:
    os.close(1)
    os.close(2)
    time.sleep(120)
    os._exit(0)
print(child, flush=True)
os._exit(0)
"""

_SLEEP_SOURCE = "import time; time.sleep(120)"


def _spawn_wrapper_tree() -> tuple[subprocess.Popen, int, int]:
    proc = subprocess.Popen(
        [sys.executable, "-c", _WRAPPER_SOURCE],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    root_pid = proc.pid
    child_pid = int(proc.stdout.readline().strip())
    proc.wait(timeout=5)
    # 等待 root PID 明确消失，同时组仍存活。
    assert _wait_until(lambda: not _pid_alive(root_pid)), "wrapper did not exit"
    assert _pid_alive(child_pid), "child died unexpectedly"
    assert os.getpgid(child_pid) == root_pid, "child left the wrapper process group"
    return proc, root_pid, child_pid


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


@pytest.mark.asyncio
async def test_stop_persisted_root_gone_does_not_confirm_live_group_dead():
    """P0-1：root 消失 + 同 PGID child 存活 → child 被终止后才允许死亡证明。"""
    proc, root_pid, child_pid = _spawn_wrapper_tree()
    try:
        assert _pid_alive(child_pid)
        result = await process_supervisor.stop_persisted(
            root_pid,
            datetime.now(timezone.utc),
            "linux-audit-reap",
            process_group_id=root_pid,
        )
        # 修复后只允许两种结果：
        if result.confirmed_dead is True:
            # a. group 被完整终止后才有死亡证明。
            with pytest.raises(ProcessLookupError):
                os.killpg(root_pid, 0)
        else:
            # b. 探测无法完成时必须是 UNKNOWN，绝不能是 False/True。
            assert result.confirmed_dead is None
            assert result.error_code in {"PROCESS_GROUP_UNKNOWN", PROCESS_TREE_UNKNOWN}
    finally:
        kill_test_group(root_pid)


@pytest.mark.asyncio
async def test_group_permission_error_is_unknown_not_dead(monkeypatch):
    """P0-2：killpg 权限错误 → UNKNOWN，不清 ownership（doc §6.3）。"""
    missing_pid = _find_absent_pid()
    known_group = _find_absent_pid()
    monkeypatch.setattr(
        os,
        "killpg",
        lambda *_args, **_kw: (_ for _ in ()).throw(PermissionError()),
    )
    result = await process_supervisor.verify_persisted_cleanup(
        missing_pid,
        datetime.now(timezone.utc),
        known_group,
    )
    assert result.confirmed_dead is None
    assert result.error_code == PROCESS_GROUP_UNKNOWN


@pytest.mark.asyncio
async def test_stop_persisted_group_permission_error_is_unknown_not_dead(monkeypatch):
    """stop 路径同样不允许把权限错误折叠成死亡证明。"""
    proc, root_pid, child_pid = _spawn_wrapper_tree()
    try:
        monkeypatch.setattr(
            os,
            "killpg",
            lambda *_args, **_kw: (_ for _ in ()).throw(PermissionError()),
        )
        result = await process_supervisor.stop_persisted(
            root_pid,
            datetime.now(timezone.utc),
            "linux-audit-reap",
            process_group_id=root_pid,
        )
        assert result.confirmed_dead is None
        assert result.error_code in {PROCESS_GROUP_UNKNOWN, PROCESS_TREE_UNKNOWN}
        # child 未被误杀（没有任何信号发送过）。
        assert _pid_alive(child_pid)
    finally:
        # 先恢复 killpg，再清理进程组（cleanup 依赖真实 killpg）。
        monkeypatch.undo()
        kill_test_group(root_pid)


class _FakeProcess:
    """psutil.Process stand-in for token-scan exception classification.

    fake 是“可识别命令”的同 UID 进程（cmdline 带 marker）：这是 marker
    预过滤后仍然必须读 environ 的目标类。
    """

    def __init__(self, *, pid: int, environ_error: BaseException | None = None):
        self.pid = pid
        self._environ_error = environ_error

    def uids(self):
        return SimpleNamespace(real=os.getuid())

    def cmdline(self):
        return ["claude", "--fake-process"]

    def create_time(self):
        return time.time()

    def environ(self):
        if self._environ_error is not None:
            raise self._environ_error
        return {}


def _find_absent_pid() -> int:
    candidate = os.getpid() + 100000
    while _pid_alive(candidate) or candidate == os.getpid():
        candidate += 1
    return candidate


class _MarkerlessFakeProcess:
    """Same-UID system process (sd-pam shape): readable cmdline, no marker."""

    def __init__(self, *, pid: int, create_time: float | None = None):
        self.pid = pid
        self._create_time = create_time

    def uids(self):
        return SimpleNamespace(real=os.getuid())

    def cmdline(self):
        return ["(sd-pam)"]

    def create_time(self):
        if self._create_time is None:
            raise psutil.AccessDenied(self.pid)
        return self._create_time

    def environ(self):
        raise psutil.AccessDenied(self.pid)


@pytest.mark.asyncio
async def test_markerless_environ_unreadable_requires_verifiable_boundary(monkeypatch):
    """P0-2（修正过强假设）：markerless + environ 不可读的同 UID 进程只有
    在“启动时间早于本 attempt”可验证时才可排除；命令名不是归属证据。
    """
    fake = _MarkerlessFakeProcess(pid=_find_absent_pid(), create_time=time.time())
    monkeypatch.setattr(psutil, "process_iter", lambda *_a, **_kw: iter([fake]))

    # 无可信边界：无法证明该进程不属于本 attempt → UNKNOWN（正确性优先）。
    result = await process_supervisor.stop_by_run_token_discovery("token-1", "test")
    assert result is not None
    assert result.confirmed_dead is None
    assert result.error_code == TOKEN_DISCOVERY_UNKNOWN
    assert fake.pid in result.remaining_pids

    # 可验证边界：create time 严格早于 not_before → 可安全排除，扫描完整。
    result2 = await process_supervisor.stop_by_run_token_discovery(
        "token-1",
        "test",
        not_before=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert result2 is not None
    assert result2.confirmed_dead is True


@pytest.mark.asyncio
async def test_token_environ_access_denied_invalidates_empty_scan(monkeypatch):
    """P0-2：同 UID 进程 environ 不可读 → UNKNOWN，double-empty 不是死亡证明。"""
    fake_pid = _find_absent_pid()
    fakes = [
        _FakeProcess(pid=fake_pid, environ_error=psutil.AccessDenied(fake_pid)),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda *_a, **_kw: iter(fakes))

    result = await process_supervisor.stop_by_run_token_discovery("token-1", "test")
    assert result is not None
    assert result.confirmed_dead is None
    assert result.error_code == TOKEN_DISCOVERY_UNKNOWN
    assert fake_pid in result.remaining_pids


@pytest.mark.asyncio
async def test_token_scan_process_disappeared_is_not_global_unknown(monkeypatch):
    """单个 PID 在扫描中 NoSuchProcess 属正常消失，不得让整个扫描 UNKNOWN。"""
    fake_pid = _find_absent_pid()
    fakes = [
        _FakeProcess(
            pid=fake_pid,
            environ_error=psutil.NoSuchProcess(fake_pid),
        ),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda *_a, **_kw: iter(fakes))

    result = await process_supervisor.stop_by_run_token_discovery("token-1", "test")
    assert result is not None
    # 消失进程被跳过 → 完整空扫描 → 合法死亡证明。
    assert result.confirmed_dead is True


@pytest.mark.asyncio
async def test_token_process_iter_failure_is_global_unknown(monkeypatch):
    """process_iter 本身失败 → 整个快照 UNKNOWN。"""
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda *_a, **_kw: (_ for _ in ()).throw(psutil.Error("proc table broken")),
    )
    result = await process_supervisor.stop_by_run_token_discovery("token-1", "test")
    assert result is not None
    assert result.confirmed_dead is None
    assert result.error_code == TOKEN_DISCOVERY_UNKNOWN


@pytest.mark.asyncio
async def test_stop_by_run_token_discovery_kills_exact_token_target():
    """token 精确匹配：只杀目标 token，不杀同 UID 的其他测试进程。"""
    token = f"linux-audit-{os.getpid()}-{time.time_ns()}"
    # P0-2：调用方必须提供受信任的 attempt 时间边界（生产 reaper 传
    # job_started_at）；边界之前的同 UID 系统进程（sd-pam 等）被可验证地
    # 排除，普通工具子进程（无 marker）仍会被精确匹配。
    not_before = datetime.now(timezone.utc)
    target = subprocess.Popen(
        [sys.executable, "-c", _SLEEP_SOURCE, "traceforge-marker"],
        start_new_session=True,
        env={**os.environ, "TRACEFORGE_RUN_TOKEN": token},
    )
    control = subprocess.Popen(
        [sys.executable, "-c", _SLEEP_SOURCE, "unrelated-guard"],
        start_new_session=True,
    )
    target_pgid = os.getpgid(target.pid)
    control_pgid = os.getpgid(control.pid)
    try:
        assert target_pgid == target.pid
        assert _wait_until(lambda: _token_visible(token)), "token process not visible"
        result = await process_supervisor.stop_by_run_token_discovery(
            token, "test", not_before=not_before
        )
        assert result is not None
        assert result.confirmed_dead is True
        # SIGKILL 后的僵尸进程仍留在组内；先收割目标子进程再断言组消失。
        try:
            target.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        with pytest.raises(ProcessLookupError):
            os.killpg(target_pgid, 0)
        assert _pid_alive(control.pid)
    finally:
        kill_test_group(target_pgid)
        kill_test_group(control_pgid)


def _token_visible(token: str) -> bool:
    try:
        for proc in psutil.process_iter(["pid", "environ"]):
            try:
                environ = proc.info.get("environ") or {}
                if environ.get("TRACEFORGE_RUN_TOKEN") == token:
                    return True
            except (psutil.Error, OSError):
                continue
    except (psutil.Error, OSError):
        return False
    return False


@pytest.mark.asyncio
async def test_stop_persisted_does_not_kill_reused_pid():
    """PID/PGID 复用保护：create time 不匹配 → 绝不向该 PID 发送信号。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", _SLEEP_SOURCE],
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    try:
        assert pgid == proc.pid
        # 持久化的 create time 与当前进程不符 → PID 被复用（模拟）。
        stale_started_at = datetime.now(timezone.utc) - timedelta(days=30)
        result = await process_supervisor.stop_persisted(
            proc.pid,
            stale_started_at,
            "linux-audit-reap",
            process_group_id=None,
        )
        # 复用 PID 绝不能被信号杀死，也绝不能被确认为原身份死亡。
        assert result.error_code == "PID_REUSED"
        assert result.signals_sent == ()
        assert _pid_alive(proc.pid)
    finally:
        kill_test_group(pgid)


@pytest.mark.asyncio
async def test_persisted_token_scan_does_not_block_event_loop(monkeypatch):
    """P1-1：慢 token 扫描只占 inspection worker，不占主事件循环。"""
    original = supervisor_module._scan_token_processes_sync

    def slow_scan(token: str, _not_before=None):
        time.sleep(0.20)
        return original(token, _not_before)

    monkeypatch.setattr(supervisor_module, "_scan_token_processes_sync", slow_scan)

    gaps: list[float] = []

    async def ticker():
        previous = asyncio.get_running_loop().time()
        for _ in range(60):
            await asyncio.sleep(0.01)
            now = asyncio.get_running_loop().time()
            gaps.append(now - previous)
            previous = now

    _, token_task = await asyncio.gather(
        ticker(),
        process_supervisor.stop_by_run_token_discovery(
            "missing-token",
            "lag-test",
            not_before=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
    )
    assert token_task is not None and token_task.confirmed_dead is True
    assert max(gaps) < 0.10
