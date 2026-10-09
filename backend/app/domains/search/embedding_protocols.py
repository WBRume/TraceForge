"""Embedding wire protocols. Register new protocols here, not in search workers."""

import math
from typing import Any, Protocol


class EmbeddingError(RuntimeError):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class EmbeddingProtocol(Protocol):
    label: str

    def request(self, model: str, texts: list[str], *, query: bool) -> dict[str, Any]: ...

    def parse(self, payload: Any, count: int, dimension: int | None) -> list[list[float]]: ...


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
        if (
            len(vector) != dimension
            or not all(type(v) in (int, float) and math.isfinite(v) for v in vector)
            or not any(vector)
        ):
            raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
        vectors[index] = vector
    return vectors


class OpenAIEmbeddingProtocol:
    label = "OpenAI 兼容"

    def request(self, model, texts, *, query):
        return {"model": model, "input": texts, "encoding_format": "float"}

    def parse(self, payload, count, dimension):
        return validate_vectors(payload, count, dimension)


PROTOCOLS: dict[str, EmbeddingProtocol] = {"openai_compatible": OpenAIEmbeddingProtocol()}


def get_protocol(name: str) -> EmbeddingProtocol:
    if name not in PROTOCOLS:
        raise EmbeddingError("EMBEDDING_UNSUPPORTED_PROTOCOL")
    return PROTOCOLS[name]


def profile_fingerprint(profile: dict) -> str:
    from app.domains.search.projection import digest

    identity = [
        profile["endpoint"],
        profile["model_id"],
        profile["dimension"],
        profile.get("chunk_chars", 1600),
        profile.get("chunk_overlap", 160),
        profile.get("query_prefix", ""),
        profile.get("document_prefix", ""),
    ]
    protocol = profile.get("protocol") or "openai_compatible"
    # Keep existing OpenAI-compatible index identities stable during upgrade.
    if protocol != "openai_compatible":
        identity.append(protocol)
    return digest(identity)
