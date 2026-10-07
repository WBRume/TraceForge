"""Agent backend 注册表。

默认每次 get_agent_backend() 返回新实例；adapter 可在内部复用底层连接。
"""

from __future__ import annotations

from typing import Any

from app.agents.contract import AgentBackend
from app.agents.errors import AgentConfigurationError

AGENT_BACKENDS: dict[str, type[AgentBackend]] = {}


def register_backend(name: str, backend_cls: type[AgentBackend]) -> None:
    """注册一个 Agent backend 实现。"""
    AGENT_BACKENDS[name] = backend_cls


def create_agent_backend(name: str, **kwargs: Any) -> AgentBackend:
    """按名称创建 Agent backend 实例。"""
    backend_cls = AGENT_BACKENDS.get(name)
    if backend_cls is None:
        from app.agents.adapters import register_all

        register_all()
        backend_cls = AGENT_BACKENDS.get(name)
    if backend_cls is None:
        raise AgentConfigurationError(f"Unknown agent backend: {name!r}")
    return backend_cls(**kwargs)


def get_agent_backend(name: str | None = None, **kwargs: Any) -> AgentBackend:
    """创建当前配置对应的 Agent backend 实例。"""
    from app.core.feature_settings import feature_settings as settings

    if name is None:
        name = getattr(settings, "AGENT_BACKEND", None) or "claude-code"
    defaults = {
        "opencode": {
            "server_url": "OPENCODE_SERVER_URL",
            "username": "OPENCODE_SERVER_USERNAME",
            "password": "OPENCODE_SERVER_PASSWORD",
        },
        "dsh": {
            "server_url": "DSH_SERVER_URL",
            "browser_token": "DSH_BROWSER_TOKEN",
            "browser_cookie": "DSH_BROWSER_COOKIE",
        },
    }
    for key, setting in defaults.get(name, {}).items():
        if settings.has_override(setting):
            kwargs.setdefault(key, getattr(settings, setting))
    return create_agent_backend(name, **kwargs)
