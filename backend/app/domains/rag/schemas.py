"""
RAG 适配层标准数据模型。

当前设计边界：只定义适配层协议与标准文档，不绑定具体 RAG 平台。

案例同步队列（人工导出导入 RAG）：
- 队列是批次的载体：审批通过的案例被追加到当前 RUNNING 队列，
  没有 RUNNING 队列时自动新建；队列被整体打包下载成功后进入 CONSUMED 终态。
- 案例状态只围绕「导出下载」：QUEUED（待下载）→ EXPORTED（已导出锁定，可重下）。
- 自动 RAG 摄入已停用，下载完成后由操作人员自行导入 RAG。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RagSourceType(str, PyEnum):
    CASE = "case"


class RagNamespace(str, PyEnum):
    KNOWLEDGE = "knowledge"


class RagVisibility(str, PyEnum):
    PUBLIC = "public"
    WORKSPACE = "workspace"


class RagStatus(str, PyEnum):
    PUBLISHED = "published"


class RagOutboxStatus(str, PyEnum):
    """案例在同步队列内的导出状态。"""

    QUEUED = "QUEUED"
    EXPORTED = "EXPORTED"


class RagQueueStatus(str, PyEnum):
    """案例同步队列生命周期状态。"""

    RUNNING = "RUNNING"
    CONSUMED = "CONSUMED"


class RagChunk(BaseModel):
    id: str
    text: str
    heading: Optional[str] = None


class RagDocument(BaseModel):
    doc_id: str
    source_type: str = RagSourceType.CASE.value
    source_id: str
    workspace_id: str
    namespace: str = RagNamespace.KNOWLEDGE.value
    visibility: str = RagVisibility.WORKSPACE.value
    status: str = RagStatus.PUBLISHED.value
    version: int = 1
    title: str = ""
    content: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunks: List[RagChunk] = Field(default_factory=list)


class RagQueueItem(BaseModel):
    """案例同步队列条目：按工作区隔离，面向操作人员的批次。"""

    id: str
    name: str
    workspace_id: Optional[str] = None
    status: str = ""
    case_count: int = 0
    exported_count: int = 0
    created_at: Optional[datetime] = None
    consumed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RagQueuePageResponse(BaseModel):
    items: List[RagQueueItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class RagQueueCaseItem(BaseModel):
    """同步队列内的案例条目（面向操作人员展示与下载）。"""

    id: str
    doc_key: str
    case_id: Optional[str] = None
    workspace_id: Optional[str] = None
    title: Optional[str] = None
    version: Optional[int] = None
    status: str = ""
    exported_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RagQueueCasePageResponse(BaseModel):
    items: List[RagQueueCaseItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50