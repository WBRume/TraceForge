"""通用 HTTP RAG Provider。

这是后续对接具体 RAG 平台的基座实现：
- 默认 upsert 路径：POST {base_url}/documents/upsert
- 默认 delete 路径：DELETE {base_url}/documents/{doc_key}
- 支持 Bearer Token 鉴权

具体平台（WeKnora / LLMWiki 等）后续在 Phase 2 基于此协议单独实现。
"""

from __future__ import annotations

from typing import Dict, Optional

import httpx

from app.core.logging import get_logger
from app.domains.rag.providers.base import RagProvider
from app.domains.rag.schemas import RagDocument

logger = get_logger(__name__, category="rag")


class HttpRagProvider(RagProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout_seconds: int = 10,
        upsert_path: str = "/documents/upsert",
        delete_path: str = "/documents/{doc_key}",
    ) -> None:
        self._base_url = str(base_url or "").rstrip("/")
        self._api_key = str(api_key or "").strip()
        self._timeout_seconds = timeout_seconds
        self._upsert_path = upsert_path
        self._delete_path = delete_path
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers=self._headers(),
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def upsert(self, document: RagDocument) -> bool:
        url = f"{self._base_url}{self._upsert_path}"
        try:
            resp = self._client.post(url, json={"document": document.model_dump()})
            if resp.status_code >= 400:
                logger.error(
                    "RAG upsert failed status=%s url=%s body=%s",
                    resp.status_code,
                    url,
                    resp.text[:500],
                )
                return False
            return True
        except httpx.HTTPError as exc:
            logger.error("RAG upsert http error url=%s err=%s", url, exc)
            return False

    def delete(self, doc_key: str, namespace: str = "knowledge") -> bool:
        path = self._delete_path.format(doc_key=doc_key, namespace=namespace)
        url = f"{self._base_url}{path}"
        try:
            resp = self._client.delete(url)
            if resp.status_code >= 400:
                logger.error(
                    "RAG delete failed status=%s url=%s body=%s",
                    resp.status_code,
                    url,
                    resp.text[:500],
                )
                return False
            return True
        except httpx.HTTPError as exc:
            logger.error("RAG delete http error url=%s err=%s", url, exc)
            return False

    def health_check(self) -> bool:
        url = f"{self._base_url}/health"
        try:
            resp = self._client.get(url)
            return resp.status_code < 400
        except httpx.HTTPError:
            return False