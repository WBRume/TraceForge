"""Task API 路由聚合。

按业务簇拆分子路由（各子模块自带 /workspaces/{ws_id}/tasks 前缀）：

- crud:              任务创建受理（provision）/ 取消准备 / 列表 / 详情 / 关注 /
                     仓库 / 删除 / 导出 / 历史
- session_runs:      会话建立（start / initialize，业务编排在
                     task_session_control_service）
- session_control:   会话控制与状态（interrupt / resume / 消息撤销 / 聊天受理 /
                     会话快照 / AI 作业与上下文窗口查询 / 预输入兜底）
- spec_docs:         spec 资产 / 上传 / spec 基线（bootstrap）/ superpowers 文档
- skill_runtime:     Skills 运行时列表 / 事件 / 运行文件树与读写
- change_proposals:  变更提案创建（三重分布式锁编排）
- diagnosis:         问题定位辅助文档 / 定位结果 / 一键转案例 / 一键总结

get_db / get_current_user 在此 re-export：路由声明与测试 DI override 使用
同一可调用对象（app.dependencies 中的原函数）。
"""

from fastapi import APIRouter

from app.dependencies import get_current_user, get_db  # noqa: F401
from . import (
    change_proposals,
    crud,
    diagnosis,
    session_control,
    session_runs,
    skill_runtime,
    spec_docs,
)

router = APIRouter(tags=["Tasks"])
for _submodule in (
    crud,
    session_runs,
    session_control,
    spec_docs,
    skill_runtime,
    change_proposals,
    diagnosis,
):
    router.include_router(_submodule.router)
