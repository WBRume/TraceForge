"""
问题定位任务：定位结果 Pydantic Schemas

结构化结果协议（AI 会话反填 + 用户可编辑）：
- summary          AI 返回的结果内容（结论概述）
- root_cause       根因结论
- evidence_chain   证据链
- fix_suggestion   修复方案说明
- fix_code         修复代码/补丁（仅方案建议）
- code_context     相关代码上下文
- similar_cases    相似案例
- call_chain       调用链路
- confidence       置信度 0-100
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DiagnosisCodeContextItem(BaseModel):
    file_path: str = ""
    start_line: int | None = None
    end_line: int | None = None
    snippet: str | None = None
    note: str | None = None


class DiagnosisSimilarCaseItem(BaseModel):
    title: str = ""
    similarity: str | None = None  # 高/中/低
    summary: str | None = None
    reference: str | None = None  # 案例ID / 链接 / 关键词


class DiagnosisCallChainNode(BaseModel):
    seq: int | None = None
    module: str | None = None
    function: str | None = None
    file_path: str | None = None
    description: str | None = None


class DiagnosisResultPayload(BaseModel):
    """结构化定位结果载荷（AI 输出 JSON 块与用户编辑共用）。"""

    summary: str | None = None
    root_cause: str | None = None
    evidence_chain: str | None = None
    fix_suggestion: str | None = None
    fix_code: str | None = None
    code_context: list[DiagnosisCodeContextItem] = Field(default_factory=list)
    similar_cases: list[DiagnosisSimilarCaseItem] = Field(default_factory=list)
    call_chain: list[DiagnosisCallChainNode] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)


class DiagnosisResultUpsertRequest(DiagnosisResultPayload):
    pass


class DiagnosisResultResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    created_by_id: str
    summary: str | None = None
    root_cause: str | None = None
    evidence_chain: str | None = None
    fix_suggestion: str | None = None
    fix_code: str | None = None
    code_context: list[DiagnosisCodeContextItem] = Field(default_factory=list)
    similar_cases: list[DiagnosisSimilarCaseItem] = Field(default_factory=list)
    call_chain: list[DiagnosisCallChainNode] = Field(default_factory=list)
    confidence: int = 0
    status: str
    extracted_from_ai: bool = True
    extracted_at: datetime | None = None
    source_chat_message_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
