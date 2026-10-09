"""Bailian temporary credentials; the browser plugin streams audio directly."""

import time

import httpx

from app.domains.ai.speech.base import SpeechProbe, SpeechProviderError, SpeechSession
from app.domains.system_config.services.config_fields import ConfigField

DEFAULT_MODEL = "qwen-audio-3.1-asr-flash-streaming"


class BailianSpeechProvider:
    label = "阿里云百炼"
    transports = ("websocket",)
    default_transport = "websocket"
    config_fields = (
        ConfigField(
            "region",
            "百炼服务地域",
            "SPEECH_API_REGION",
            "select",
            ("beijing", "singapore"),
            hint="API Key 所属地域必须与所选地域一致。",
        ),
        ConfigField(
            "token_ttl",
            "临时凭据有效期（秒）",
            "SPEECH_TOKEN_TTL_SECONDS",
            "number",
            minimum=60,
            maximum=300,
            group="credentials",
            hint="仅向客户端下发短期凭据；取值为 60–300 秒。",
        ),
    )

    def configured(self, values):
        return bool(values.get("api_key", "").strip()) and values.get("region", "beijing") in {"beijing", "singapore"}

    async def create_session(self, client, values):
        host = (
            "dashscope.aliyuncs.com" if values.get("region", "beijing") == "beijing" else "dashscope-intl.aliyuncs.com"
        )
        try:
            result = await client.post(
                f"https://{host}/api/v1/tokens",
                params={"expire_in_seconds": values.get("token_ttl", 120)},
                headers={"Authorization": "Bearer " + values["api_key"].strip()},
            )
            result.raise_for_status()
            data = result.json()
            token, expires_at = data["token"], int(data["expires_at"])
            if not isinstance(token, str) or not token.startswith("st-") or expires_at <= int(time.time()):
                raise ValueError("Invalid temporary credential")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise SpeechProviderError("Unable to obtain speech credentials from provider") from exc
        return SpeechSession(
            token=token,
            expires_at=expires_at,
            websocket_url=f"wss://{host}/api-ws/v1/inference",
            model=values.get("model", "").strip() or DEFAULT_MODEL,
        )

    async def transcribe(self, client, values, audio):
        raise SpeechProviderError("Selected provider does not support HTTP transcription", 409)

    async def probe(self, client, values, *, draft):
        await self.create_session(client, values | {"token_ttl": 60})
        return SpeechProbe(True, "流式识别凭据与共享限流组件可用")
