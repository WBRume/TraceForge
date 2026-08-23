"""RagProvider 适配层协议。

后续对接具体平台时，只需实现该协议并注册到 factories。
"""

from __future__ import annotations

from typing import Protocol

from app.domains.rag.schemas import RagDocument


class RagProvider(Protocol):
    def upsert(self, document: RagDocument) -> bool:
        """把一篇标准 RAG 文档写入/覆盖到目标平台。"""
        ...

    def delete(self, doc_key: str, namespace: str = "knowledge") -> bool:
        """按 doc_key 删除目标平台中的文档。"""
        ...

    def health_check(self) -> bool:
        """用于连通性/存活检查，不是必需强一致。"""
        ...