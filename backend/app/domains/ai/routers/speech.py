"""Authenticated, bounded speech operations dispatched through provider plugins."""

import asyncio
import hmac
import io
import time
import wave
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response

from app.core.feature_settings import feature_settings as settings
from app.core.redis_client import get_redis_client
from app.dependencies import get_current_user
from app.domains.ai.speech.base import SpeechProviderError, SpeechSession
from app.domains.ai.speech.registry import get_provider, runtime_values
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
_RATE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return count
"""


async def _check_budget(user_id: str) -> None:
    try:
        redis = await get_redis_client()
        count = int(await redis.eval(_RATE_SCRIPT, 1, f"traceforge:speech:tokens:{user_id}"))
    except Exception as exc:
        raise HTTPException(503, "Speech credential service is temporarily unavailable") from exc
    if count > settings.SPEECH_TOKEN_REQUESTS_PER_MINUTE:
        raise HTTPException(429, "Too many speech sessions. Try again shortly.", headers={"Retry-After": "60"})


def _configured(transport):
    values = runtime_values()
    try:
        provider, selected = get_provider(values)
    except SpeechProviderError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    if values["mode"] != "api" or not provider.configured(values):
        raise HTTPException(503, "API voice input is not configured")
    if selected != transport:
        raise HTTPException(409, "Configured recognition method does not match this request")
    return values, provider


def _generation(values):
    from app.config import settings as environment
    from app.domains.system_config.services.feature_config_service import fingerprint

    return hmac.new(environment.JWT_SECRET_KEY.encode(), fingerprint(values).encode(), "sha256").hexdigest()


def _client(request):
    client = getattr(request.app.state, "speech_http_client", None)
    if client is None:
        raise HTTPException(503, "Speech service is not ready")
    return client


def _check_generation(request, values):
    generation = request.headers.get("X-Speech-Generation")
    if generation and not hmac.compare_digest(generation, _generation(values)):
        raise HTTPException(409, "Speech configuration changed; start a new recording")


def _no_cache(response):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


@router.post("/sessions", response_model=SpeechSession, status_code=201)
async def create_speech_session(
    request: Request, response: Response, user: User = Depends(get_current_user)
) -> SpeechSession:
    values, provider = _configured("websocket")
    _check_generation(request, values)
    client = _client(request)
    await _check_budget(user.id)
    started = time.perf_counter()
    try:
        session = await provider.create_session(client, values)
    except SpeechProviderError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    _no_cache(response)
    response.headers["Server-Timing"] = f"speech-token;dur={(time.perf_counter() - started) * 1000:.1f}"
    return session


MAX_AUDIO_BYTES = 16000 * 2 * 60 + 4096


async def _read_audio(request):
    raw = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > MAX_AUDIO_BYTES:
                    raise HTTPException(413, "Recording exceeds the 60-second limit")
                raw.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "Audio upload timed out") from None
    try:
        with wave.open(io.BytesIO(raw), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                raise ValueError
            frames = audio.getnframes()
            if not 1600 <= frames <= 16000 * 60 or len(audio.readframes(frames)) != frames * 2:
                raise ValueError
    except (wave.Error, EOFError, ValueError):
        raise HTTPException(422, "Expected 0.1–60 seconds of mono 16 kHz PCM16 WAV audio") from None
    return bytes(raw)


async def _until_disconnect(request, operation):
    async def disconnected():
        while (await request.receive())["type"] != "http.disconnect":
            pass

    work = asyncio.create_task(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if work in done:
            return work.result()
        raise HTTPException(499, "Speech request canceled")
    finally:
        work.cancel()
        watcher.cancel()
        await asyncio.gather(work, watcher, return_exceptions=True)


@router.post("/transcriptions")
async def transcribe_speech(request: Request, response: Response, user: User = Depends(get_current_user)):
    values, provider = _configured("http")
    _check_generation(request, values)
    client = _client(request)
    await _check_budget(user.id)
    audio = await _read_audio(request)
    try:
        text = await _until_disconnect(request, provider.transcribe(client, values, audio))
    except SpeechProviderError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    _no_cache(response)
    return {"text": text}


@router.get("/capabilities")
async def speech_capabilities(response: Response, user: User = Depends(get_current_user)):
    values = runtime_values()
    try:
        provider, transport = get_provider(values)
        configured = provider.configured(values)
    except SpeechProviderError:
        transport, configured = "unavailable", False
    _no_cache(response)
    return {
        "mode": values["mode"],
        "provider": values["provider"],
        "transport": transport,
        "generation": _generation(values),
        "configured": values["mode"] != "api" or configured,
    }
