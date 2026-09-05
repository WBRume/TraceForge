"""
FastAPI 主入口
包含 CORS 配置、路由挂载和 WebSocket 端点
"""

import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError

from app.config import settings
from app.core.offload import run_db, shutdown_offload_executors
from app.core.redis_client import close_redis_client
from app.core.logging import (
    bind_log_context,
    bind_task_context,
    get_logger,
    setup_logging,
)

setup_logging()
logger = get_logger(__name__)
api_mock_logger = get_logger(__name__, category="api_mock")

from app.database import SessionLocal
from app.domains.api_mock.models.api_mock import ApiMockCollabEventType
from app.domains.task.models.task import SddTask
from app.domains.auth.models.user import User
from app.middleware.logging_middleware import LoggingMiddleware
from app.domains.ai.routers import agent
from app.domains.auth.routers import auth, oauth
from app.domains.auth.errors import OAuthAPIError, oauth_api_error_handler
from app.domains.workspace.routers import workspace
from app.domains.task.routers import task
from app.domains.dashboard.routers import dashboard
from app.domains.asset.routers import asset
from app.domains.asset.routers import upload
from app.domains.skill.routers import skill
from app.domains.api_mock.routers import api_mock
from app.domains.workflow.routers import provision
from app.domains.ai.routers import queue
from app.domains.workspace_asset.routers import workspace_asset
from app.domains.task.routers import task_closeout
from app.domains.case_center.routers import case as case_center_router
from app.domains.asset.routers import decision
from app.domains.management.routers import (
    products_router,
    projects_router,
    repositories_router,
    repo_groups_router,
)
from app.domains.ai.services import ai_job_service
from app.domains.api_mock.services import api_mock_service
from app.domains.auth.services import auth_service
from app.domains.system_config.routers import system_config
from app.domains.workspace.services import workspace_service
from app.domains.websocket.ws.manager import manager
from app.domains.websocket.ws.task_handler import TaskWebSocketHandler, TaskWebSocketUser
from app.domains.notification.routers import notification as notification_router
from app.domains.notification.ws.notification_manager import notification_ws_manager
from app.domains.task.services import pre_input_worker as pre_input_deadline_worker
from app.domains.api_mock.ws.api_mock_manager import api_mock_ws_manager
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.rag.routers import outbox as rag_outbox_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="规范驱动开发基础平台 API"
)

_pre_input_worker_task: asyncio.Task | None = None

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LoggingMiddleware)

# ── OAuth 统一业务异常输出：{"detail": ..., "code": "OAUTH_XXX", **extra}（§4.5）──
app.add_exception_handler(OAuthAPIError, oauth_api_error_handler)


@app.on_event("startup")
async def _on_startup() -> None:
    global _pre_input_worker_task
    _pre_input_worker_task = asyncio.create_task(pre_input_deadline_worker.run_pre_input_worker())
    recovered_queue_count = await ai_job_service.recover_pending_queues()
    if recovered_queue_count:
        logger.info("Recovered {} pending AI job queues", recovered_queue_count)


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _pre_input_worker_task
    if _pre_input_worker_task is not None:
        _pre_input_worker_task.cancel()
        _pre_input_worker_task = None
    try:
        await api_mock_ws_manager.shutdown()
    except Exception:
        logger.warning("Failed to shutdown API MOCK redis listener")
    try:
        await close_redis_client()
    except Exception:
        logger.warning("Failed to close redis client on shutdown")
    try:
        shutdown_offload_executors()
    except Exception:
        logger.warning("Failed to shutdown offload executors")

