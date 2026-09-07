"""
FastAPI 主入口
包含 CORS 配置、路由挂载和 WebSocket 端点
"""

import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
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
from app.domains.api_mock.models.api_mock import ApiMockCollabEventType, SddApiMockProject
from app.domains.task.models.task import SddTask
from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.asset.models.asset import SddAsset
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
from app.engine.workflow_engine import shutdown_active_engines
from app.domains.api_mock.services import api_mock_service
from app.domains.auth.services import auth_service
from app.domains.system_config.routers import system_config
from app.domains.websocket.ws.manager import manager
from app.domains.websocket.ws.task_handler import TaskWebSocketHandler, TaskWebSocketUser
from app.domains.notification.routers import notification as notification_router
from app.domains.notification.ws.notification_manager import notification_ws_manager
from app.domains.task.services import pre_input_worker as pre_input_deadline_worker
from app.domains.task.services import task_cli_state_service
from app.domains.api_mock.ws.api_mock_manager import api_mock_ws_manager
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.rag.routers import outbox as rag_outbox_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="规范驱动开发基础平台 API"
)

_pre_input_worker_task: asyncio.Task | None = None
app.state.ai_runtime_ready = False

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
    app.state.ai_runtime_ready = False
    _pre_input_worker_task = asyncio.create_task(pre_input_deadline_worker.run_pre_input_worker())
    recovered_queue_count = await ai_job_service.start_runtime_workers()
    app.state.ai_runtime_ready = True
    if recovered_queue_count:
        logger.info("Recovered {} pending AI job queues", recovered_queue_count)


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _pre_input_worker_task
    app.state.ai_runtime_ready = False
    if _pre_input_worker_task is not None:
        _pre_input_worker_task.cancel()
        await asyncio.gather(_pre_input_worker_task, return_exceptions=True)
        _pre_input_worker_task = None
    # Stop new durable claims and queue runners first.  The service then
    # terminates every locally supervised process before infrastructure closes.
    try:
        await ai_job_service.shutdown_runtime_workers()
    except Exception:
        logger.exception("Failed to shutdown AI job runtime")
    try:
        await shutdown_active_engines()
    except Exception:
        logger.exception("Failed to shutdown active workflow engines")
    try:
        await api_mock_ws_manager.shutdown()
    except Exception:
        logger.warning("Failed to shutdown API MOCK redis listener")
    for ws_manager, label in (
        (manager, "task"),
        (notification_ws_manager, "notification"),
        (asset_discussion_ws_manager, "asset discussion"),
    ):
        try:
            await ws_manager.shutdown()
        except Exception:
            logger.warning("Failed to shutdown %s websocket hubs", label)
    try:
        await close_redis_client()
    except Exception:
        logger.warning("Failed to close redis client on shutdown")
    try:
        # 在线程中执行有限等待的 executor 关闭，避免阻塞事件循环
        await asyncio.get_running_loop().run_in_executor(
            None, shutdown_offload_executors, True
        )
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
    """连接即鉴权（每连接一次）：JWT 解码留事件循环，单条 join 查询经 DB executor。"""
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
        # 单条 join：user × task × workspace_member 一次往返完成三项校验
        db = SessionLocal()
        try:
            row = (
                db.query(
                    User.id,
                    User.display_name,
                    User.avatar_url,
                    User.avatar_svg,
                    SddTask.workspace_id,
                    WorkspaceMember.is_expert,
                )
                .filter(
                    User.id == user_id,
                    SddTask.id == task_id,
                    WorkspaceMember.workspace_id == SddTask.workspace_id,
                    WorkspaceMember.user_id == User.id,
                )
                .first()
            )
            if not row:
                return None
            return {
                "user_id": row[0],
                "display_name": row[1],
                "avatar_url": row[2],
                "avatar_svg": row[3],
                "workspace_id": row[4],
                "is_workspace_expert": bool(row[5]),
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


async def _authenticate_resource_ws(
    websocket: WebSocket,
    *,
    resource_kind: str,
    resource_id: str,
) -> dict | None:
    """Authenticate resource sockets before any manager can accept them.

    The token subject is authoritative.  The resource-to-workspace membership
    check is deliberately a single synchronous DB query executed off-loop.
    """
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
            resource_model = {
                "api_mock": SddApiMockProject,
                "asset": SddAsset,
            }.get(resource_kind)
            if resource_model is None:
                return None
            row = (
                db.query(User.id, User.display_name, WorkspaceMember.is_expert)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .join(resource_model, resource_model.workspace_id == WorkspaceMember.workspace_id)
                .filter(
                    User.id == user_id,
                    resource_model.id == resource_id,
                )
                .first()
            )
            if not row:
                return None
            return {
                "user_id": str(row[0]),
                "display_name": row[1],
                "is_workspace_expert": bool(row[2]),
            }
        finally:
            db.close()

    return await run_db(_load)


def _ws_resume_query(websocket: WebSocket) -> tuple[str | None, str | None, int | None]:
    """Read a tab-scoped cursor; never substitute user_id for client_id."""
    client_id = str(websocket.query_params.get("client_id") or "").strip() or None
    epoch = str(websocket.query_params.get("epoch") or "").strip() or None
    raw_sequence = websocket.query_params.get("last_sequence")
    if raw_sequence in (None, ""):
        last_sequence = None
    else:
        try:
            last_sequence = int(raw_sequence)
        except (TypeError, ValueError):
            last_sequence = -1
    return client_id, epoch, last_sequence


def _persist_api_mock_collab_event(
    project_id: str,
    user_id: str,
    event_enum,
    endpoint_id,
    normalized_payload: dict,
) -> None:
    """api-mock 协作事件落库（线程内执行，由 run_db 包装）。"""
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
    client_id, resume_epoch, last_sequence = _ws_resume_query(websocket)

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
            client_key=client_id,
            resume_epoch=resume_epoch,
            last_sequence=last_sequence,
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
    client_id, resume_epoch, last_sequence = _ws_resume_query(websocket)
    await notification_ws_manager.connect(
        websocket,
        user_id,
        client_id=client_id,
        epoch=resume_epoch,
        last_sequence=last_sequence,
    )
    try:
        while True:
            # 通道只下行；仅处理 resync_complete 控制帧。
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if data.get("type") == "resync_complete":
                payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
                try:
                    await notification_ws_manager.complete_resync(
                        websocket,
                        user_id,
                        epoch=str(payload.get("epoch") or ""),
                        barrier_sequence=int(payload.get("barrier_sequence")),
                    )
                except (TypeError, ValueError):
                    continue
    except WebSocketDisconnect:
        notification_ws_manager.disconnect(websocket, user_id)
    except Exception:
        logger.exception("Notification websocket endpoint failed")
        notification_ws_manager.disconnect(websocket, user_id)


@app.websocket("/ws/api-mock/{project_id}")
async def api_mock_websocket_endpoint(websocket: WebSocket, project_id: str):
    ws_context = await _authenticate_resource_ws(
        websocket,
        resource_kind="api_mock",
        resource_id=project_id,
    )
    if not ws_context:
        await websocket.close(code=1008, reason="Unauthorized API mock websocket")
        return
    user_id = str(ws_context["user_id"])
    client_id, resume_epoch, last_sequence = _ws_resume_query(websocket)
    with bind_log_context(project_id=project_id, user_id=user_id):
        await api_mock_ws_manager.connect(
            websocket,
            project_id,
            user_id,
            client_id=client_id,
            epoch=resume_epoch,
            last_sequence=last_sequence,
        )
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
                if data.get("type") == "resync_complete":
                    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
                    try:
                        await api_mock_ws_manager.complete_resync(
                            websocket,
                            project_id,
                            epoch=str(payload.get("epoch") or ""),
                            barrier_sequence=int(payload.get("barrier_sequence")),
                        )
                    except (TypeError, ValueError):
                        pass
                    continue
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
                    await run_db(
                        _persist_api_mock_collab_event,
                        project_id, user_id, event_enum, endpoint_id, normalized_payload,
                    )

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
    ws_context = await _authenticate_resource_ws(
        websocket,
        resource_kind="asset",
        resource_id=asset_id,
    )
    if not ws_context:
        await websocket.close(code=1008, reason="Unauthorized asset discussion websocket")
        return
    user_id = str(ws_context["user_id"])
    client_id, resume_epoch, last_sequence = _ws_resume_query(websocket)
    with bind_log_context(asset_id=asset_id, user_id=user_id):
        await asset_discussion_ws_manager.connect(
            websocket,
            asset_id,
            user_id,
            client_id=client_id,
            epoch=resume_epoch,
            last_sequence=last_sequence,
        )
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
                if data.get("type") == "resync_complete":
                    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
                    try:
                        await asset_discussion_ws_manager.complete_resync(
                            websocket,
                            asset_id,
                            epoch=str(payload.get("epoch") or ""),
                            barrier_sequence=int(payload.get("barrier_sequence")),
                        )
                    except (TypeError, ValueError):
                        pass
                    continue
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


@app.get("/health/ready")
def readiness_check():
    worker_health = ai_job_service.runtime_worker_health()
    containment = ai_job_service.process_containment_readiness()
    runtime_ready = bool(getattr(app.state, "ai_runtime_ready", False))
    ready = (
        runtime_ready
        and bool(worker_health.get("healthy", False))
        and bool(containment.get("ok", True))
    )
    status = "ready" if ready else ("degraded" if runtime_ready else "starting")
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": status,
            "ready": ready,
            "app": settings.APP_NAME,
            "workers": worker_health,
            "process_containment": containment,
        },
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
