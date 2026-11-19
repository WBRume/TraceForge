"""Metadata shared by construction, settings, model selection and discovery."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from app.agents.contract import AgentBackend
from app.domains.system_config.services.config_fields import ConfigField


@dataclass(frozen=True)
class AgentSetting:
    parameter: str
    field: ConfigField


@dataclass(frozen=True)
class BackendRegistration:
    backend_cls: type[AgentBackend]
    label: str
    selectable: bool = True
    settings: tuple[AgentSetting, ...] = ()
    runtime_kwargs: dict[str, Any] = field(default_factory=dict)
    runtime_factory: Callable[[], Any] | None = None
    probe_scope: Literal["connection", "binary", "simulation"] = "connection"
    model_format: Literal["opaque", "provider/model"] = "opaque"


def agent_config_fields() -> tuple[ConfigField, ...]:
    from .registry import registered_backends

    registrations = registered_backends()
    return (
        ConfigField(
            "backend",
            "默认 Agent 后端",
            "AGENT_BACKEND",
            "select",
            tuple(registrations),
            option_labels=tuple((name, entry.label) for name, entry in registrations.items()),
            hint="作用：新会话默认使用的 Agent 引擎。前提：引擎已配置且可连通；工作区可以覆盖此选择。",
        ),
        *(
            setting.field
            if any(key == "backend" for key, _ in setting.field.visible_when)
            else replace(setting.field, visible_when=(("backend", (name,)), *setting.field.visible_when))
            for name, entry in registrations.items()
            for setting in entry.settings
        ),
    )
