"""Read Claude Code model settings without making an inference request."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.agents.model_selection import model_option


def model_catalog(project_path: str = "") -> dict:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    paths = [home / "settings.json"]
    if project_path:
        paths.extend(Path(project_path) / ".claude" / name for name in ("settings.json", "settings.local.json"))
    managed = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "ClaudeCode" / "managed-settings.json"
        if os.name == "nt"
        else Path("/Library/Application Support/ClaudeCode/managed-settings.json")
        if sys.platform == "darwin"
        else Path("/etc/claude-code/managed-settings.json")
    )
    paths.append(managed)
    settings = {}
    env = dict(os.environ)
    for path in paths:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            settings.update(data)
            env.update(data.get("env") or {})
    default = env.get("ANTHROPIC_MODEL") or settings.get("model") or env.get("ANTHROPIC_DEFAULT_MODEL") or "default"
    allowed = settings.get("availableModels")
    aliases = allowed if isinstance(allowed, list) else ["default", "sonnet", "opus", "haiku", "opusplan"]
    options = []
    for alias in aliases:
        if not isinstance(alias, str) or not alias:
            continue
        mapped = env.get(f"ANTHROPIC_DEFAULT_{alias.upper()}_MODEL")
        label = "Claude Code 默认" if alias == "default" else f"{alias} · {mapped}" if mapped else alias
        options.append(model_option(alias, label))
    if default not in {item["value"] for item in options}:
        options.insert(0, model_option(default))
    return {"options": options, "default_model": default}
