"""One Agent registration drives execution, discovery and configuration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from app.agents.contract import AgentBackend
from app.agents.errors import AgentConfigurationError
from app.agents.registration import AgentSetting, BackendRegistration

AGENT_BACKENDS: dict[str, BackendRegistration] = {}
_builtins_loaded = False


def register_backend(
    name: str,
    backend_cls: type[AgentBackend],
    *,
    label: str | None = None,
    selectable: bool = True,
    settings: tuple[AgentSetting, ...] = (),
    runtime_kwargs: dict[str, Any] | None = None,
    runtime_factory: Callable[[], Any] | None = None,
    probe_scope: Literal["connection", "binary", "simulation"] = "connection",
    model_format: Literal["opaque", "provider/model"] = "opaque",
) -> None:
    """Register an adapter and its configuration once, before serving requests."""
    if not name or name != name.strip() or backend_cls.name != name:
        raise AgentConfigurationError("Agent registration name must match the adapter name")
    if backend_cls.capabilities.supports_tool_binding and backend_cls.bind_tools is AgentBackend.bind_tools:
        raise AgentConfigurationError(f"{name} must implement bind_tools()")
    entry = BackendRegistration(
        backend_cls=backend_cls,
        label=label or name,
        selectable=selectable,
        settings=settings,
        runtime_kwargs=dict(runtime_kwargs or {}),
        runtime_factory=runtime_factory,
        probe_scope=probe_scope,
        model_format=model_format,
    )
    if name in AGENT_BACKENDS:
        if AGENT_BACKENDS[name] == entry:
            return
        raise AgentConfigurationError(f"Agent backend already registered: {name}")
    fields = [setting.field for item in (*AGENT_BACKENDS.values(), entry) for setting in item.settings]
    if len({field.key for field in fields}) != len(fields) or any(field.key == "backend" for field in fields):
        raise AgentConfigurationError("Agent configuration field keys must be unique")
    if len({field.env for field in fields}) != len(fields) or any(field.env == "AGENT_BACKEND" for field in fields):
        raise AgentConfigurationError("Agent configuration environment keys must be unique")
    if len({setting.parameter for setting in entry.settings}) != len(entry.settings):
        raise AgentConfigurationError("Agent constructor parameter bindings must be unique")
    AGENT_BACKENDS[name] = entry


def registered_backends() -> dict[str, BackendRegistration]:
    global _builtins_loaded
    if not _builtins_loaded:
        from app.agents.adapters import register_all

        register_all()
        _builtins_loaded = True
    return dict(AGENT_BACKENDS)


def backend_registration(name: str) -> BackendRegistration:
    entry = registered_backends().get(name)
    if entry is None:
        raise AgentConfigurationError(f"Unknown agent backend: {name!r}")
    return entry


def backend_config_kwargs(name: str, values: dict | None = None) -> dict[str, Any]:
    """Resolve saved runtime values, or an isolated configuration draft for probes."""
    from app.core.feature_settings import feature_settings

    kwargs = {}
    for setting in backend_registration(name).settings:
        field = setting.field
        if values is not None:
            value = values[field.key] if field.key in values else field.default()
        elif feature_settings.has_override(field.env):
            value = getattr(feature_settings, field.env)
        else:
            value = field.default()
        kwargs[setting.parameter] = value
    return kwargs


def create_agent_backend(name: str, **kwargs: Any) -> AgentBackend:
    return backend_registration(name).backend_cls(**kwargs)


def get_agent_backend(name: str | None = None, **kwargs: Any) -> AgentBackend:
    from app.core.feature_settings import feature_settings

    name = name or feature_settings.AGENT_BACKEND or "claude-code"
    return create_agent_backend(name, **(backend_config_kwargs(name) | kwargs))


def create_runtime_backend(name: str):
    entry = backend_registration(name)
    if entry.runtime_factory:
        return entry.runtime_factory()
    return get_agent_backend(name, **entry.runtime_kwargs)


def selectable_backend_names() -> tuple[str, ...]:
    return tuple(name for name, entry in registered_backends().items() if entry.selectable)
