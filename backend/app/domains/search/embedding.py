"""Bounded OpenAI-compatible embeddings; credentials never leave the server."""
import asyncio
import json
import math
from urllib.parse import urlsplit
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings


class EmbeddingError(RuntimeError):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


def cipher():
    if not settings.SEARCH_CONFIG_ENCRYPTION_KEY:
        raise EmbeddingError("SEARCH_CONFIG_ENCRYPTION_KEY_MISSING")
    return Fernet(settings.SEARCH_CONFIG_ENCRYPTION_KEY.encode())


def encrypt_key(key):
    if not key.strip() or set(key.strip()) <= {"*", "•"}:
        raise EmbeddingError("EMBEDDING_INVALID_KEY")
    return cipher().encrypt(key.strip().encode()).decode()


def decrypt_key(encrypted):
    if not encrypted:
        raise EmbeddingError("EMBEDDING_KEY_MISSING")
    try:
        return cipher().decrypt(encrypted.encode()).decode()
    except InvalidToken:
        raise EmbeddingError("EMBEDDING_KEY_DECRYPT_FAILED") from None


def validate_endpoint(endpoint):
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise EmbeddingError("EMBEDDING_INVALID_ENDPOINT")
    return endpoint.rstrip("/")


def validate_vectors(payload, count, dimension=None):
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != count:
        raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
    vectors = [None] * count
    for row in rows:
        if not isinstance(row, dict):
            raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
        index, vector = row.get("index"), row.get("embedding")
        if type(index) is not int or not 0 <= index < count or vectors[index] is not None:
            raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
        if not isinstance(vector, list) or not 1 <= len(vector) <= 4096:
            raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
        dimension = dimension or len(vector)
        if len(vector) != dimension or not all(type(v) in (int, float) and math.isfinite(v) for v in vector) or not any(vector):
            raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
        vectors[index] = vector
    return vectors


async def embed(client, profile, texts, *, query=False):
    if not 1 <= len(texts) <= 16 or not all(isinstance(t, str) and t.strip() for t in texts):
        raise EmbeddingError("EMBEDDING_INVALID_INPUT")
    timeout = settings.SEARCH_QUERY_EMBEDDING_TIMEOUT if query else settings.SEARCH_EMBEDDING_TIMEOUT
    prefix = profile.get("query_prefix" if query else "document_prefix", "")
    import httpx
    try:
        async with asyncio.timeout(timeout):
            async with client.stream("POST", validate_endpoint(profile["endpoint"]),
                    headers={"Authorization": "Bearer " + decrypt_key(profile["encrypted_api_key"])},
                    json={"model": profile["model_id"], "input": [prefix + t for t in texts], "encoding_format": "float"}) as response:
                if response.status_code != 200:
                    status = response.status_code
                    code = "EMBEDDING_AUTH_FAILED" if status in (401, 403) else "EMBEDDING_RATE_LIMITED" if status == 429 else "EMBEDDING_PROVIDER_FAILED"
                    raise EmbeddingError(code, status == 429 or status >= 500)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 4 * 1024 * 1024:
                        raise EmbeddingError("EMBEDDING_RESPONSE_TOO_LARGE")
        return validate_vectors(json.loads(raw), len(texts), profile.get("dimension"))
    except (TimeoutError, httpx.TransportError):
        raise EmbeddingError("EMBEDDING_UNAVAILABLE", True) from None
    except (ValueError, TypeError):
        raise EmbeddingError("EMBEDDING_INVALID_RESPONSE") from None
