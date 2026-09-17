"""监管域的三态证据模型（doc §5.4）。

所有进程生死判断共用同一语言：

- :class:`ProcessProbeState` —— LIVE / CONFIRMED_DEAD / UNKNOWN 三态；禁止
  调用方通过"空 PID 集"或 ``False`` 自行推断死亡，检查异常必须映射为
  ``UNKNOWN``，绝不制造假死亡证明。
- :class:`TerminationResult` / :class:`ProcessWaitResult` —— 终止与等待的
  结构化结果（doc §5.4.4）。
- :class:`ProcessTreeSnapshot` —— 受管进程树的离环采样快照。
- 失败码常量与 run-token 派生的 containment id。

本模块只依赖标准库与 contract，不触碰 psutil / 平台 API，供所有下游模块
共享，依赖方向严格向下。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, Tuple

from app.agents.contract import (
    EXECUTION_KIND_LOCAL_PROCESS,
    AgentStopResult,
)

# attempt 级 run token：spawn 时注入子进程 env（后代继承），reaper 的
# token discovery 用它在 worker 重启后找回全部后代。
RUN_TOKEN_ENV_VAR = "TRACEFORGE_RUN_TOKEN"

# P0-3：per-spawn 谱系 token 环境变量。每次 spawn 生成 uuid4 注入子进程
# env（后代继承），把"脱组后代"精确归属到单个 managed 进程；attempt 级
# run token 仍然同时注入，供 reaper 的 token discovery 覆盖全部后代。
SPAWN_TOKEN_ENV_VAR = "TRACEFORGE_SPAWN_TOKEN"

# P0-3：全树完成检查无法收敛时的结构化 failure code。
DETACHED_DESCENDANTS_UNRESOLVED = "DETACHED_DESCENDANTS_UNRESOLVED"

PROCESS_TREE_UNKNOWN = "PROCESS_TREE_UNKNOWN"
PROCESS_GROUP_UNKNOWN = "PROCESS_GROUP_UNKNOWN"
TOKEN_DISCOVERY_UNKNOWN = "TOKEN_DISCOVERY_UNKNOWN"


class ProcessProbeState(str, enum.Enum):
    """三态进程探测结果（doc §5.4.1）。

    禁止让调用方通过"空 PID 集"或 ``False`` 自行推断死亡；所有检查异常
    必须映射为 ``UNKNOWN``，而不是制造假死亡证明。
    """

    LIVE = "LIVE"
    CONFIRMED_DEAD = "CONFIRMED_DEAD"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TerminationResult:
    """终止结果（doc §5.4.4）。

    ``confirmed_dead`` 三态语义：
    - ``True``  ：根进程明确退出 + 所有已登记 identity 明确不存在 +
      containment 明确为空 + 本轮没有 UNKNOWN 探测；
    - ``False`` ：存在明确存活进程；
    - ``None``  ：无法确认（探测错误/未知），failure code 使用
      ``PROCESS_TREE_UNKNOWN`` 或具体探测错误码。禁止把 None 当成死亡证明。
    """

    confirmed_dead: Optional[bool]
    root_return_code: Optional[int]
    signals_sent: Tuple[str, ...] = ()
    tree_kill_used: bool = False
    elapsed_ms: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    remaining_pids: Tuple[int, ...] = ()
    root_identity_matches: Optional[bool] = None
    # P1（doc 审计 0c381413 §3.2）：最近一轮 per-spawn 谱系扫描"无法检查"
    # 的候选 PID。它们只表明扫描不完整（environ 暂时不可读），从未证明
    # 携带本 spawn token；仅作诊断展示（必须标注"无法检查"，不得显示为
    # "确认仍有子进程"），绝不进入 kill/known descendant 路径。
    inspection_unknown_pids: Tuple[int, ...] = ()


@dataclass(frozen=True)
class ProcessWaitResult:
    """Result of waiting for a root process and its complete process tree."""

    root_return_code: Optional[int]
    termination: TerminationResult


@dataclass(frozen=True)
class ProcessTreeSnapshot:
    """One off-loop process-tree inspection sample (doc §5.4.1/§12)."""

    state: ProcessProbeState = ProcessProbeState.UNKNOWN
    live_descendant_pids: Tuple[int, ...] = ()
    # 身份无法核实（UNKNOWN）的后代：apply_snapshot 必须保留这些 PID，
    # 绝不能因同一样本中的 LIVE 集合而被遗忘（doc 审计 P0-3A）。
    unknown_descendant_pids: Tuple[int, ...] = ()
    root_return_code: Optional[int] = None
    root_identity_matches: Optional[bool] = None
    remaining_pids: Tuple[int, ...] = ()
    failure_code: Optional[str] = None
    error_message: Optional[str] = None


def agent_stop_result_from_termination(
    termination: Optional[TerminationResult],
) -> AgentStopResult:
    """Convert a local supervisor termination result to the unified stop protocol.

    ``None`` 表示没有可停止的本地进程（从未启动）：stop_acknowledged=True 仅
    表示停止流程已执行；终态判定仍取决于 death 证据（此处为 None）。
    """
    if termination is None:
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
            stop_acknowledged=True,
            local_process_started=False,
            local_process_confirmed_dead=None,
        )
    confirmed = getattr(termination, "confirmed_dead", None)
    return AgentStopResult(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        stop_acknowledged=True,
        local_process_started=True,
        local_process_confirmed_dead=None if confirmed is None else bool(confirmed),
        failure_code=getattr(termination, "error_code", None),
        error_message=getattr(termination, "error_message", None),
        remaining_pids=tuple(getattr(termination, "remaining_pids", ()) or ()),
    )


def containment_id_for_run_token(run_token: Optional[str]) -> Optional[str]:
    """Stable attempt containment id derived from the durable run token.

    The id is available before the child PID exists so it can be persisted at
    job claim time and re-located by the reaper after a worker restart.
    """
    token = str(run_token or "").strip()
    return f"runtoken:{token}" if token else None
