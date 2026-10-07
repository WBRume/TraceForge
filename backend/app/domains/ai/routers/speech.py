"""Authenticated credential issuance; audio flows directly to Bailian."""

import hmac
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.feature_settings import feature_settings as settings
from app.core.redis_client import get_redis_client
from app.dependencies import get_current_user
from app.domains.auth.models.user import User


@asynccontextmanager
async def speech_lifespan(app: FastAPI):
    # Reuse TLS/HTTP connections instead of initializing a client on every click.
    async with httpx.AsyncClient(
        timeout=8.0,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5, keepalive_expiry=60),
    ) as client:
        app.state.speech_http_client = client
        try:
            yield
        finally:
            app.state.speech_http_client = None


router = APIRouter(prefix="/speech", tags=["Speech"], lifespan=speech_lifespan)
MODEL = "qwen-audio-3.1-asr-flash-streaming"
_RATE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return count
"""


class SpeechSession(BaseModel):
    token: str = Field(repr=False)
    expires_at: int
    websocket_url: str
    model: str = MODEL


async def _check_budget(user_id: str) -> None:
    try:
        redis = await get_redis_client()
        count = int(await redis.eval(_RATE_SCRIPT, 1, f"traceforge:speech:tokens:{user_id}"))
    except Exception as exc:
        raise HTTPException(503, "Speech credential service is temporarily unavailable") from exc
    if count > settings.SPEECH_TOKEN_REQUESTS_PER_MINUTE:
        raise HTTPException(429, "Too many speech sessions. Try again shortly.", headers={"Retry-After": "60"})


async def _issue_token(client: httpx.AsyncClient, host: str, api_key: str) -> tuple[str, int]:
    try:
        result = await client.post(
            f"https://{host}/api/v1/tokens",
            params={"expire_in_seconds": settings.SPEECH_TOKEN_TTL_SECONDS},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        result.raise_for_status()
        data = result.json()
        token, expires_at = data["token"], int(data["expires_at"])
        if not isinstance(token, str) or not token.startswith("st-") or expires_at <= int(time.time()):
            raise ValueError("Invalid temporary credential")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        # Do not expose upstream bodies, credentials, or request URLs in responses.
        raise HTTPException(502, "Unable to obtain speech credentials from Bailian") from exc
    return token, expires_at


@router.post("/sessions", response_model=SpeechSession, status_code=201)
async def create_speech_session(
    request: Request, response: Response, user: User = Depends(get_current_user)
) -> SpeechSession:
    api_key = settings.SPEECH_API_KEY.get_secret_value().strip()
    if settings.SPEECH_MODE != "api" or not api_key:
        raise HTTPException(503, "API voice input is not configured")
    client = getattr(request.app.state, "speech_http_client", None)
    if client is None:
        raise HTTPException(503, "Speech credential service is not ready")
    host = "dashscope.aliyuncs.com" if settings.SPEECH_API_REGION == "beijing" else "dashscope-intl.aliyuncs.com"
    await _check_budget(user.id)
    started = time.perf_counter()
    token, expires_at = await _issue_token(client, host, api_key)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Server-Timing"] = f"speech-token;dur={(time.perf_counter() - started) * 1000:.1f}"
    return SpeechSession(token=token, expires_at=expires_at, websocket_url=f"wss://{host}/api-ws/v1/inference")


@router.get("/capabilities")
async def speech_capabilities(response: Response, user: User = Depends(get_current_user)):
    from app.config import settings as environment
    from app.domains.system_config.services.feature_config_service import fingerprint

    response.headers["Cache-Control"] = "no-store, private"
    # Opaque generation changes release browser standby streams and credentials.
    generation = fingerprint(
        {
            "mode": settings.SPEECH_MODE,
            "region": settings.SPEECH_API_REGION,
            "key": settings.SPEECH_API_KEY.get_secret_value(),
            "token_ttl": settings.SPEECH_TOKEN_TTL_SECONDS,
            "requests_per_minute": settings.SPEECH_TOKEN_REQUESTS_PER_MINUTE,
        }
    )
    generation = hmac.new(environment.JWT_SECRET_KEY.encode(), generation.encode(), "sha256").hexdigest()
    return {
        "mode": settings.SPEECH_MODE,
        "generation": generation,
        "configured": settings.SPEECH_MODE != "api" or bool(settings.SPEECH_API_KEY.get_secret_value()),
    }