# ── 路由挂载 ──
app.include_router(auth.router, prefix="/api")
app.include_router(oauth.router, prefix="/api")
app.include_router(workspace.router, prefix="/api")
app.include_router(task.router, prefix="/api")
app.include_router(task_closeout.router, prefix="/api")
app.include_router(case_center_router.router, prefix="/api")
app.include_router(case_center_router.global_router, prefix="/api")
app.include_router(decision.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(asset.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(skill.router, prefix="/api")
app.include_router(api_mock.router, prefix="/api")
app.include_router(provision.router, prefix="/api")
app.include_router(queue.router, prefix="/api")
app.include_router(workspace_asset.router, prefix="/api")
app.include_router(notification_router.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(repositories_router, prefix="/api")
app.include_router(repo_groups_router, prefix="/api")
app.include_router(system_config.router, prefix="/api")
app.include_router(rag_outbox_router.router, prefix="/api")
app.include_router(api_mock.gateway_router)

# ── 静态文件挂载 ──
# app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


async def _authenticate_task_ws(websocket: WebSocket, task_id: str) -> dict | None:
    """连接即鉴权（JOIN 一次）：JWT 解码留事件循环，DB 查询经 DB executor。"""
    token = str(websocket.query_params.get("token") or "").strip()
    if not token:
        return None

    try:
        payload = auth_service.decode_token(token, expected_type="access")
    except JWTError:
        return None

    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        return None

    def _load() -> dict | None:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            task_obj = db.query(SddTask).filter(SddTask.id == task_id).first()
            if not user or not task_obj:
                return None

            member = workspace_service.get_workspace_member(db, task_obj.workspace_id, user.id)
            if not member:
                return None

            return {
                "user_id": user.id,
                "display_name": user.display_name,
                "avatar_url": user.avatar_url,
                "avatar_svg": user.avatar_svg,
                "workspace_id": task_obj.workspace_id,
                "is_workspace_expert": bool(member.is_expert),
            }
        finally:
            db.close()

    return await run_db(_load)


async def _authenticate_user_ws(websocket: WebSocket) -> dict | None:
    """按用户维度认证（通知通道）：仅校验 JWT，不绑定工作区；DB 查询经 DB executor。"""
    token = str(websocket.query_params.get("token") or "").strip()
    if not token:
        return None
    try:
        payload = auth_service.decode_token(token, expected_type="access")
    except JWTError:
        return None
    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        return None

    def _load() -> dict | None:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return None
            return {"user_id": user.id, "display_name": user.display_name}
        finally:
            db.close()

    return await run_db(_load)


# ── WebSocket 端点 ──
@app.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str) -> None:
    ws_context = await _authenticate_task_ws(websocket, task_id)
    if not ws_context:
        await websocket.close(code=1008, reason="Unauthorized task websocket")
        return

    user = TaskWebSocketUser(
        id=str(ws_context["user_id"]),
        display_name=str(ws_context.get("display_name") or ""),
        is_workspace_expert=bool(ws_context.get("is_workspace_expert")),
        avatar_url=ws_context.get("avatar_url") or None,
        avatar_svg=ws_context.get("avatar_svg") or None,
    )

    with bind_task_context(
        task_id=task_id,
        workspace_id=str(ws_context.get("workspace_id") or ""),
        user_id=user.id,
    ):
        handler = TaskWebSocketHandler(
            websocket,
            task_id,
            user,
            session_factory=SessionLocal,
            connection_manager=manager,
        )
        await handler.run()


@app.websocket("/ws/notifications")
async def notification_websocket_endpoint(websocket: WebSocket):
    """站内信实时通道：按用户维度推送，前端断线重连时以 REST 未读数兜底。"""
    context = await _authenticate_user_ws(websocket)
    if not context:
        await websocket.close(code=1008, reason="Unauthorized notification websocket")
        return
    user_id = str(context["user_id"])
    await notification_ws_manager.connect(websocket, user_id)
    try:
        while True:
            # 通道只下行；忽略客户端上行（保活 ping 等）
            await websocket.receive_text()
    except WebSocketDisconnect:
        notification_ws_manager.disconnect(websocket, user_id)
    except Exception:
        logger.exception("Notification websocket endpoint failed")
        notification_ws_manager.disconnect(websocket, user_id)


@app.websocket("/ws/api-mock/{project_id}")
async def api_mock_websocket_endpoint(websocket: WebSocket, project_id: str):
    user_id = websocket.query_params.get("userId", "anonymous")
    with bind_log_context(project_id=project_id, user_id=user_id):
        await api_mock_ws_manager.connect(websocket, project_id, user_id)
        await api_mock_ws_manager.broadcast(
            project_id,
            {
                "type": "presence",
                "project_id": project_id,
                "online_users": api_mock_ws_manager.online_users(project_id),
            },
        )
        try:
            while True:
                data = await websocket.receive_json()
                event_type = str(data.get("type") or "draft").lower()
                payload = data.get("payload")
                endpoint_id = data.get("endpoint_id") or (payload or {}).get("endpoint_id")
                normalized_payload = payload if isinstance(payload, dict) else {"payload": payload}

                event_mapping = {
                    "draft": ApiMockCollabEventType.DRAFT,
                    "save": ApiMockCollabEventType.SAVE,
                    "conflict": ApiMockCollabEventType.CONFLICT,
                    "presence": ApiMockCollabEventType.PRESENCE,
                }
                event_enum = event_mapping.get(event_type, ApiMockCollabEventType.DRAFT)

                if user_id != "anonymous":
                    db = SessionLocal()
                    try:
                        project = api_mock_service.get_project_by_id(db, project_id)
                        if project:
                            try:
                                api_mock_service.create_collab_event(
                                    db,
                                    project,
                                    user_id=user_id,
                                    event_type=event_enum,
                                    endpoint_id=str(endpoint_id) if endpoint_id else None,
                                    payload=normalized_payload,
                                )
                            except Exception:
                                api_mock_logger.exception("Failed to persist API MOCK collab event")
                    finally:
                        db.close()

                await api_mock_ws_manager.broadcast(
                    project_id,
                    {
                        "type": "event",
                        "event": event_type,
                        "project_id": project_id,
                        "user_id": user_id,
                        "endpoint_id": endpoint_id,
                        "payload": normalized_payload,
                        "online_users": api_mock_ws_manager.online_users(project_id),
                    },
                )
        except WebSocketDisconnect:
            api_mock_ws_manager.disconnect(websocket, project_id)
            await api_mock_ws_manager.broadcast(
                project_id,
                {
                    "type": "presence",
                    "project_id": project_id,
                    "online_users": api_mock_ws_manager.online_users(project_id),
                },
            )
        except Exception:
            api_mock_logger.exception("API MOCK websocket endpoint failed")
            api_mock_ws_manager.disconnect(websocket, project_id)


@app.websocket("/ws/assets/{asset_id}/discussion")
async def asset_discussion_websocket_endpoint(websocket: WebSocket, asset_id: str):
    user_id = websocket.query_params.get("userId", "anonymous")
    with bind_log_context(asset_id=asset_id, user_id=user_id):
        await asset_discussion_ws_manager.connect(websocket, asset_id, user_id)
        await asset_discussion_ws_manager.broadcast(
            asset_id,
            {
                "type": "presence",
                "asset_id": asset_id,
                "online_users": asset_discussion_ws_manager.online_users(asset_id),
            },
        )
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = str(data.get("type") or "").lower()
                payload = data.get("payload")

                if msg_type in {"ping", "presence"}:
                    await asset_discussion_ws_manager.broadcast(
                        asset_id,
                        {
                            "type": "presence",
                            "asset_id": asset_id,
                            "online_users": asset_discussion_ws_manager.online_users(asset_id),
                        },
                    )
                    continue

                await asset_discussion_ws_manager.broadcast(
                    asset_id,
                    {
                        "type": "event",
                        "asset_id": asset_id,
                        "event": msg_type or "message",
                        "user_id": user_id,
                        "payload": payload,
                        "online_users": asset_discussion_ws_manager.online_users(asset_id),
                    },
                )
        except WebSocketDisconnect:
            asset_discussion_ws_manager.disconnect(websocket, asset_id)
            await asset_discussion_ws_manager.broadcast(
                asset_id,
                {
                    "type": "presence",
                    "asset_id": asset_id,
                    "online_users": asset_discussion_ws_manager.online_users(asset_id),
                },
            )
        except Exception:
            logger.exception("Asset discussion websocket endpoint failed")
            asset_discussion_ws_manager.disconnect(websocket, asset_id)


@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
