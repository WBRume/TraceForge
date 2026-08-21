"""RAG Provider 工厂与协议。"""

from app.config import settings
from app.domains.rag.providers.base import RagProvider
from app.domains.rag.providers.httpx_provider import HttpRagProvider
from app.domains.rag.providers.mock_provider import MockRagProvider
from app.core.logging import get_logger

logger = get_logger(__name__, category="rag")


def create_provider() -> RagProvider:
    """根据配置创建 RAG Provider。

    具体平台（WeKnora / LLMWiki / OpenSearch / Qdrant 等）后续按选型结果新增。
    """
    provider_name = str(settings.RAG_PROVIDER or "").strip().lower() or "mock"
    if provider_name == "httpx":
        return HttpRagProvider(
            base_url=settings.RAG_API_BASE_URL,
            api_key=settings.RAG_API_KEY,
            timeout_seconds=settings.RAG_API_TIMEOUT_SECONDS,
        )
    if provider_name == "mock":
        return MockRagProvider()
    logger.warning("Unknown RAG_PROVIDER=%r, falling back to mock", provider_name)
    return MockRagProvider()