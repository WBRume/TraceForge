"""任务会话运行时（per-task agent session runtime）。

模块划分：
- engine.py      : TaskAgentEngine 编排器（回合生命周期 + 统一事件路由）
- registry.py    : 进程内引擎注册表 + 空闲收割 + 优雅关停
- gate.py        : SessionGate 事件门禁（内存判定 + TTL 重校验 + fence）
- persistence.py : 执行日志批 / context segment+snapshot 批 / 任务状态与指标
- frontend.py    : ThinkingStream + FrontendFeed（WS 推送 + 聊天消息持久化）
- turn_setup.py  : 回合准备纯函数（工作目录 / 技能物化 / env / AgentRunRequest）
"""

from app.engine.session.engine import TaskAgentEngine
from app.engine.session.gate import SessionGate
from app.engine.session.registry import (
    get_engine,
    register_engine,
    shutdown_active_engines,
    unregister_engine,
)

__all__ = [
    "TaskAgentEngine",
    "SessionGate",
    "get_engine",
    "register_engine",
    "unregister_engine",
    "shutdown_active_engines",
]
