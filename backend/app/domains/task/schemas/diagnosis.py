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

from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class DiagnosisCodeContextItem(BaseModel):
    file_path: str = ""
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    snippet: Optional[str] = None
    note: Optional[str] = None


class DiagnosisSimilarCaseItem(BaseModel):
    title: str = ""
    similarity: Optional[str] = None   # 高/中/低
    summary: Optional[str] = None
    reference: Optional[str] = None    # 案例ID / 链接 / 关键词


class DiagnosisCallChainNode(BaseModel):
    seq: Optional[int] = None
    module: Optional[str] = None
    function: Optional[str] = None
    file_path: Optional[str] = None
    description: Optional[str] = None


class DiagnosisResultPayload(BaseModel):
    """结构化定位结果载荷（AI 输出 JSON 块与用户编辑共用）。"""

    summary: Optional[str] = None
    root_cause: Optional[str] = None
    evidence_chain: Optional[str] = None
    fix_suggestion: Optional[str] = None
    fix_code: Optional[str] = None
    code_context: List[DiagnosisCodeContextItem] = Field(default_factory=list)
    similar_cases: List[DiagnosisSimilarCaseItem] = Field(default_factory=list)
    call_chain: List[DiagnosisCallChainNode] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)


class DiagnosisResultUpsertRequest(DiagnosisResultPayload):
    pass


class DiagnosisResultResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    created_by_id: str
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    evidence_chain: Optional[str] = None
    fix_suggestion: Optional[str] = None
    fix_code: Optional[str] = None
    code_context: List[DiagnosisCodeContextItem] = Field(default_factory=list)
    similar_cases: List[DiagnosisSimilarCaseItem] = Field(default_factory=list)
    call_chain: List[DiagnosisCallChainNode] = Field(default_factory=list)
    confidence: int = 0
    status: str
    extracted_from_ai: bool = True
    extracted_at: Optional[datetime] = None
    source_chat_message_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
