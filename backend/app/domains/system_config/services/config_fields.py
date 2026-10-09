"""Typed configuration fields shared by the feature catalog and provider plugins."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import SecretStr

from app.config import settings


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    env: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 4096
    hint: str = ""
    visible_when: tuple[tuple[str, tuple[str, ...]], ...] = ()
    option_labels: tuple[tuple[str, str], ...] = ()
    group: str = ""

    def default(self):
        if self.env == "SPEECH_MODE":
            return settings.SPEECH_MODE or ("api" if settings.SPEECH_API_ENABLED else "off")
        if self.env == "OAUTH_GITHUB_ENABLED":
            return bool(settings.OAUTH_GITHUB_CLIENT_ID and settings.OAUTH_GITHUB_CLIENT_SECRET)
        value = getattr(settings, self.env)
        return value.get_secret_value() if isinstance(value, SecretStr) else value

    def validate(self, value):
        if self.kind == "boolean":
            return type(value) is bool
        if self.kind == "number":
            return type(value) is int and self.minimum <= value <= self.maximum
        if not isinstance(value, str) or len(value) > self.maximum:
            return False
        if self.options:
            return value in self.options
        if self.kind == "secret":
            if self.key in {"api_key", "embedding_api_key"} and "********" in value:
                return False
            return not value or not set(value) <= {"*", "•"}
        if self.kind in {"url", "https"} and value:
            try:
                parts = urlsplit(value)
                valid_port = parts.port is None or 1 <= parts.port <= 65535
            except ValueError:
                return False
            schemes = {"https"} if self.kind == "https" else {"https", "http"}
            return bool(
                parts.scheme in schemes
                and parts.hostname
                and valid_port
                and not (parts.username or parts.password or parts.query or parts.fragment)
            )
        return True
