"""Mock RAG Provider：本地调试/测试用，不发送外部请求。"""

from __future__ import annotations

import threading
from typing import Dict

from app.domains.rag.providers.base import RagProvider
from app.domains.rag.schemas import RagDocument


class MockRagProvider(RagProvider):
    """纯内存 Mock，支持记录 upsert/delete，方便测试与本地联调。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.upserted: Dict[str, RagDocument] = {}
        self.deleted_keys: list[str] = []

    def upsert(self, document: RagDocument) -> bool:
        with self._lock:
            self.upserted[document.doc_id] = document
        return True

    def delete(self, doc_key: str, namespace: str = "knowledge") -> bool:
        with self._lock:
            self.deleted_keys.append(f"{namespace}:{doc_key}")
            self.upserted.pop(f"rag:case:{doc_key.split(':', 1)[-1]}", None)
        return True

    def health_check(self) -> bool:
        return True