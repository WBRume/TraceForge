"""Provider-neutral speech contracts. Secrets must never appear in public metadata."""

from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field

from app.domains.system_config.services.config_fields import ConfigField

SpeechTransport = Literal["http", "websocket"]


class SpeechProviderError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class SpeechSession(BaseModel):
    provider: str = "bailian"
    transport: Literal["websocket"] = "websocket"
    token: str = Field(repr=False)
    expires_at: int
    websocket_url: str
    model: str


@dataclass(frozen=True)
class SpeechProbe:
    verified: bool
    explanation: str
    guidance: str = ""


class SpeechProvider(Protocol):
    label: str
    transports: tuple[SpeechTransport, ...]
    default_transport: SpeechTransport
    config_fields: tuple[ConfigField, ...]

    def configured(self, values: dict) -> bool: ...

    async def create_session(self, client: httpx.AsyncClient, values: dict) -> SpeechSession: ...

    async def transcribe(self, client: httpx.AsyncClient, values: dict, audio: bytes) -> str: ...

    async def probe(self, client: httpx.AsyncClient, values: dict, *, draft: bool) -> SpeechProbe: ...
