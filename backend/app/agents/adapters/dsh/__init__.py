"""DSH adapter（SDK 模式）。"""

from app.agents.adapters.dsh.dsh_adapter import DSHAdapter
from app.agents.adapters.dsh.event_mapper import map_dsh_event

__all__ = ["DSHAdapter", "map_dsh_event"]