"""bc6ca89 审计回归（doc: docs/agent-job-bc6ca89-remaining-code-audit.md）。

从审计复现脚本迁入正式测试目录，保留 Linux skip、受控故障与 finally 清理：

- P0-1：root 探测 UNKNOWN 不能凭 group LIVE 获得整组发送资格；已验证成员
  身份必须保存 immutable identity，并在发送前与原身份逐项比较（不可读/
  不符绝不发送）。
- P0-2：精确 token 命中绝不升级整组 killpg；发送前重新验证身份，扫描到
  发送之间身份变化时跳过。
- P0-3：managed wait/close 在出具全树死亡证明前必须用 per-spawn 谱系
  token 做脱组后代最终检查；同 attempt 其他合法执行进程绝不误伤。
- P1-2：取消正在执行的身份探测必须回收迟到结果并恰好关闭一次 pidfd。

所有真实进程测试只启动并回收本测试创建的进程/句柄。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import psutil
import pytest

import app.agents.process_supervisor as ps
from app.agents.process_supervisor import ProcessSupervisor

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux pidfd/proc discovery and POSIX process-group semantics only",
)


def alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


# ─────────────────────────────── P0-1 ───────────────────────────────


@pytest.mark.asyncio
async def test_unknown_root_must_not_authorize_group_signal():
    """root 探测 UNKNOWN（非明确消失）：数字 PGID 不能凭组非空整组 killpg。"""
    supervisor = ProcessSupervisor()
    unknown = ps.PersistedProcessSnapshot(state=ps.ProcessProbeState.UNKNOWN)
    live = ps.PersistedProcessSnapshot(
        state=ps.ProcessProbeState.LIVE, live_pids=(999991,)
    )
    dead = ps.PersistedProcessSnapshot(state=ps.ProcessProbeState.CONFIRMED_DEAD)
    with patch.object(supervisor, "_persisted_root_snapshot", AsyncMock(return_value=unknown)), \
         patch.object(supervisor, "_persisted_group_snapshot", AsyncMock(return_value=live)), \
         patch.object(supervisor, "_wait_persisted_group_gone", AsyncMock(return_value=dead)), \
         patch.object(ps.os, "killpg") as send:
        result = await supervisor.stop_persisted(
            999991, datetime.now(timezone.utc), "audit", process_group_id=999991
        )
    assert not send.called, send.call_args_list
    # root 未知是独立状态：不能被折叠成明确消失。
    assert result.confirmed_dead is None


@pytest.mark.asyncio
async def test_verified_member_identity_must_be_compared_again_before_signal():
    """已验证成员身份发送前必须重新比较原身份；PID 复用后绝不发送。"""
    supervisor = ProcessSupervisor()
    # 初次归属验证看到旧身份；发送前该 PID 已被新进程复用。
    identities = [
        ps._MemberIdentity(create_time=150.0),
        ps._MemberIdentity(
            state=ps.MemberBindingState.BOUND, create_time=300.0, pidfd=777
        ),
        ps._MemberIdentity(state=ps.MemberBindingState.GONE),
    ]
    with patch.object(ps.ProcessSupervisor, "_probe_member_identity", AsyncMock(side_effect=identities)), \
         patch.object(ps.ProcessSupervisor, "_signal_verified_member", return_value=True) as send, \
         patch.object(ps.os, "close"):
        snapshot = await supervisor._stop_reused_group_members(
            (999992,),
            old_root_started_at=datetime.fromtimestamp(100, timezone.utc),
            reused_create_time=200.0,
            signals=[],
        )
    assert not send.called, send.call_args_list
    assert snapshot.state == ps.ProcessProbeState.UNKNOWN
    assert 999992 in snapshot.live_pids


@pytest.mark.asyncio
async def test_unreadable_identity_before_signal_must_not_send():
    """发送前身份不可读（create time 无法读取）：绝不发送，保持未确认。"""
    supervisor = ProcessSupervisor()
    identities = [ps._MemberIdentity(create_time=150.0),
                  ps._MemberIdentity(create_time=None),
                  ps._MemberIdentity(state=ps.MemberBindingState.GONE)]
    with patch.object(ps.ProcessSupervisor, "_probe_member_identity", AsyncMock(side_effect=identities)), \
         patch.object(ps.ProcessSupervisor, "_signal_verified_member", return_value=True) as send:
        snapshot = await supervisor._stop_reused_group_members(
            (999993,),
            old_root_started_at=datetime.fromtimestamp(100, timezone.utc),
            reused_create_time=200.0,
            signals=[],
        )
    assert not send.called, send.call_args_list
    assert snapshot.state == ps.ProcessProbeState.UNKNOWN


@pytest.mark.asyncio
async def test_matching_identity_still_sends_after_recheck():
    """对照：发送前身份与原身份一致时仍允许单独发送（不过度收紧）。"""
    supervisor = ProcessSupervisor()
    identities = [
        ps._MemberIdentity(create_time=150.0),
        ps._MemberIdentity(
            state=ps.MemberBindingState.BOUND, create_time=150.0, pidfd=778
        ),
        ps._MemberIdentity(state=ps.MemberBindingState.GONE),
    ]
    with patch.object(ps.ProcessSupervisor, "_probe_member_identity", AsyncMock(side_effect=identities)), \
         patch.object(ps.ProcessSupervisor, "_signal_verified_member", return_value=True) as send, \
         patch.object(ps.os, "close"):
        snapshot = await supervisor._stop_reused_group_members(
            (999994,),
            old_root_started_at=datetime.fromtimestamp(100, timezone.utc),
            reused_create_time=200.0,
            signals=[],
        )
    assert send.called
    assert snapshot.state == ps.ProcessProbeState.CONFIRMED_DEAD


# ─────────────────────────────── P0-2 ───────────────────────────────


@pytest.mark.asyncio
async def test_exact_token_does_not_authorize_killing_other_token_group_members():
    """同数字组内的其他 token/无 token 成员：精确命中绝不升级整组 SIGKILL。"""
    token = str(uuid.uuid4())
    source = '''import os, subprocess, json, time
a = subprocess.Popen(["/bin/sleep", "120"], env={**os.environ, "TRACEFORGE_RUN_TOKEN": os.environ["AUDIT_TOKEN"]})
b = subprocess.Popen(["/bin/sleep", "120"], env={**os.environ, "TRACEFORGE_RUN_TOKEN": "other-" + os.environ["AUDIT_TOKEN"]})
print(json.dumps([a.pid, b.pid]), flush=True)
time.sleep(120)
'''
    parent = subprocess.Popen(
        [sys.executable, "-c", source],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "AUDIT_TOKEN": token},
    )
    children: list[int] = []
    try:
        children = json.loads(await asyncio.wait_for(asyncio.to_thread(parent.stdout.readline), 5))
        target, control = children
        supervisor = ProcessSupervisor()
        await supervisor.stop_by_run_token_discovery(token, "audit",
            not_before=datetime.now(timezone.utc))
        await asyncio.sleep(0.05)
        assert alive(control), (target, control, "other-token control was killed")
        assert not alive(target), (target, control, "exact-token target survived")
    finally:
        # 该 PGID 由本测试独占创建。
        assert parent.pid > 1 and parent.pid != os.getpgrp()
        try:
            os.killpg(parent.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.wait(timeout=5)
        parent.stdout.close()


@pytest.mark.asyncio
async def test_token_send_revalidates_identity_captured_at_scan():
    """扫描到发送之间 PID/身份改变：跳过发送（不盲杀复用后的新进程）。"""
    match = ps.DiscoveredTokenProcess(pid=999995, process_group_id=999995, create_time=100.0)
    supervisor = ProcessSupervisor()
    with patch.object(ps.ProcessSupervisor, "_probe_member_identity",
                      AsyncMock(return_value=ps._MemberIdentity(
                          state=ps.MemberBindingState.BOUND,
                          create_time=900.0, pidfd=779))), \
         patch.object(ps.ProcessSupervisor, "_signal_verified_member", return_value=True) as send, \
         patch.object(ps.os, "killpg") as killpg, patch.object(ps.os, "kill") as kill, \
         patch.object(ps.os, "close"):
        await ProcessSupervisor._kill_token_matches((match,), [])
    assert not send.called and not killpg.called and not kill.called


@pytest.mark.asyncio
async def test_token_send_with_matching_identity_still_kills():
    """对照：发送前身份与扫描身份一致时照常逐个发送（无整组信号）。"""
    match = ps.DiscoveredTokenProcess(pid=999996, process_group_id=999996, create_time=100.0)
    supervisor = ProcessSupervisor()
    with patch.object(ps.ProcessSupervisor, "_probe_member_identity",
                      AsyncMock(return_value=ps._MemberIdentity(
                          state=ps.MemberBindingState.BOUND,
                          create_time=100.0, pidfd=780))), \
         patch.object(ps.ProcessSupervisor, "_signal_verified_member", return_value=True) as send, \
         patch.object(ps.os, "killpg") as killpg, patch.object(ps.os, "close"):
        await ProcessSupervisor._kill_token_matches((match,), [])
    assert send.called
    assert not killpg.called, "token 命中禁止升级整组 killpg"


# ─────────────────────────────── P0-3 ───────────────────────────────


@pytest.mark.asyncio
async def test_managed_wait_must_not_forget_unsampled_detached_child():
    """未采样脱组后代：wait 绝不能出具 confirmed_dead=True（受控调度缺口）。"""
    supervisor = ProcessSupervisor()
    gate = asyncio.Event()
    original_monitor = supervisor._monitor_tree

    async def delayed_monitor(managed):
        await gate.wait()
        await original_monitor(managed)

    source = '''import subprocess
p = subprocess.Popen(["/bin/sleep", "120"], start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(p.pid, flush=True)
'''
    child_pid = None
    managed = None
    try:
        with patch.object(supervisor, "_monitor_tree", side_effect=delayed_monitor):
            managed = await supervisor.spawn([sys.executable, "-c", source], cwd=os.getcwd(),
                env=os.environ.copy(), run_token=str(uuid.uuid4()))
        child_pid = int(await asyncio.wait_for(managed.process.stdout.readline(), 5))
        await asyncio.wait_for(managed.process.wait(), 5)
        gate.set()
        result = await asyncio.wait_for(managed.wait(), 10)
        assert not (result.termination.confirmed_dead is True and alive(child_pid)), result
    finally:
        gate.set()
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if managed is not None:
            await managed.close(reason="audit_cleanup")
            supervisor.forget(managed)


@pytest.mark.asyncio
async def test_managed_wait_settles_detached_child_without_touching_sibling():
    """P0-3 收敛：wait 的最终检查只终止本 spawn 谱系后代；同 attempt 其他
    managed 的合法执行进程绝不误伤（per-spawn token 归属）。"""
    supervisor = ProcessSupervisor()
    source = '''import subprocess
p = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(p.pid, flush=True)
'''
    run_token = str(uuid.uuid4())
    detached_child = None
    managed = None
    sibling = None
    try:
        sibling = await supervisor.spawn([sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=os.getcwd(), env=os.environ.copy(), run_token=run_token)
        managed = await supervisor.spawn([sys.executable, "-c", source], cwd=os.getcwd(),
            env=os.environ.copy(), run_token=run_token)
        detached_child = int(await asyncio.wait_for(managed.process.stdout.readline(), 5))
        await asyncio.wait_for(managed.process.wait(), 5)
        result = await asyncio.wait_for(managed.wait(), 15)
        # 本 spawn 的脱组后代由安全身份路径终止后，才允许全树死亡证明。
        assert result.termination.confirmed_dead is True, result
        assert not alive(detached_child)
        # 同 attempt、同 run token 的其他 managed 进程不受影响。
        assert alive(sibling.pid)
    finally:
        if detached_child is not None:
            try:
                os.kill(detached_child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if managed is not None:
            await managed.close(reason="audit_cleanup")
            supervisor.forget(managed)
        if sibling is not None:
            await sibling.close(reason="audit_cleanup")
            supervisor.forget(sibling)


# ─────────────────────────────── P1-2 ───────────────────────────────


@pytest.mark.asyncio
async def test_cancelled_running_identity_probe_must_close_returned_pidfd():
    """取消正在执行的探测：迟到的 pidfd 必须被回收任务恰好关闭一次。"""
    if not hasattr(os, "pidfd_open"):
        pytest.skip("pidfd_open unavailable")
    supervisor = ProcessSupervisor()
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    captured: list[int] = []
    original = ps._probe_member_identity_sync

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(5)
        identity = original(*args, **kwargs)
        captured.append(identity.pidfd)
        completed.set()
        return identity

    try:
        with patch.object(ps, "_probe_member_identity_sync", side_effect=delayed):
            task = asyncio.create_task(supervisor._probe_member_identity(os.getpid(), want_pidfd=True))
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            while not completed.is_set():
                await asyncio.sleep(0.001)
            await asyncio.sleep(0.05)
            assert captured and captured[0] is not None, "pidfd unavailable in this environment"
            with pytest.raises(OSError):
                os.fstat(captured[0])
    finally:
        release.set()
        for fd in captured:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
