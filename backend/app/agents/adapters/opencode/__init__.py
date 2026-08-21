"""OpenCode adapter（Server 模式）。"""

from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.adapters.opencode.event_mapper import map_opencode_event

__all__ = ["OpenCodeAdapter", "map_opencode_event"]