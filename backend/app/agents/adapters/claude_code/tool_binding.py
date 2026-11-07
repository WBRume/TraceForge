"""Provider settings for isolated Claude Code tool turns."""

import json
import os
from pathlib import Path


def provider_environment() -> dict[str, str]:
    # Never import project settings or arbitrary environment variables: hooks,
    # shell options and preload variables must not enter this restricted run.
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    path = home / "settings.json"
    if not path.is_file():
        return {}
    settings = json.loads(path.read_text(encoding="utf-8-sig"))
    allowed = {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    }
    values = {
        key: value for key, value in (settings.get("env") or {}).items() if key in allowed and isinstance(value, str)
    }
    if isinstance(settings.get("model"), str):
        values.setdefault("ANTHROPIC_MODEL", settings["model"])
    return values
