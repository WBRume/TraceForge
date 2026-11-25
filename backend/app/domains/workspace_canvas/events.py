from app.domains.websocket.ws.connection import ConnectionRegistry

canvas_connections = ConnectionRegistry()


async def notify_canvas_changed(workspace_id: str) -> None:
    # Subscribers reload source data using their own workspace permissions.
    if canvas_connections.has_subscribers(workspace_id):
        canvas_connections.broadcast_json(workspace_id, {"type": "canvas_changed"}, sequenced=False)
