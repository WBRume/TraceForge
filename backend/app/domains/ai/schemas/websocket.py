"""
WebSocket 消息 Pydantic Schemas
支持 log / status / hitl_request / chat_message / thinking / tool_use 等类型
"""

from pydantic import BaseModel
from typing import Optional, Any, List


class WSMessage(BaseModel):
    """WebSocket 下行消息基类"""
    type: str  # log | status | hitl_request | chat_message | thinking | tool_use | result | plan_update
    payload: Any


# ── 日志 ──
class WSLogPayload(BaseModel):
    task_id: str
    phase: Optional[str] = None
    log_type: str = "STDOUT"
    content: str


# ── 阶段状态 ──
class WSStatusPayload(BaseModel):
    task_id: str
    status: str  # INIT / RUNNING / DONE / FAILED
    sub_task: Optional[str] = None
    message: str
    job_id: Optional[str] = None
    model: Optional[str] = None
    duration_ms: Optional[int] = None
    cost_usd: Optional[float] = None


# ── HITL 请求 ──
class WSHitlRequest(BaseModel):
    task_id: str
    hitl_type: str  # boolean | select | text
    prompt: str
    job_id: Optional[str] = None
    options: Optional[List[str]] = None
    context: Optional[str] = None


# ── HITL 回复 ──
class WSHitlResponse(BaseModel):
    task_id: str
    response: str
    job_id: Optional[str] = None


# ── Chat 消息 ──
class WSChatPayload(BaseModel):
    task_id: str
    role: str  # user | assistant | system
    content: str
    message_type: str = "text"
    metadata: Optional[dict] = None
    id: Optional[str] = None
    client_message_id: Optional[str] = None
    creator_id: Optional[str] = None
    creator_display_name: Optional[str] = None
    creator_is_workspace_expert: Optional[bool] = None
    created_at: Optional[str] = None


# ── AI 思考过程 ──
class WSThinkingPayload(BaseModel):
    task_id: str
    content: str


# ── 工具调用 ──
class WSToolUsePayload(BaseModel):
    task_id: str
    tool_name: str
    tool_input: Any = None
    tool_use_id: Optional[str] = None


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
    job_id: Optional[str] = None
    duration_ms: Optional[int] = None
    cost_usd: Optional[float] = None
