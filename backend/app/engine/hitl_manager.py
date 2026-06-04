"""
HITL (Human-in-the-Loop) 管理器
处理交互式挂起与恢复
"""

import asyncio
from typing import Dict, Optional, Any
from app.core.logging import get_logger
from app.domains.websocket.ws.manager import manager as ws_manager
from app.domains.ai.schemas.websocket import WSMessage, WSHitlRequest

logger = get_logger(__name__, category="task_execution")


class HitlManager:
    def __init__(self):
        # task_id -> asyncio.Event (用于挂起子进程读取)
        self.suspend_events: Dict[str, asyncio.Event] = {}
        # task_id -> user response payload
        self.responses: Dict[str, Any] = {}

    def register_task(self, task_id: str):
        self.suspend_events[task_id] = asyncio.Event()

    def cleanup_task(self, task_id: str):
        if task_id in self.suspend_events:
            self.suspend_events[task_id].set()  # 释放可能堵塞的协程
            del self.suspend_events[task_id]
        if task_id in self.responses:
            del self.responses[task_id]

    async def request_human_input(
        self, 
        task_id: str, 
        hitl_type: str, 
        prompt: str, 
        options: Optional[list[str]] = None,
        context: Optional[str] = None
    ) -> str:
        """
        触发前端 HITL 并挂起当前协程，直到收到恢复信号
        """
        logger.info(f"Task {task_id} suspended for HITL: {prompt}")
        
        # 准备挂起事件
        if task_id not in self.suspend_events:
            self.register_task(task_id)
        event = self.suspend_events[task_id]
        event.clear()
        
        # 发送 WebSocket 消息到前端
        req = WSHitlRequest(
            task_id=task_id, 
            hitl_type=hitl_type,
            prompt=prompt,
            options=options,
            context=context
        )
        msg = WSMessage(type="hitl_request", payload=req.model_dump())
        await ws_manager.send_message_to_room(task_id, msg)
        
        # 等待前端回复 (此时子进程输出读取协程被挂起，不会继续丢入 PTY 缓冲区)
        await event.wait()
        
        # 获取回复并清理
        response = self.responses.pop(task_id, "")
        logger.info(f"Task {task_id} resumed with response: {response}")
        return response

    async def provide_response(self, task_id: str, response: str):
        """
        由 API/Controller 调用，提供用户的选择并恢复挂起的协程
        """
        if task_id in self.suspend_events:
            self.responses[task_id] = response
            self.suspend_events[task_id].set()
            return True
        return False


hitl_manager = HitlManager()
