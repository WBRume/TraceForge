from typing import TypedDict

from app.domains.websocket.ws.connection import ConnectionRegistry

canvas_connections = ConnectionRegistry()


class CanvasViewer(TypedDict):
    id: str
    display_name: str
    avatar_url: str | None
    avatar_svg: str | None


_viewer_profiles: dict[str, dict[str, CanvasViewer]] = {}


def publish_canvas_presence(workspace_id: str, joined: CanvasViewer | None = None) -> None:
    online = canvas_connections.online_users(workspace_id)
    if not online:
        _viewer_profiles.pop(workspace_id, None)
        return

    profiles = _viewer_profiles.get(workspace_id, {})
    if joined:
        profiles[joined["id"]] = joined
    active = {user_id: profiles[user_id] for user_id in online if user_id in profiles}
    _viewer_profiles[workspace_id] = active
    canvas_connections.broadcast_json(
        workspace_id, {"type": "presence", "online_users": list(active.values())}, sequenced=False
    )


async def notify_canvas_changed(
    workspace_id: str, *, calendar: bool = False, plan_task_id: str | None = None, assets: bool = True
) -> None:
    # Subscribers reload source data using their own workspace permissions.
    if canvas_connections.has_subscribers(workspace_id):
        canvas_connections.broadcast_json(
            workspace_id,
            {"type": "canvas_changed", "calendar": calendar, "plan_task_id": plan_task_id, "assets": assets},
            sequenced=False,
        )
