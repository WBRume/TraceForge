"""d21a7118 审计回归（doc: docs/agent-job-d21a7118-audit-and-fix-plan.md）。

从审计复现脚本迁入正式测试目录，保留 Linux skip 与安全清理逻辑，并补充
审计文档验收要求的表驱动组合与上层断言：

- P0-1：root PID 复用（或身份无法核实）时，数字 PGID 不能获得整组发送
  资格；只有身份可验证的残留目标才允许单独发信号（pidfd 优先）。
- P0-2：token 扫描不按命令名预过滤；environ 不可读的候选只有可验证的
  时间边界证据才可排除；匹配的存活目标不得产生空扫描。
- P0-3：聚合层保留 UNKNOWN / token LIVE 证据；确认死亡不得携带未决来源。
- P1-2：inspection 许可唯一释放者（排队取消/运行取消/submit 失败/
  probe 异常/正常完成都恰好释放一次）。

所有真实进程测试只启动并回收本测试的 /bin/sleep，绝不向既有进程发信号。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import psutil
import pytest

import app.agents.process_supervisor as ps
from app.agents.process_supervisor import (
    PROCESS_GROUP_UNKNOWN,
    PROCESS_TREE_UNKNOWN,
    TOKEN_DISCOVERY_UNKNOWN,
    ProcessProbeState,
    process_supervisor,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux /proc and POSIX process-group semantics only",
)

_PERSISTED_ROOT_START = datetime.now(timezone.utc) - timedelta(hours=1)


def _find_absent_pid() -> int:
    candidate = os.getpid() + 100000
    while True:
        try:
            os.kill(candidate, 0)
        except ProcessLookupError:
            return candidate
        except PermissionError:
            candidate += 1
            continue
        candidate += 1


# ─────────────────────────── P0-3A：managed 快照聚合 ───────────────────────────


def _managed(returncode=0, pid=99999999, known=()):
    return SimpleNamespace(
        process=SimpleNamespace(returncode=returncode),
        pid=pid,
        known_descendant_pids=set(known),
        job_handle=None,
        process_group_id=None,
        process_start_time=None,
    )


def test_group_unknown_must_not_become_dead():
    """root 退出 + group UNKNOWN：没有 LIVE 也绝不允许 CONFIRMED_DEAD。"""
    managed = _managed()
    with patch.object(ps, "_windows_job_probe", return_value=(ProcessProbeState.CONFIRMED_DEAD, ())), \
         patch.object(ps, "_posix_group_probe", return_value=(ProcessProbeState.UNKNOWN, ())):
        result = ps.inspect_process_tree_snapshot(managed)
    assert result.state == ProcessProbeState.UNKNOWN
    assert result.failure_code == "PROCESS_GROUP_UNKNOWN"


def test_job_probe_unknown_must_not_become_dead():
    """Windows Job 查询失败同样不能折叠成死亡（同一聚合不变量）。"""
    managed = _managed()
    with patch.object(ps, "_windows_job_probe", return_value=(ProcessProbeState.UNKNOWN, ())), \
         patch.object(ps, "_posix_group_probe", return_value=(ProcessProbeState.CONFIRMED_DEAD, ())):
        result = ps.inspect_process_tree_snapshot(managed)
    assert result.state == ProcessProbeState.UNKNOWN


def test_all_sources_dead_stays_confirmed_dead():
    """对照：全部来源明确死亡仍然允许 CONFIRMED_DEAD（不收紧过度）。"""
    managed = _managed()
    with patch.object(ps, "_windows_job_probe", return_value=(ProcessProbeState.CONFIRMED_DEAD, ())), \
         patch.object(ps, "_posix_group_probe", return_value=(ProcessProbeState.CONFIRMED_DEAD, ())):
        result = ps.inspect_process_tree_snapshot(managed)
    assert result.state == ProcessProbeState.CONFIRMED_DEAD


def test_mixed_live_and_unknown_descendants_are_both_kept(monkeypatch):
    """LIVE 与 UNKNOWN 后代混合：apply_snapshot 绝不能遗忘 UNKNOWN 身份。"""
    managed = _managed(returncode=None, known=[991002, 991003])

    def process_for(pid):
        if int(pid) == 991002:
            proc = SimpleNamespace()
            proc.create_time = lambda: 12345.0
            proc.is_running = lambda: True
            proc.status = lambda: psutil.STATUS_RUNNING
            return proc
        raise psutil.AccessDenied(pid=991003)

    monkeypatch.setattr(ps.psutil, "Process", process_for)
    monkeypatch.setattr(psutil, "Process", process_for, raising=False)
    snapshot = ps.inspect_process_tree_snapshot(managed)
    assert snapshot.state == ProcessProbeState.LIVE
    assert 991002 in snapshot.live_descendant_pids
    assert 991003 in snapshot.unknown_descendant_pids

    from app.agents.process_supervisor import ManagedAgentProcess

    real_managed = ManagedAgentProcess(
        process=SimpleNamespace(pid=99999999, returncode=None),
        known_descendant_pids={991002, 991003},
    )
    real_managed.apply_snapshot(snapshot)
    # 混合 LIVE/UNKNOWN：两个身份都必须保留。
    assert real_managed.known_descendant_pids == {991002, 991003}


def test_unknown_state_has_no_fillable_pid_is_still_unknown():
    """UNKNOWN 不依赖可填写的 PID（containment 未知但没有 PID）。"""
    managed = _managed(known=[])
    with patch.object(ps, "_windows_job_probe", return_value=(ProcessProbeState.CONFIRMED_DEAD, ())), \
         patch.object(ps, "_posix_group_probe", return_value=(ProcessProbeState.UNKNOWN, ())):
        result = ps.inspect_process_tree_snapshot(managed)
    assert result.state == ProcessProbeState.UNKNOWN
    assert result.unknown_descendant_pids == ()


# ─────────────────────────── P0-3B：persisted 聚合 ───────────────────────────


def _dead(**kwargs):
    return ps.PersistedProcessSnapshot(state=ProcessProbeState.CONFIRMED_DEAD, **kwargs)


def _live_pids(*pids):
    return ps.PersistedProcessSnapshot(
        state=ProcessProbeState.LIVE, live_pids=tuple(pids)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "root_snapshot,group_snapshot,token_return,expect",
    [
        # root/group DEAD + token LIVE：token 存活目标参与最终 state。
        ("dead", "dead", ((987654,), None), (False, (987654,))),
        # root/group DEAD + token 扫描 UNKNOWN：独立 UNKNOWN 状态。
        ("dead", "dead", ((), "unknown"), (None, (999901,))),
        # root DEAD + group UNKNOWN（无 token）：UNKNOWN 保留组未确认 PID。
        ("dead", "unknown", None, (None, (999902,))),
        # root/group DEAD + token UNKNOWN（无未知 PID 可填写）：仍是 UNKNOWN。
        ("dead", "dead", ((), "empty-unknown"), (None, ())),
        # root LIVE + group DEAD + token DEAD：LIVE。
        ("live", "dead", ((), None), (False, (99999999,))),
    ],
)
async def test_persisted_aggregation_table(root_snapshot, group_snapshot, token_return, expect):
    root = (
        _dead()
        if root_snapshot == "dead"
        else _live_pids(99999999)
    )
    if group_snapshot == "dead":
        group_snapshot = _dead()
    elif group_snapshot == "unknown":
        group_snapshot = ps.PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            live_pids=(999902,),
            failure_code=PROCESS_GROUP_UNKNOWN,
        )
    supervisor = process_supervisor
    run_token = "audit-token" if token_return is not None else None
    if token_return is not None and token_return[1] is not None:
        unknown_pids = () if token_return[1] == "empty-unknown" else (999901,)
        token_return = (
            token_return[0],
            ps.TokenDiscoverySnapshot(
                state=ProcessProbeState.UNKNOWN,
                unknown_pids=unknown_pids,
                failure_code=TOKEN_DISCOVERY_UNKNOWN,
            ),
        )
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=root)), \
         patch.object(supervisor, "_persisted_group_snapshot", AsyncMock(return_value=group_snapshot)), \
         patch.object(
             supervisor,
             "_wait_persisted_group_gone",
             AsyncMock(return_value=group_snapshot),
         ), \
         patch.object(ps.os, "killpg"), patch.object(ps.os, "kill"), \
         patch.object(
             supervisor,
             "_run_token_containment",
             AsyncMock(return_value=token_return),
         ):
        result = await supervisor.stop_persisted(
            99999999, None, "audit", run_token=run_token
        )
    expect_dead, expect_remaining = expect
    assert result.confirmed_dead is expect_dead, result
    assert set(result.remaining_pids) >= set(expect_remaining), (result, expect_remaining)


@pytest.mark.asyncio
async def test_confirmed_dead_returns_never_carry_unconfirmed_targets():
    """确认死亡的返回点不得携带未决来源（防御性不变量）。"""
    supervisor = process_supervisor
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=_dead())), \
         patch.object(supervisor, "_persisted_group_snapshot", AsyncMock(return_value=_dead())), \
         patch.object(supervisor, "_run_token_containment", AsyncMock(return_value=((), None))):
        result = await supervisor.stop_persisted(99999999, None, "audit", run_token="t")
    assert result.confirmed_dead is True
    assert result.remaining_pids == ()


# ─────────────────────────────── P0-1：复用 PGID ───────────────────────────────


def _reused_root(create_time=None):
    return ps.PersistedProcessSnapshot(
        state=ProcessProbeState.CONFIRMED_DEAD,
        root_identity_matches=False,
        pid_create_time=create_time,
        failure_code="PID_REUSED",
        error_message="PID create time does not match persisted owner",
    )


@pytest.mark.asyncio
async def test_reused_root_without_group_sends_no_signal():
    """无 PGID：复用 root 无任何可归因 containment，不得发信号。"""
    supervisor = process_supervisor
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=_reused_root())), \
         patch.object(supervisor, "_persisted_group_snapshot", AsyncMock(return_value=_dead())), \
         patch.object(ps.os, "killpg") as killpg, patch.object(ps.os, "kill") as kill:
        result = await supervisor.stop_persisted(
            987654, None, "audit", process_group_id=None
        )
    assert not killpg.called and not kill.called
    assert result.confirmed_dead is True
    assert result.error_code == "PID_REUSED"


@pytest.mark.asyncio
async def test_reused_group_with_unverifiable_member_sends_no_signal():
    """复用 root + PGID 组员身份不可核实：绝不允许整组或单独发信号。"""
    member = _find_absent_pid()
    supervisor = process_supervisor
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=_reused_root())), \
         patch.object(
             supervisor,
             "_persisted_group_snapshot",
             AsyncMock(return_value=_live_pids(member)),
         ), \
         patch.object(
             ps, "_probe_member_identity_sync", lambda pid, **kw: ps._MemberIdentity()
         ), \
         patch.object(ps.os, "killpg") as killpg, patch.object(ps.os, "kill") as kill:
        result = await supervisor.stop_persisted(
            987654, _PERSISTED_ROOT_START, "audit", process_group_id=987654
        )
    assert not killpg.called and not kill.called, killpg.call_args_list
    assert result.confirmed_dead is None
    assert member in result.remaining_pids


@pytest.mark.asyncio
async def test_reused_group_new_member_created_after_reuse_is_ambiguous():
    """复用后创建的组员（新进程组）归属不明：不发信号，保持 UNKNOWN。"""
    member = _find_absent_pid()
    reused_ct = _PERSISTED_ROOT_START.timestamp() + 3600.0
    supervisor = process_supervisor
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=_reused_root(reused_ct))), \
         patch.object(
             supervisor,
             "_persisted_group_snapshot",
             AsyncMock(return_value=_live_pids(member)),
         ), \
         patch.object(
             ps,
             "_probe_member_identity_sync",
             lambda pid, **kw: ps._MemberIdentity(create_time=reused_ct + 10.0),
         ), \
         patch.object(ps.os, "killpg") as killpg, patch.object(ps.os, "kill") as kill:
        result = await supervisor.stop_persisted(
            987654, _PERSISTED_ROOT_START, "audit", process_group_id=987654
        )
    assert not killpg.called and not kill.called
    assert result.confirmed_dead is None
    assert member in result.remaining_pids


@pytest.mark.asyncio
async def test_reused_group_verified_leftover_is_signaled_individually():
    """复用 root + 可信残留后代：必须逐个验证身份后经绑定句柄单独发信号
    （非 killpg，绝不退回数字 PID），且在残留停止前绝不允许
    confirmed_dead=True。"""
    member = _find_absent_pid()
    reused_ct = _PERSISTED_ROOT_START.timestamp() + 3600.0
    member_ct = _PERSISTED_ROOT_START.timestamp() + 60.0
    killed: list[tuple[int, int]] = []
    fake_fd = 424242

    def fake_identity_sync(pid, *, want_pidfd=False):
        # SIGKILL 已发送后目标消失（绑定句柄 ESRCH 的明确死亡证据）。
        if any(sig == int(signal.SIGKILL) for _, sig in killed):
            return ps._MemberIdentity(state=ps.MemberBindingState.GONE)
        return ps._MemberIdentity(
            state=ps.MemberBindingState.BOUND, create_time=member_ct, pidfd=fake_fd
        )

    supervisor = process_supervisor

    def fake_pidfd_send(fd, sig, *args, **kwargs):
        killed.append((member, int(sig)))
        if int(sig) == int(signal.SIGKILL):
            # 绑定句柄的 ESRCH：该实例在 KILL 后已退出。
            raise ProcessLookupError(member)

    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=_reused_root(reused_ct))), \
         patch.object(
             supervisor,
             "_persisted_group_snapshot",
             AsyncMock(return_value=_live_pids(member)),
         ), \
         patch.object(ps, "_probe_member_identity_sync", fake_identity_sync), \
         patch.object(ps.os, "killpg") as killpg, \
         patch.object(ps.os, "kill") as kill, \
         patch.object(ps.os, "close"), \
         patch.object(ps.signal, "pidfd_send_signal", side_effect=fake_pidfd_send):
        result = await supervisor.stop_persisted(
            987654, _PERSISTED_ROOT_START, "audit", process_group_id=987654
        )
    assert not killpg.called
    assert not kill.called, "绑定失败路径禁止退回数字 PID 发送"
    # 验证过的残留目标被逐个 SIGTERM/SIGKILL（pidfd，非整组）。
    assert (member, int(signal.SIGTERM)) in killed
    assert (member, int(signal.SIGKILL)) in killed
    assert result.confirmed_dead is True
    assert result.error_code == "PID_REUSED"


@pytest.mark.asyncio
async def test_unverified_live_root_group_does_not_receive_group_signal():
    """root 存活但身份无法核实：旧 PGID 不能单凭组非空获得发送资格。"""
    member = _find_absent_pid()
    unverified_root = ps.PersistedProcessSnapshot(
        state=ProcessProbeState.LIVE,
        live_pids=(987654,),
        root_identity_matches=None,
        failure_code=PROCESS_TREE_UNKNOWN,
        error_message="create time could not be verified",
    )
    supervisor = process_supervisor
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=unverified_root)), \
         patch.object(
             supervisor,
             "_persisted_group_snapshot",
             AsyncMock(return_value=_live_pids(member)),
         ), \
         patch.object(
             ps, "_probe_member_identity_sync", lambda pid, **kw: ps._MemberIdentity()
         ), \
         patch.object(ps.os, "killpg") as killpg, patch.object(ps.os, "kill") as kill:
        result = await supervisor.stop_persisted(
            987654, _PERSISTED_ROOT_START, "audit", process_group_id=987654
        )
    assert not killpg.called and not kill.called
    # root 自身 LIVE 证据保留（未确认，不是死亡证明）。
    assert result.confirmed_dead is False
    assert member in result.remaining_pids


@pytest.mark.asyncio
async def test_root_gone_group_live_still_receives_group_signal():
    """对照：root 明确消失（未被复用占用）+ 原组存活 → killpg 正常清理。"""
    supervisor = process_supervisor
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=_dead())), \
         patch.object(supervisor, "_persisted_group_snapshot", AsyncMock(return_value=_live_pids(987655))), \
         patch.object(supervisor, "_wait_persisted_group_gone", AsyncMock(return_value=_dead())), \
         patch.object(ps.os, "killpg") as killpg, patch.object(ps.os, "kill") as kill:
        result = await supervisor.stop_persisted(
            987654, None, "audit", process_group_id=987654
        )
    assert killpg.called
    assert result.confirmed_dead is True


# ─────────────────────────── P0-2：token 扫描完整性 ───────────────────────────


def _sleep_proc(token: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["/bin/sleep", "120"],
        start_new_session=True,
        env={**os.environ, ps.RUN_TOKEN_ENV_VAR: token},
    )


@pytest.mark.asyncio
async def test_plain_token_child_is_discovered_and_stopped():
    """P0-2：无 marker 的普通工具子进程（/bin/sleep）继承 token 时，
    discovery 不得返回空扫描；可信边界内匹配目标被终止。"""
    token = str(uuid.uuid4())
    proc = _sleep_proc(token)
    pgid = os.getpgid(proc.pid)
    try:
        result = await process_supervisor.stop_by_run_token_discovery(
            token, "audit", not_before=datetime.now(timezone.utc)
        )
        assert result is not None
        # 匹配存活目标不得空扫描：要么已终止（confirmed_dead=True），
        # 要么扫描不完整（UNKNOWN）；绝不允许“目标存活 + 空扫描死亡”。
        alive = proc.poll() is None
        assert not (result.confirmed_dead is True and alive), (result, proc.pid)
        if not alive:
            assert result.confirmed_dead is True
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.asyncio
async def test_control_process_without_token_is_not_killed():
    """P0-2 对照：不同 token 的同 UID 进程绝不能被误终止。"""
    token = str(uuid.uuid4())
    target = _sleep_proc(token)
    control = subprocess.Popen(
        ["/bin/sleep", "120"],
        start_new_session=True,
        env={**os.environ, ps.RUN_TOKEN_ENV_VAR: str(uuid.uuid4())},
    )
    control_pgid = os.getpgid(control.pid)
    try:
        result = await process_supervisor.stop_by_run_token_discovery(
            token, "audit", not_before=datetime.now(timezone.utc)
        )
        assert result is not None
        assert not (result.confirmed_dead is True and target.poll() is None)
        assert control.poll() is None, "control process must not be signalled"
    finally:
        for proc in (target, control):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        try:
            os.killpg(control_pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.asyncio
async def test_unreadable_environ_without_boundary_keeps_unknown(monkeypatch):
    """environ 不可读且无可验证边界：UNKNOWN（不完整扫描不得确认死亡）。"""
    fake_pid = _find_absent_pid()

    class _Unreadable:
        pid = fake_pid

        def uids(self):
            return SimpleNamespace(real=os.getuid())

        def status(self):
            return psutil.STATUS_RUNNING

        def create_time(self):
            return time.time()

        def environ(self):
            raise psutil.AccessDenied(fake_pid)

    monkeypatch.setattr(psutil, "process_iter", lambda *_a, **_kw: iter([_Unreadable()]))
    result = await process_supervisor.stop_by_run_token_discovery("token-1", "audit")
    assert result is not None
    assert result.confirmed_dead is None
    assert fake_pid in result.remaining_pids


def test_token_identity_ok_no_longer_requires_marker():
    """普通工具命令不能仅因缺少 marker 被判为身份冲突。"""
    match = ps.DiscoveredTokenProcess(
        pid=123,
        create_time=time.time(),
        command="/bin/sleep 120",
        command_readable=True,
    )
    assert ps.ProcessSupervisor._token_identity_ok(
        match, not_before=None, not_after=None
    )


# ─────────────────────────── P1-2：inspection 许可所有权 ───────────────────────────


class _PermitFixture:
    def __init__(self, permits: int = 2, workers: int = 1):
        self.permits = threading.BoundedSemaphore(permits)
        self.total = permits
        self.executor = ThreadPoolExecutor(max_workers=workers)

    def available(self) -> int:
        count = 0
        for _ in range(self.total):
            if self.permits.acquire(blocking=False):
                count += 1
            else:
                break
        for _ in range(count):
            self.permits.release()
        return count


@pytest.mark.asyncio
async def test_cancelled_queued_probe_releases_permit():
    """排队期取消：工作项可被取消，但许可必须恰好释放一次。"""
    fixture = _PermitFixture()
    gate = threading.Event()
    started = threading.Event()

    def block():
        started.set()
        gate.wait(5)

    with patch.object(ps, "_inspection_executor", return_value=fixture.executor), \
         patch.object(ps, "_INSPECTION_QUEUE_PERMITS", fixture.permits):
        first = asyncio.create_task(ps.run_process_probe(block))
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            queued = asyncio.create_task(ps.run_process_probe(lambda: None))
            await asyncio.sleep(0.01)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            gate.set()
            await first
            fixture.executor.shutdown(wait=True)
            assert fixture.available() == fixture.total
        finally:
            gate.set()
            await first


@pytest.mark.asyncio
async def test_cancelled_running_probe_keeps_permit_until_work_finishes():
    """运行期取消：asyncio wrapper 立刻返回，但许可由原始 future 在工作
    完成后释放（底层线程仍占用许可）。"""
    fixture = _PermitFixture()
    gate = threading.Event()
    started = threading.Event()

    def block():
        started.set()
        gate.wait(5)

    with patch.object(ps, "_inspection_executor", return_value=fixture.executor), \
         patch.object(ps, "_INSPECTION_QUEUE_PERMITS", fixture.permits):
        task = asyncio.create_task(ps.run_process_probe(block))
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            # 工作仍在执行：许可被占用。
            assert fixture.available() == fixture.total - 1
            gate.set()
            await asyncio.sleep(0.05)
            fixture.executor.shutdown(wait=True)
            assert fixture.available() == fixture.total
        finally:
            gate.set()
            await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_submit_failure_releases_permit():
    """submit 抛错：工作项从未入队，由提交方释放许可。"""
    fixture = _PermitFixture()

    class _BrokenExecutor:
        def submit(self, *args, **kwargs):
            raise RuntimeError("executor is shut down")

    with patch.object(ps, "_inspection_executor", return_value=_BrokenExecutor()), \
         patch.object(ps, "_INSPECTION_QUEUE_PERMITS", fixture.permits):
        with pytest.raises(RuntimeError):
            await ps.run_process_probe(lambda: None)
    assert fixture.available() == fixture.total


@pytest.mark.asyncio
async def test_probe_runtime_error_releases_permit_exactly_once():
    """probe 自身抛 RuntimeError：许可只释放一次（不再触发
    BoundedSemaphore 的 double-release ValueError）。"""
    fixture = _PermitFixture()

    def boom():
        raise RuntimeError("probe exploded")

    with patch.object(ps, "_inspection_executor", return_value=fixture.executor), \
         patch.object(ps, "_INSPECTION_QUEUE_PERMITS", fixture.permits):
        with pytest.raises(RuntimeError):
            await ps.run_process_probe(boom)
        fixture.executor.shutdown(wait=True)
    assert fixture.available() == fixture.total


@pytest.mark.asyncio
async def test_normal_probe_completion_restores_permits():
    fixture = _PermitFixture()

    with patch.object(ps, "_inspection_executor", return_value=fixture.executor), \
         patch.object(ps, "_INSPECTION_QUEUE_PERMITS", fixture.permits):
        assert await ps.run_process_probe(lambda: "ok") == "ok"
        fixture.executor.shutdown(wait=True)
    assert fixture.available() == fixture.total


@pytest.mark.asyncio
async def test_cancellation_storm_does_not_permanently_saturate_queue():
    """长期取消压力：许可不能被排队取消永久耗尽。"""
    fixture = _PermitFixture(permits=4, workers=1)
    gate = threading.Event()
    started = threading.Event()

    def block():
        started.set()
        gate.wait(10)

    with patch.object(ps, "_inspection_executor", return_value=fixture.executor), \
         patch.object(ps, "_INSPECTION_QUEUE_PERMITS", fixture.permits):
        first = asyncio.create_task(ps.run_process_probe(block))
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            for _ in range(50):
                task = asyncio.create_task(ps.run_process_probe(lambda: None))
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            gate.set()
            await first
            fixture.executor.shutdown(wait=True)
            assert fixture.available() == fixture.total
        finally:
            gate.set()
