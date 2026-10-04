"""
WebSocket 消息 Pydantic Schemas
支持 log / status / hitl_request / chat_message / thinking / tool_use 等类型
"""

from typing import Any

from pydantic import BaseModel


class WSMessage(BaseModel):
    """WebSocket 下行消息基类"""

    type: str  # log | status | hitl_request | chat_message | thinking | tool_use | result | plan_update
    payload: Any


# ── 日志 ──
class WSLogPayload(BaseModel):
    task_id: str
    phase: str | None = None
    log_type: str = "STDOUT"
    content: str


# ── 阶段状态 ──
class WSStatusPayload(BaseModel):
    task_id: str
    status: str  # INIT / RUNNING / DONE / FAILED
    sub_task: str | None = None
    message: str
    job_id: str | None = None
    model: str | None = None
    duration_ms: int | None = None
    cost_usd: float | None = None


# ── HITL 请求 ──
class WSHitlRequest(BaseModel):
    task_id: str
    hitl_type: str  # boolean | select | text
    prompt: str
    job_id: str | None = None
    options: list[str] | None = None
    context: str | None = None


# ── HITL 回复 ──
class WSHitlResponse(BaseModel):
    task_id: str
    response: str
    job_id: str | None = None


# ── Chat 消息 ──
class WSChatPayload(BaseModel):
    task_id: str
    role: str  # user | assistant | system
    content: str
    message_type: str = "text"
    metadata: dict | None = None
    id: str | None = None
    client_message_id: str | None = None
    creator_id: str | None = None
    creator_display_name: str | None = None
    creator_is_workspace_expert: bool | None = None
    creator_avatar_url: str | None = None
    creator_avatar_svg: str | None = None
    created_at: str | None = None
    session_turn_id: str | None = None
    session_generation: int | None = None
    can_undo: bool | None = None
    # 共享内容版本（阅读条目身份）：不是任何个人进度；旧帧/临时气泡缺失时
    # 客户端先不确认，合并缺失 ID 后经 reading-items 补取
    reading_item_key: str | None = None
    reading_change_seq: str | None = None


# ── AI 思考过程 ──
# 统一帧协议：sequence 单调递增；delta 帧携带增量片段（前端 append），
# 快照帧 content 为全量累积 buffer（前端整体替换，缺 delta 字段）；
# final=True 为收口帧（本轮思考结束），此后不再有新帧。
class WSThinkingPayload(BaseModel):
    task_id: str
    content: str
    sequence: int = 0
    delta: str | None = None
    final: bool = False


# ── 工具调用 ──
class WSToolUsePayload(BaseModel):
    task_id: str
    tool_name: str
    tool_input: Any = None
    tool_use_id: str | None = None


# ── 工具结果 ──
class WSToolResultPayload(BaseModel):
    task_id: str
    tool_use_id: str
    output: str = ""
    is_error: bool = False


# ── 执行结果 ──
class WSResultPayload(BaseModel):
    task_id: str
    success: bool
    result: str = ""
    job_id: str | None = None
    duration_ms: int | None = None
    cost_usd: float | None = None
