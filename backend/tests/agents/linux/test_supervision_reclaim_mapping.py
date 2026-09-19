"""reclaim.stop_by_run_token_discovery 的结果映射测试（Linux 门禁内）。

stop_by_run_token_discovery 在 Windows 上直接返回 None（discovery 不可用），
因此映射断言放在 Linux 门禁内。通过 mock 驱动（不触碰真实进程表），钉住
统一收敛引擎 ``converge_token_kill`` 的结果 → TerminationResult 映射：

- 发送前发现身份冲突：confirmed_dead=False，未发送（tree_kill_used=False）；
- 发送之后才发现冲突/不完整扫描：tree_kill_used=True（信号已真实发出，
  诊断必须如实上报）；
- 完整空扫描（double-scan grace 后仍为空）：confirmed_dead=True。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

import app.agents.supervision.discovery as discovery_mod
import app.agents.supervision.reclaim as reclaim_mod
from app.agents.supervision.discovery import (
    DiscoveredTokenProcess,
    TokenDiscoverySnapshot,
)
from app.agents.supervision.model import ProcessProbeState

pytestmark = pytest.mark.skipif(
    not __import__("sys").platform.startswith("linux"),
    reason="stop_by_run_token_discovery returns None off Linux",
)


_UNSET = object()


def _match(pid: int, create_time=_UNSET) -> DiscoveredTokenProcess:
    # 默认 create_time 落在受信任窗口内（not_before 之后）；显式传 None
    # 表示 create time 不可读（token_identity_ok 判为身份冲突）。
    if create_time is _UNSET:
        create_time = NOT_BEFORE.timestamp() + 10.0
    return DiscoveredTokenProcess(pid=pid, create_time=create_time)


def _snap(matches=(), unknown_pids=()) -> TokenDiscoverySnapshot:
    if matches:
        state = ProcessProbeState.LIVE
    elif unknown_pids:
        state = ProcessProbeState.UNKNOWN
    else:
        state = ProcessProbeState.CONFIRMED_DEAD
    return TokenDiscoverySnapshot(
        state=state, matches=tuple(matches), unknown_pids=tuple(unknown_pids)
    )


NOT_BEFORE = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_pre_kill_conflict_reports_no_tree_kill():
    """发送前冲突：未发出任何信号，tree_kill_used=False。"""
    initial = _snap(matches=(_match(999906, create_time=None),))
    with patch.object(discovery_mod, "token_snapshot", AsyncMock(return_value=initial)), \
         patch.object(discovery_mod, "kill_token_matches", AsyncMock()) as kill:
        result = await reclaim_mod.stop_by_run_token_discovery("tok", "audit", not_before=NOT_BEFORE)
    assert result is not None
    assert result.confirmed_dead is False
    assert result.error_code == "TOKEN_PROCESS_IDENTITY_CONFLICT"
    assert result.tree_kill_used is False
    assert result.signals_sent == ()
    assert not kill.called


@pytest.mark.asyncio
async def test_post_kill_conflict_reports_tree_kill_used():
    """发送之后才发现冲突：诊断必须如实上报 tree_kill_used=True。"""
    # 初始：一个可验证匹配 → 发送；重扫：身份不可读（冲突）。
    snapshots = [
        _snap(matches=(_match(999907),)),
        _snap(matches=(_match(999907, create_time=None),)),
    ]
    with patch.object(discovery_mod, "token_snapshot", AsyncMock(side_effect=snapshots)), \
         patch.object(discovery_mod, "kill_token_matches", AsyncMock()) as kill:
        result = await reclaim_mod.stop_by_run_token_discovery("tok", "audit", not_before=NOT_BEFORE)
    assert result is not None
    assert result.confirmed_dead is False
    assert result.error_code == "TOKEN_PROCESS_IDENTITY_CONFLICT"
    assert result.tree_kill_used is True
    assert kill.await_count == 1


@pytest.mark.asyncio
async def test_double_empty_scan_confirms_dead():
    """double-scan grace 后仍为空：合法死亡证明（不触发发送）。"""
    snapshot_mock = AsyncMock(return_value=_snap())
    with patch.object(discovery_mod, "token_snapshot", snapshot_mock), \
         patch.object(discovery_mod, "kill_token_matches", AsyncMock()) as kill:
        result = await reclaim_mod.stop_by_run_token_discovery("tok", "audit", not_before=NOT_BEFORE)
    assert result is not None
    assert result.confirmed_dead is True
    assert not kill.called
    # double-scan grace：两次扫描。
    assert snapshot_mock.await_count == 2
