"""Bounded protocol-based embeddings; credentials never leave the server."""

import asyncio
import json
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from app.core.feature_settings import feature_settings as settings
from app.domains.search.embedding_protocols import EmbeddingError, get_protocol
from app.domains.search.embedding_protocols import validate_vectors as validate_vectors


def cipher():
    if not settings.SEARCH_CONFIG_ENCRYPTION_KEY:
        raise EmbeddingError("SEARCH_CONFIG_ENCRYPTION_KEY_MISSING")
    return Fernet(settings.SEARCH_CONFIG_ENCRYPTION_KEY.encode())


def encrypt_key(key):
    if not key.strip() or set(key.strip()) <= {"*", "•"}:
        raise EmbeddingError("EMBEDDING_INVALID_KEY")
    if settings.SEARCH_CONFIG_ENCRYPTION_KEY:
        return cipher().encrypt(key.strip().encode()).decode()
    from app.domains.system_config.services.feature_config_service import cipher as feature_cipher

    return "feature:v1:" + feature_cipher().encrypt(key.strip().encode()).decode()


def decrypt_key(encrypted):
    if not encrypted:
        raise EmbeddingError("EMBEDDING_KEY_MISSING")
    try:
        if encrypted.startswith("feature:v1:"):
            from app.domains.system_config.services.feature_config_service import cipher as feature_cipher

            return feature_cipher().decrypt(encrypted.removeprefix("feature:v1:").encode()).decode()
        return cipher().decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise EmbeddingError("EMBEDDING_KEY_DECRYPT_FAILED") from None


def validate_endpoint(endpoint):
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise EmbeddingError("EMBEDDING_INVALID_ENDPOINT")
    return endpoint.rstrip("/")


def profile_key(profile, runtime_credentials):
    if runtime_credentials and settings.has_override("SEARCH_EMBEDDING_API_KEY"):
        if not settings.SEARCH_EMBEDDING_API_KEY:
            raise EmbeddingError("EMBEDDING_KEY_MISSING")
        if (
            profile["endpoint"] == settings.SEARCH_EMBEDDING_ENDPOINT
            and profile["model_id"] == settings.SEARCH_EMBEDDING_MODEL
            and (profile.get("protocol") or "openai_compatible") == settings.SEARCH_EMBEDDING_PROTOCOL
        ):
            return settings.SEARCH_EMBEDDING_API_KEY
    return decrypt_key(profile["encrypted_api_key"])


async def embed(client, profile, texts, *, query=False, runtime_credentials=True):
    if not 1 <= len(texts) <= 16 or not all(isinstance(t, str) and t.strip() for t in texts):
        raise EmbeddingError("EMBEDDING_INVALID_INPUT")
    timeout = settings.SEARCH_QUERY_EMBEDDING_TIMEOUT if query else settings.SEARCH_EMBEDDING_TIMEOUT
    prefix = profile.get("query_prefix" if query else "document_prefix", "")
    import httpx

    protocol = get_protocol(profile.get("protocol") or "openai_compatible")
    key = profile_key(profile, runtime_credentials)
    try:
        async with asyncio.timeout(timeout):
            async with client.stream(
                "POST",
                validate_endpoint(profile["endpoint"]),
                headers={"Authorization": "Bearer " + key},
                json=protocol.request(profile["model_id"], [prefix + t for t in texts], query=query),
            ) as response:
                if response.status_code != 200:
                    status = response.status_code
                    code = (
                        "EMBEDDING_AUTH_FAILED"
                        if status in (401, 403)
                        else "EMBEDDING_RATE_LIMITED"
                        if status == 429
                        else "EMBEDDING_PROVIDER_FAILED"
                    )
                    raise EmbeddingError(code, status == 429 or status >= 500)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 4 * 1024 * 1024:
                        raise EmbeddingError("EMBEDDING_RESPONSE_TOO_LARGE")
        return protocol.parse(json.loads(raw), len(texts), profile.get("dimension"))
    except (TimeoutError, httpx.TransportError):
        raise EmbeddingError("EMBEDDING_UNAVAILABLE", True) from None
    except (ValueError, TypeError):
        raise EmbeddingError("EMBEDDING_INVALID_RESPONSE") from None
