"""
WebSocket Manager 
"""

import json
from typing import Dict, Set
from fastapi import WebSocket
from loguru import logger
from app.schemas.websocket import WSMessage


class ConnectionManager:
    def __init__(self):
        # task_id -> set of active websocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = set()
        self.active_connections[task_id].add(websocket)
        logger.info(f"Client connected to task {task_id}")

    def disconnect(self, websocket: WebSocket, task_id: str):
        if task_id in self.active_connections:
            self.active_connections[task_id].discard(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
        logger.info(f"Client disconnected from task {task_id}")

    async def send_message_to_room(self, task_id: str, message: WSMessage):
        """发送结构化消息到特定任务的所有订阅者"""
        if task_id not in self.active_connections:
            return
            
        json_data = message.json()
        sockets_to_remove = set()
        
        for connection in self.active_connections[task_id]:
            try:
                await connection.send_text(json_data)
            except Exception as e:
                logger.error(f"Failed to send to websocket: {e}")
                sockets_to_remove.add(connection)
                
        # 清理断开的连接
        for dead_connection in sockets_to_remove:
            self.disconnect(dead_connection, task_id)


manager = ConnectionManager()
