"""
RAG 适配层标准数据模型。

当前设计边界：只定义适配层协议与标准文档，不绑定具体 RAG 平台。
"""

from __future__ import annotations

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
    PENDING = "PENDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


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