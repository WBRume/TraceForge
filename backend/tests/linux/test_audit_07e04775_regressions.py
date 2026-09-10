"""07e04775 审计回归（doc: docs/agent-job-07e04775-audit-pseudocode-plan.md）。

从审计复现脚本迁入正式测试目录，保留 Linux skip、受控故障与 finally 清理：

- P0：pidfd 绑定失败/身份漂移绝不退回数字 PID 发送；同一 PID 两次读取的
  create time 必须精确一致（删除 0.5 秒容差）；只有 BOUND 状态允许发送。
- P1：已采样的脱组后代同样必须进入 per-spawn 谱系清理——清理不再以本地
  快照 CONFIRMED_DEAD 为前置条件；拒绝 TERM 的后代升级 SIGKILL。
- 发送后句柄恰好关闭一次；取消期间迟到结果仍被回收（见 bc6ca89 回归）。

所有信号都发给本测试创建/受控的目标；模拟身份的信号发送全部被拦截。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import patch

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


# ─────────────────────────────── P0 ───────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("second_time", [200.0, 100.25])
async def test_failed_or_different_pidfd_binding_never_sends(second_time):
    """初读 100；pidfd 打开后身份已变（200 / 100.25）：必须拒绝发送。

    旧行为：第一例关闭 fd 但返回旧 create_time + pidfd=None，发送路径退回
    os.kill 误杀新占用者；第二例落在 0.5 秒容差内被当成同一身份直接发送。
    新行为：绑定校验失败 -> UNVERIFIED，零信号（doc 审计 §2.5）。
    """
    samples = [SimpleNamespace(create_time=lambda: 100.0),
               SimpleNamespace(create_time=lambda: second_time)]
    with patch.object(ps.psutil, "Process", side_effect=samples), \
         patch.object(ps.os, "pidfd_open", return_value=777), \
         patch.object(ps.os, "close"), patch.object(ps.os, "kill") as kill, \
         patch.object(ps.signal, "pidfd_send_signal") as fd_send:
        result = await ps._signal_after_identity_recheck(999991, 100.0, signal.SIGKILL, [], "SIGKILL")
    assert result == "unverified", (result, kill.call_args_list, fd_send.call_args_list)
    assert not kill.called and not fd_send.called, (
        result, kill.call_args_list, fd_send.call_args_list
    )


@pytest.mark.asyncio
async def test_rebind_access_denied_never_sends():
    """绑定后身份重读 AccessDenied：结构化未确认，零信号。"""
    samples = [SimpleNamespace(create_time=lambda: 100.0), psutil.AccessDenied(999992)]
    with patch.object(ps.psutil, "Process", side_effect=samples), \
         patch.object(ps.os, "pidfd_open", return_value=778), \
         patch.object(ps.os, "close"), patch.object(ps.os, "kill") as kill, \
         patch.object(ps.signal, "pidfd_send_signal") as fd_send:
        result = await ps._signal_after_identity_recheck(999992, 100.0, signal.SIGKILL, [], "SIGKILL")
    assert result == "unverified"
    assert not kill.called and not fd_send.called


@pytest.mark.asyncio
async def test_pidfd_open_failure_never_sends():
    """pidfd_open 失败（权限拒绝）：结构化未确认，绝不退回数字 PID。"""
    samples = [SimpleNamespace(create_time=lambda: 100.0)]
    with patch.object(ps.psutil, "Process", side_effect=samples), \
         patch.object(ps.os, "pidfd_open", side_effect=PermissionError(999993)), \
         patch.object(ps.os, "kill") as kill, \
         patch.object(ps.signal, "pidfd_send_signal") as fd_send:
        result = await ps._signal_after_identity_recheck(999993, 100.0, signal.SIGKILL, [], "SIGKILL")
    assert result == "unverified"
    assert not kill.called and not fd_send.called


@pytest.mark.asyncio
async def test_unsupported_pidfd_platform_never_sends():
    """平台不支持安全句柄操作：明确 UNSUPPORTED，零信号。"""
    samples = [SimpleNamespace(create_time=lambda: 100.0)]
    with patch.object(ps.psutil, "Process", side_effect=samples), \
         patch.object(ps, "_pidfd_send_supported", return_value=False), \
         patch.object(ps.os, "kill") as kill, \
         patch.object(ps.signal, "pidfd_send_signal") as fd_send:
        result = await ps._signal_after_identity_recheck(999994, 100.0, signal.SIGKILL, [], "SIGKILL")
    assert result == "unverified"
    assert not kill.called and not fd_send.called


@pytest.mark.asyncio
async def test_missing_expected_identity_never_sends():
    """期望身份缺失（原身份从未验证）：零信号，保持未确认。"""
    samples = [SimpleNamespace(create_time=lambda: 100.0),
               SimpleNamespace(create_time=lambda: 100.0)]
    with patch.object(ps.psutil, "Process", side_effect=samples), \
         patch.object(ps.os, "pidfd_open", return_value=779), \
         patch.object(ps.os, "close"), patch.object(ps.os, "kill") as kill, \
         patch.object(ps.signal, "pidfd_send_signal") as fd_send:
        result = await ps._signal_after_identity_recheck(999995, None, signal.SIGKILL, [], "SIGKILL")
    assert result == "unverified"
    assert not kill.called and not fd_send.called


@pytest.mark.asyncio
async def test_verified_send_closes_pidfd_exactly_once():
    """正常匹配发送（sig=0 仅探测）：返回 sent，且绑定句柄恰好关闭一次。"""
    probe_ct = float(psutil.Process(os.getpid()).create_time())
    samples = [SimpleNamespace(create_time=lambda: probe_ct),
               SimpleNamespace(create_time=lambda: probe_ct)]
    closed: list[int] = []
    real_close = os.close

    def counting_close(fd):
        closed.append(int(fd))
        try:
            real_close(int(fd))
        except OSError:
            pass

    sent: list[tuple[int, int]] = []
    real_send = signal.pidfd_send_signal

    def counting_send(fd, sig, *args, **kwargs):
        sent.append((int(fd), int(sig)))
        return real_send(int(fd), int(sig), *args, **kwargs)

    with patch.object(ps.psutil, "Process", side_effect=samples), \
         patch.object(ps.os, "close", side_effect=counting_close), \
         patch.object(ps.signal, "pidfd_send_signal", side_effect=counting_send):
        result = await ps._signal_after_identity_recheck(
            os.getpid(), probe_ct, 0, [], "SIG0"
        )
    assert result == "sent", result
    # sig=0 不会真正发信号；句柄在发送后恰好关闭一次。
    assert sent and sent[0][1] == 0
    assert len(closed) == 1, closed


# ─────────────────────────────── P1 ───────────────────────────────


@pytest.mark.asyncio
async def test_sampled_detached_child_must_be_reclaimed():
    """已采样登记的脱组后代：本地快照一直 LIVE，close 仍必须经 spawn-token
    清理终止它并出具 confirmed_dead=True（doc 审计 §3.5）。"""
    supervisor = ProcessSupervisor()
    source = '''import subprocess, time
p = subprocess.Popen(["/bin/sleep", "120"], start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(p.pid, flush=True)
time.sleep(1)
'''
    managed = await supervisor.spawn(
        [sys.executable, "-c", source], cwd=os.getcwd(), env=os.environ.copy(),
        run_token="07e04775-audit",
    )
    child = None
    try:
        child = int(await asyncio.wait_for(managed.process.stdout.readline(), 5))
        await managed.inspect_tree()
        assert child in managed.known_descendant_pids, (
            "test setup must register child before root exits"
        )
        await asyncio.wait_for(managed.process.wait(), 5)
        # 只缩短等待预算；保留真实树采样与真实信号。
        async def fast_wait(_timeout):
            snapshot = await managed.inspect_tree()
            return snapshot.state == ps.ProcessProbeState.CONFIRMED_DEAD

        with patch.object(managed, "_wait_for_exit", side_effect=fast_wait):
            result = await managed.close(reason="audit")
        assert result.confirmed_dead is True, result
        assert not alive(child), result
    finally:
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await managed.close(reason="audit_cleanup")
        supervisor.forget(managed)


@pytest.mark.asyncio
async def test_term_resistant_detached_child_escapes_via_kill():
    """拒绝 TERM 的脱组后代：谱系清理必须升级 SIGKILL 后才能出具死亡证明。"""
    supervisor = ProcessSupervisor()
    source = '''import subprocess, sys, time
p = subprocess.Popen(
    [sys.executable, "-c",
     "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
    start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(p.pid, flush=True)
time.sleep(0.2)
'''
    managed = await supervisor.spawn(
        [sys.executable, "-c", source], cwd=os.getcwd(), env=os.environ.copy(),
        run_token=str(uuid.uuid4()),
    )
    child = None
    try:
        child = int(await asyncio.wait_for(managed.process.stdout.readline(), 5))
        await asyncio.wait_for(managed.process.wait(), 5)
        result = await asyncio.wait_for(managed.wait(), 20)
        assert result.termination.confirmed_dead is True, result
        assert "SIGTERM" in result.termination.signals_sent, result.termination
        assert "SIGKILL" in result.termination.signals_sent, result.termination
        assert not alive(child), result
    finally:
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await managed.close(reason="audit_cleanup")
        supervisor.forget(managed)


@pytest.mark.asyncio
async def test_same_attempt_two_managed_end_of_one_does_not_touch_other():
    """同 attempt 两个 managed：A 结束（含谱系清理）绝不误伤 B 的进程。"""
    supervisor = ProcessSupervisor()
    source = '''import subprocess
p = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(p.pid, flush=True)
'''
    run_token = str(uuid.uuid4())
    first_child = None
    first = None
    second = None
    try:
        first = await supervisor.spawn([sys.executable, "-c", source], cwd=os.getcwd(),
            env=os.environ.copy(), run_token=run_token)
        # 同 attempt 的另一个 managed：长驻 wrapper，必须全程存活。
        second = await supervisor.spawn(
            [sys.executable, "-c", "import time; time.sleep(60)"], cwd=os.getcwd(),
            env=os.environ.copy(), run_token=run_token,
        )
        first_child = int(await asyncio.wait_for(first.process.stdout.readline(), 5))
        await asyncio.wait_for(first.process.wait(), 5)
        result = await asyncio.wait_for(first.wait(), 20)
        assert result.termination.confirmed_dead is True, result
        assert not alive(first_child), result
        # 同 attempt、同 run token 的其他 managed 进程不受影响。
        assert alive(second.pid), second.pid
    finally:
        if first_child is not None:
            try:
                os.kill(first_child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for managed in (first, second):
            if managed is not None:
                await managed.close(reason="audit_cleanup")
                supervisor.forget(managed)


@pytest.mark.asyncio
async def test_killable_detached_child_does_not_orphan_job():
    """job 层断言（doc 审计 §3.5）：正常可杀的脱组 child 不再导致 ORPHANED。"""
    from types import SimpleNamespace

    from app.agents.contract import (
        EXECUTION_KIND_LOCAL_PROCESS,
        AgentStopResult,
    )
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptConvergenceRequest,
        ConvergenceIntent,
        _decide_final_status,
        resolve_attempt_evidence,
    )
    from app.domains.ai.models.ai_job import AiJobStatus

    supervisor = ProcessSupervisor()
    source = '''import subprocess
p = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(p.pid, flush=True)
'''
    run_token = str(uuid.uuid4())
    child = None
    managed = None
    try:
        managed = await supervisor.spawn([sys.executable, "-c", source], cwd=os.getcwd(),
            env=os.environ.copy(), run_token=run_token)
        child = int(await asyncio.wait_for(managed.process.stdout.readline(), 5))
        await asyncio.wait_for(managed.process.wait(), 5)
        termination = await asyncio.wait_for(managed.wait(), 20)
        assert termination.termination.confirmed_dead is True, termination
        assert not alive(child), termination
        # supervisor 结果 → 唯一证据解析器 → 决策表（与 job finalizer 相同路径）。
        stop = AgentStopResult(
            execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
            stop_acknowledged=True,
            local_process_started=True,
            local_process_confirmed_dead=termination.termination.confirmed_dead,
            remaining_pids=termination.termination.remaining_pids,
        )
        evidence = resolve_attempt_evidence(
            execution_kind=EXECUTION_KIND_LOCAL_PROCESS, stop_result=stop
        )
        request = AttemptConvergenceRequest(
            job_id="audit-job", run_token=run_token, worker_boot_id="boot",
            requested_status=AiJobStatus.FAILED, reason="audit",
            evidence=evidence, intent=ConvergenceIntent.NORMAL_FINALIZE,
        )
        job = SimpleNamespace(process_pid=None, process_group_id=None)
        status, _ = _decide_final_status(job, request, EXECUTION_KIND_LOCAL_PROCESS)
        assert status == AiJobStatus.FAILED, (status, evidence)
    finally:
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if managed is not None:
            await managed.close(reason="audit_cleanup")
            supervisor.forget(managed)
