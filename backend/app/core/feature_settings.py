"""Business settings snapshot. Infrastructure always remains owned by app.config."""

from types import MappingProxyType

from pydantic import SecretStr

from app.config import settings as environment


class FeatureSettings:
    def __init__(self):
        self._overrides = MappingProxyType({})

    def replace(self, values):
        # One pointer swap: readers never observe a partially hydrated snapshot.
        self._overrides = MappingProxyType(dict(values))

    def has_override(self, name):
        return name in self._overrides

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(environment, name, value)

    def __getattr__(self, name):
        if name in self._overrides:
            value = self._overrides[name]
            return SecretStr(value) if name == "SPEECH_API_KEY" else value
        if name == "SPEECH_MODE":
            return environment.SPEECH_MODE or ("api" if environment.SPEECH_API_ENABLED else "off")
        if name == "OAUTH_GITHUB_ENABLED":
            return bool(
                getattr(environment, "OAUTH_GITHUB_CLIENT_ID", "")
                and getattr(environment, "OAUTH_GITHUB_CLIENT_SECRET", "")
            )
        if name == "SPEECH_API_ENABLED" and "SPEECH_MODE" in self._overrides:
            return self._overrides["SPEECH_MODE"] == "api"
        return getattr(environment, name)


feature_settings = FeatureSettings()
