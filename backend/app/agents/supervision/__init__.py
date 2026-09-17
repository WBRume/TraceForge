"""本地 Agent 进程监管（process supervision）。

从原 3456 行 ``process_supervisor.py`` 单体按领域边界拆分：

- :mod:`model`      —— 三态证据模型：状态枚举、failure code、快照与终止结果；
- :mod:`windows`    —— Win32 内核原语（Job Object / taskkill / 句柄）；
- :mod:`inspection` —— 有界 inspection executor（许可制队列，离环扫描入口）；
- :mod:`identity`   —— pidfd 身份绑定与安全信号发送（P0 安全路径唯一归属）；
- :mod:`tree`       —— 受管树三态采样（executor 侧纯函数）；
- :mod:`discovery`  —— /proc token 发现、身份窗口校验与 token 收敛引擎；
- :mod:`persisted`  —— 持久化 root/group 三态探测与聚合；
- :mod:`lineage`    —— per-spawn 谱系清理引擎（TERM→KILL 升级）；
- :mod:`managed`    —— ManagedAgentProcess 状态与生命周期 + 周期监控；
- :mod:`spawn`      —— spawn 编排：containment 门禁、平台分支、attach 回调；
- :mod:`reclaim`    —— 上一轮 boot 的进程回收（stop_persisted / discovery）；
- :mod:`supervisor` —— ProcessSupervisor 注册表与编排入口 + 单例。

依赖方向（无环）：``model ← windows ← inspection ← identity ←
tree/discovery/persisted ← lineage ← managed ← spawn/reclaim ← supervisor``。
本 ``__init__`` 只做公开 API 再导出，不含逻辑。
"""

from app.agents.supervision.model import (
    DETACHED_DESCENDANTS_UNRESOLVED,
    PROCESS_GROUP_UNKNOWN,
    PROCESS_TREE_UNKNOWN,
    RUN_TOKEN_ENV_VAR,
    SPAWN_TOKEN_ENV_VAR,
    TOKEN_DISCOVERY_UNKNOWN,
    ProcessProbeState,
    ProcessTreeSnapshot,
    ProcessWaitResult,
    TerminationResult,
    agent_stop_result_from_termination,
    containment_id_for_run_token,
)
from app.agents.supervision.inspection import (
    InspectionQueueSaturated,
    run_process_inspection,
    run_process_probe,
)
from app.agents.supervision.identity import (
    MemberBindingState,
    MemberIdentity,
)
from app.agents.supervision.discovery import (
    DiscoveredTokenProcess,
    TokenDiscoverySnapshot,
)
from app.agents.supervision.persisted import PersistedProcessSnapshot
from app.agents.supervision.lineage import SpawnLineageCleanup
from app.agents.supervision.tree import inspect_process_tree_snapshot
from app.agents.supervision.managed import ManagedAgentProcess, monitor_tree
from app.agents.supervision.spawn import containment_capability
from app.agents.supervision.supervisor import ProcessSupervisor, process_supervisor

__all__ = [
    "DiscoveredTokenProcess",
    "InspectionQueueSaturated",
    "ManagedAgentProcess",
    "MemberBindingState",
    "MemberIdentity",
    "PersistedProcessSnapshot",
    "ProcessProbeState",
    "ProcessSupervisor",
    "ProcessTreeSnapshot",
    "ProcessWaitResult",
    "PROCESS_GROUP_UNKNOWN",
    "PROCESS_TREE_UNKNOWN",
    "RUN_TOKEN_ENV_VAR",
    "SPAWN_TOKEN_ENV_VAR",
    "TOKEN_DISCOVERY_UNKNOWN",
    "DETACHED_DESCENDANTS_UNRESOLVED",
    "TerminationResult",
    "TokenDiscoverySnapshot",
    "SpawnLineageCleanup",
    "agent_stop_result_from_termination",
    "containment_capability",
    "containment_id_for_run_token",
    "inspect_process_tree_snapshot",
    "monitor_tree",
    "process_supervisor",
    "run_process_inspection",
    "run_process_probe",
]
