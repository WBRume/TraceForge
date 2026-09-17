"""token 收敛引擎（discovery.converge_token_kill）的直接单元测试。

重构自 process_supervisor 单体的三份重复收敛循环
（``_run_token_containment`` / ``stop_by_run_token_discovery`` 的循环体 /
谱系清理）统一为一个引擎；本文件钉住该新边界的契约：

- 初始快照 UNKNOWN 立即失败（kill_attempted=False，绝不发送）；
- 初始无匹配 → 单次最终快照出证据；迟到匹配**不在**收敛循环中补杀；
- 初始冲突 → conflicts outcome，零发送；
- 正常路径：逐轮发送 → 重扫，直到 DEAD / 截止；
- 发送之后才发现的 UNKNOWN/冲突必须携带 ``kill_attempted=True``
  （调用方据此如实上报 tree_kill_used 诊断）。

全部通过 mock 驱动，不触碰真实进程表，任何平台可运行。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

import app.agents.supervision.discovery as discovery_mod
from app.agents.supervision.discovery import (
    DiscoveredTokenProcess,
    TokenDiscoverySnapshot,
    converge_token_kill,
)
from app.agents.supervision.model import ProcessProbeState


_UNSET = object()


def _match(pid: int, create_time=_UNSET) -> DiscoveredTokenProcess:
    # 默认 create_time 落在受信任窗口内（not_before 之后）；显式传 None
    # 表示 create time 不可读（token_identity_ok 判为身份冲突）。
    if create_time is _UNSET:
        create_time = NOT_BEFORE.timestamp() + 10.0
    return DiscoveredTokenProcess(pid=pid, create_time=create_time)


def _snap(
    matches=(),
    unknown_pids=(),
    state: ProcessProbeState | None = None,
) -> TokenDiscoverySnapshot:
    if state is None:
        if matches:
            state = ProcessProbeState.LIVE
        elif unknown_pids:
            state = ProcessProbeState.UNKNOWN
        else:
            state = ProcessProbeState.CONFIRMED_DEAD
    return TokenDiscoverySnapshot(
        state=state,
        matches=tuple(matches),
        unknown_pids=tuple(unknown_pids),
        failure_code="TOKEN_DISCOVERY_UNKNOWN" if state == ProcessProbeState.UNKNOWN else None,
    )


def _queue(*snapshots: TokenDiscoverySnapshot) -> AsyncMock:
    mock = AsyncMock(side_effect=list(snapshots))
    return mock


NOT_BEFORE = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_initial_unknown_fails_fast_without_sending():
    """初始扫描不完整：立即 UNKNOWN，绝不发送，kill_attempted=False。"""
    initial = _snap(unknown_pids=(999901,))
    snapshot_mock = _queue(_snap())
    kill_mock = AsyncMock()
    with patch.object(discovery_mod, "token_snapshot", snapshot_mock), \
         patch.object(discovery_mod, "kill_token_matches", kill_mock):
        outcome = await converge_token_kill(
            "tok", not_before=NOT_BEFORE, not_after=None,
            signals=[], initial=initial, max_wait=5.0,
        )
    assert outcome.unknown is initial
    assert outcome.kill_attempted is False
    assert not kill_mock.called
    # 失败快路径直接返回，不再发起任何扫描。
    assert snapshot_mock.await_count == 0


@pytest.mark.asyncio
async def test_no_initial_match_verifies_once_without_killing_late_matches():
    """初始无匹配：取一次最终快照；迟到匹配不补杀（由调用方重试覆盖）。"""
    snapshot_mock = _queue(_snap(matches=(_match(987654),)))
    kill_mock = AsyncMock()
    with patch.object(discovery_mod, "token_snapshot", snapshot_mock), \
         patch.object(discovery_mod, "kill_token_matches", kill_mock):
        outcome = await converge_token_kill(
            "tok", not_before=NOT_BEFORE, not_after=None,
            signals=[], initial=_snap(), max_wait=5.0,
        )
    assert outcome.state == ProcessProbeState.LIVE
    assert outcome.live_pids == (987654,)
    assert outcome.kill_attempted is False
    assert not kill_mock.called
    assert snapshot_mock.await_count == 1


@pytest.mark.asyncio
async def test_no_initial_match_confirmed_dead():
    """初始无匹配 + 最终扫描为空：合法的空扫描死亡证明。"""
    snapshot_mock = _queue(_snap())
    with patch.object(discovery_mod, "token_snapshot", snapshot_mock), \
         patch.object(discovery_mod, "kill_token_matches", AsyncMock()):
        outcome = await converge_token_kill(
            "tok", not_before=NOT_BEFORE, not_after=None,
            signals=[], initial=_snap(), max_wait=5.0,
        )
    assert outcome.state == ProcessProbeState.CONFIRMED_DEAD
    assert outcome.live_pids == ()
    assert outcome.unknown is None


@pytest.mark.asyncio
async def test_initial_conflicts_never_send():
    """create time 不可读的匹配是身份冲突：零发送，保持未确认。"""
    initial = _snap(matches=(_match(999902, create_time=None),))
    kill_mock = AsyncMock()
    with patch.object(discovery_mod, "token_snapshot", _queue()), \
         patch.object(discovery_mod, "kill_token_matches", kill_mock):
        outcome = await converge_token_kill(
            "tok", not_before=NOT_BEFORE, not_after=None,
            signals=[], initial=initial, max_wait=5.0,
        )
    assert outcome.conflicts == initial.matches
    assert outcome.kill_attempted is False
    assert not kill_mock.called


@pytest.mark.asyncio
async def test_kill_then_rescan_dead_reports_attempted():
    """正常收敛：发送 → 重扫为空 → DEAD，kill_attempted=True。"""
    initial = _snap(matches=(_match(999903),))
    snapshot_mock = _queue(_snap())  # 重扫即 DEAD
    kill_mock = AsyncMock()
    with patch.object(discovery_mod, "token_snapshot", snapshot_mock), \
         patch.object(discovery_mod, "kill_token_matches", kill_mock):
        outcome = await converge_token_kill(
            "tok", not_before=NOT_BEFORE, not_after=None,
            signals=[], initial=initial, max_wait=5.0,
        )
    assert outcome.state == ProcessProbeState.CONFIRMED_DEAD
    assert outcome.kill_attempted is True
    assert kill_mock.await_count == 1
    assert snapshot_mock.await_count == 1


@pytest.mark.asyncio
async def test_unknown_after_kill_keeps_kill_attempted_diagnostic():
    """发送之后扫描不完整：UNKNOWN 携带 kill_attempted=True（诊断契约）。"""
    initial = _snap(matches=(_match(999904),))
    snapshot_mock = _queue(_snap(unknown_pids=(999904,)))
    with patch.object(discovery_mod, "token_snapshot", snapshot_mock), \
         patch.object(discovery_mod, "kill_token_matches", AsyncMock()):
        outcome = await converge_token_kill(
            "tok", not_before=NOT_BEFORE, not_after=None,
            signals=[], initial=initial, max_wait=5.0,
        )
    assert outcome.state == ProcessProbeState.UNKNOWN
    assert outcome.unknown is not None
    assert outcome.unknown.unknown_pids == (999904,)
    assert outcome.kill_attempted is True


@pytest.mark.asyncio
async def test_deadline_exits_with_final_live_evidence():
    """截止仍未收敛：最后一次快照的存活匹配作为 LIVE 证据。"""
    initial = _snap(matches=(_match(999905),))
    # 引擎以 0.1s 间隔轮询重扫直至截止（与原实现一致），随后做最终扫描；
    # mock 持续返回同一存活匹配，用足够长的 side_effect 序列兜住整个窗口
    # （Windows 上 asyncio 计时器可能提前唤醒，截止判断多跑一轮属正常）。
    snapshot_mock = AsyncMock(
        side_effect=[
            _snap(matches=(_match(999905),))
            for _ in range(12)
        ]
    )
    with patch.object(discovery_mod, "token_snapshot", snapshot_mock), \
         patch.object(discovery_mod, "kill_token_matches", AsyncMock()):
        outcome = await converge_token_kill(
            "tok", not_before=NOT_BEFORE, not_after=None,
            signals=[], initial=initial, max_wait=0.05,
        )
    assert outcome.state == ProcessProbeState.LIVE
    assert outcome.live_pids == (999905,)
    assert outcome.kill_attempted is True
    # 截止收敛：若干轮重扫 + 一次最终扫描。
    assert snapshot_mock.await_count >= 3
