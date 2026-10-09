"""Explicit provider registration; only trusted deployment code supplies plugins."""

from dataclasses import replace

from app.domains.ai.speech.bailian import BailianSpeechProvider
from app.domains.ai.speech.base import SpeechProvider, SpeechProviderError
from app.domains.ai.speech.openai_compatible import OpenAICompatibleSpeechProvider

PROVIDERS: dict[str, SpeechProvider] = {
    "bailian": BailianSpeechProvider(),
    "openai_compatible": OpenAICompatibleSpeechProvider(),
}


def get_provider(values: dict) -> tuple[SpeechProvider, str]:
    provider = PROVIDERS.get(values.get("provider", "bailian"))
    if provider is None:
        raise SpeechProviderError("Unknown speech provider", 422)
    transport = values.get("transport", "auto")
    if transport == "auto":
        transport = provider.default_transport
    if transport not in provider.transports:
        raise SpeechProviderError("Selected speech provider does not support this recognition method", 422)
    return provider, transport


def provider_fields():
    seen = {"mode", "provider", "transport", "model", "api_key", "requests_per_minute"}
    fields = []
    for name, provider in PROVIDERS.items():
        for field in provider.config_fields:
            if field.key in seen:
                raise ValueError("Speech plugins must use unique configuration keys")
            seen.add(field.key)
            fields.append(
                replace(
                    field, visible_when=(("mode", ("api",)), ("provider", (name,))), group=field.group or "recognition"
                )
            )
    return tuple(fields)


def provider_catalog():
    return [
        {
            "id": name,
            "label": plugin.label,
            "transports": list(plugin.transports),
            "default_transport": plugin.default_transport,
        }
        for name, plugin in PROVIDERS.items()
    ]


def runtime_values():
    from pydantic import SecretStr

    from app.core.feature_settings import feature_settings
    from app.domains.system_config.services.feature_catalog import CATALOG

    values = {field.key: getattr(feature_settings, field.env) for field in CATALOG["speech"][1]}
    return {key: value.get_secret_value() if isinstance(value, SecretStr) else value for key, value in values.items()}
