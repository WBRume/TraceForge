"""
FastAPI 主入口
包含 CORS 配置、路由挂载和 WebSocket 端点
"""

import sys
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.routers import auth, workspace, task, dashboard, asset, upload
from app.ws.manager import manager
from app.engine.workflow_engine import get_engine
from app.schemas.websocket import WSMessage, WSChatPayload

# ── 日志配置 ──
logger.remove()
logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
logger.add(f"{settings.LOG_DIR}/sdd_app.log", rotation="50 MB", retention="10 days", level=settings.LOG_LEVEL)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="规范驱动开发基础平台 API"
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.middleware.logging_middleware import LoggingMiddleware
app.add_middleware(LoggingMiddleware)

# ── 路由挂载 ──
app.include_router(auth.router, prefix="/api")
app.include_router(workspace.router, prefix="/api")
app.include_router(task.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(asset.router, prefix="/api")
app.include_router(upload.router, prefix="/api")

# ── 静态文件挂载 ──
# app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ── WebSocket 端点 ──
@app.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await manager.connect(websocket, task_id)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "chat_message":
                # 用户发送消息 → 转发给 CLI 引擎
                payload = data.get("payload", {})
                user_content = payload.get("content", "")
                if not user_content.strip():
                    continue

                logger.info(f"User chat for task {task_id}: {user_content[:80]}")

                engine = get_engine(task_id)
                if engine:
                    # 引擎存在 → 以 --resume 方式启动新 CLI 轮次
                    asyncio.create_task(engine.send_message(user_content))
                else:
                    logger.warning(f"No engine for task {task_id}, message ignored")

            elif msg_type == "hitl_response":
                # HITL 回复 → 以用户回答恢复 CLI 会话
                payload = data.get("payload", {})
                response = payload.get("response", "")
                if not response.strip():
                    continue

                logger.info(f"HITL response for task {task_id}: {response[:80]}")

                engine = get_engine(task_id)
                if engine:
                    asyncio.create_task(engine.send_message(response))

    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        manager.disconnect(websocket, task_id)


@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
