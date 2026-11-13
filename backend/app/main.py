"""
FastAPI 主入口
包含 CORS 配置、路由挂载和 WebSocket 端点
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError

from app.config import settings
from app.core.logging import (
    bind_log_context,
    bind_task_context,
    get_logger,
    setup_logging,
)
from app.core.offload import run_db, shutdown_offload_executors
from app.core.redis_client import close_redis_client
from app.database import SessionLocal
from app.domains.ai.routers import agent, queue, speech
from app.domains.ai.services.jobs import workers as ai_job_workers
from app.domains.api_mock.models.api_mock import ApiMockCollabEventType, SddApiMockProject
from app.domains.api_mock.routers import api_mock
from app.domains.api_mock.services import api_mock_service
from app.domains.api_mock.ws.api_mock_manager import api_mock_ws_manager
from app.domains.asset.models.asset import SddAsset
from app.domains.asset.routers import assets as asset_assets
from app.domains.asset.routers import decision
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.auth.errors import OAuthAPIError, oauth_api_error_handler
from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.auth.routers import auth, oauth
from app.domains.auth.services import auth_service
from app.domains.case_center.routers import case as case_center_router
from app.domains.dashboard.routers import dashboard
from app.domains.diagnosis_playbook.router import (
    global_router as diagnosis_playbook_global_router,
)
from app.domains.diagnosis_playbook.router import (
    router as diagnosis_playbook_router,
)
from app.domains.diagnosis_playbook.tool_server import router as playbook_tool_router
from app.domains.local_resource.client import ResourceError
from app.domains.local_resource.router import router as local_resource_router
from app.domains.management.routers import (
    products_router,
    projects_router,
    repo_groups_router,
    repositories_router,
)
from app.domains.notification.routers import notification as notification_router
from app.domains.notification.routers.task_awareness import router as task_awareness_router
from app.domains.notification.ws.notification_manager import notification_ws_manager
from app.domains.rag.routers import outbox as rag_outbox_router
from app.domains.search import router as search_router
from app.domains.skill.routers import skill
from app.domains.system_config.routers import features as feature_configs
from app.domains.system_config.routers import system_config
from app.domains.task.models.task import SddTask
from app.domains.task.routers import public_session_shares, task, task_closeout
from app.domains.task.services import pre_input_worker as pre_input_deadline_worker
from app.domains.task.services.status_machine import StatusTransitionError
from app.domains.websocket.ws.connection import (
    ConnectionEvicted,
    receive_json_until_evicted,
    receive_text_until_evicted,
)
from app.domains.websocket.ws.manager import manager
from app.domains.websocket.ws.task_handler import TaskWebSocketHandler, TaskWebSocketUser
from app.domains.workflow.routers import provision
from app.domains.workspace.routers import invite_join, workspace
from app.domains.workspace_asset.routers import workspace_asset
from app.domains.workspace_collaboration.router import router as workspace_collaboration_router
from app.engine.session import shutdown_active_engines
from app.middleware.logging_middleware import LoggingMiddleware

setup_logging()
logger = get_logger(__name__)
api_mock_logger = get_logger(__name__, category="api_mock")


async def _shutdown_websocket_hubs():
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
        from app.domains.websocket.ws.public_share_manager import public_share_ws_manager

        await public_share_ws_manager.shutdown()
    except Exception:
        logger.warning("Failed to shutdown public share websocket hubs")


async def _shutdown(label: str, callback: Callable[..., Awaitable[None]], *args: Any) -> None:
    try:
        await callback(*args)
    except Exception:
        logger.exception("Failed to shut down {}", label)


async def _cancel_worker(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def _log_worker_exit(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        logger.opt(exception=task.exception()).error("Background worker exited unexpectedly: {}", task.get_name())


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.domains.notification.services import task_awareness_worker
    from app.domains.system_config.services.feature_runtime import FeatureRuntime
    from app.domains.task.services.task_records import deletion as task_deletion
    from app.runtime.evidence_runner.registry import load_configured_bundles

    app.state.runtime_started = False
    workers: dict[str, asyncio.Task[None]] = {}
    app.state.background_workers = workers
    # Stop producers before the services they submit work to or reconfigure.
    async with AsyncExitStack() as services, AsyncExitStack() as producers:
        services.push_async_callback(
            _shutdown, "offload executors", asyncio.to_thread, shutdown_offload_executors, True
        )
        services.push_async_callback(_shutdown, "Redis client", close_redis_client)
        services.push_async_callback(_shutdown_websocket_hubs)
        services.push_async_callback(_shutdown, "active workflow engines", shutdown_active_engines)
        producers.callback(workers.clear)

        def start_worker(name: str, run: Callable[[], Coroutine[Any, Any, None]]) -> None:
            task = asyncio.create_task(run(), name=name)
            producers.push_async_callback(_cancel_worker, task)
            workers[name] = task
            task.add_done_callback(_log_worker_exit)

        feature_runtime = FeatureRuntime(app)
        app.state.feature_runtime = feature_runtime
        producers.push_async_callback(_shutdown, "feature runtime", feature_runtime.close)
        await feature_runtime.initialize()
        load_configured_bundles(settings.DIAGNOSIS_PLAYBOOK_BUNDLE_FACTORIES)
        if settings.DIAGNOSIS_PLAYBOOK_MYSQL_ENVIRONMENTS_FILE:
            from app.runtime.evidence_runner.bundles.mysql_deadlock.bundle import install

            install(settings.DIAGNOSIS_PLAYBOOK_MYSQL_ENVIRONMENTS_FILE)
        # Search setup and AI recovery can acquire resources before returning.
        services.push_async_callback(_shutdown, "search runtime", search_router.stop, app)
        await search_router.start(app)
        try:
            await feature_runtime.refresh()
        except Exception as exc:
            logger.warning("Feature runtime initialization deferred: {}", type(exc).__name__)
        feature_runtime.start()

        start_worker("pre_input", pre_input_deadline_worker.run_pre_input_worker)
        services.push_async_callback(_shutdown, "AI job runtime", ai_job_workers.shutdown_runtime_workers)
        recovered_queue_count = await ai_job_workers.start_runtime_workers()
        if recovered_queue_count:
            logger.info("Recovered {} pending AI job queues", recovered_queue_count)
        start_worker("task_awareness", task_awareness_worker.run_worker)
        start_worker("task_deletion", task_deletion.run_worker)

        producers.callback(setattr, app.state, "runtime_started", False)
        app.state.runtime_started = True
        yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="规范驱动开发基础平台 API",
    lifespan=lifespan,
)

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

# ── OAuth 统一业务异常输出：{"detail": ..., "code": "OAUTH_XXX", **extra} ──
app.add_exception_handler(OAuthAPIError, oauth_api_error_handler)


@app.exception_handler(StatusTransitionError)
async def task_status_error_handler(_request, error):
    return JSONResponse(status_code=error.status_code, content={"code": error.code, "detail": str(error)})


# ── 路由挂载 ──
app.include_router(search_router.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(oauth.router, prefix="/api")
app.include_router(workspace.router, prefix="/api")
app.include_router(invite_join.router, prefix="/api")
app.include_router(task.router, prefix="/api")
app.include_router(workspace_collaboration_router, prefix="/api")
app.include_router(public_session_shares.router, prefix="/api")
# 公开分享 WS 通道：与 /ws/task 同级（vite / nginx 的 /ws 代理直接转发）
app.include_router(public_session_shares.ws_router)
app.include_router(task_closeout.router, prefix="/api")
app.include_router(diagnosis_playbook_router, prefix="/api")
app.include_router(diagnosis_playbook_global_router, prefix="/api")
app.include_router(playbook_tool_router, prefix="/api")
app.include_router(case_center_router.router, prefix="/api")
app.include_router(case_center_router.global_router, prefix="/api")
app.include_router(decision.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(asset_assets.router, prefix="/api")
app.include_router(skill.router, prefix="/api")
app.include_router(api_mock.router, prefix="/api")
app.include_router(provision.router, prefix="/api")
app.include_router(queue.router, prefix="/api")
app.include_router(workspace_asset.router, prefix="/api")
app.include_router(workspace_asset.global_router, prefix="/api")
app.include_router(notification_router.router, prefix="/api")

app.include_router(task_awareness_router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(speech.router, prefix="/api")
app.include_router(products_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(repositories_router, prefix="/api")
app.include_router(repo_groups_router, prefix="/api")
app.include_router(system_config.router, prefix="/api")
app.include_router(feature_configs.router, prefix="/api")
app.include_router(rag_outbox_router.router, prefix="/api")
app.include_router(api_mock.gateway_router)


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
    connection = await notification_ws_manager.connect(
        websocket,
        user_id,
        client_id=client_id,
        epoch=resume_epoch,
        last_sequence=last_sequence,
    )
    try:
        while True:
            # 通道只下行；仅处理 resync_complete 控制帧。
            raw = await receive_text_until_evicted(websocket, connection)
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
    except (WebSocketDisconnect, ConnectionEvicted):
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
        connection = await api_mock_ws_manager.connect(
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
                data = await receive_json_until_evicted(websocket, connection)
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
                        project_id,
                        user_id,
                        event_enum,
                        endpoint_id,
                        normalized_payload,
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
        except (WebSocketDisconnect, ConnectionEvicted):
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
        connection = await asset_discussion_ws_manager.connect(
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
                data = await receive_json_until_evicted(websocket, connection)
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
        except (WebSocketDisconnect, ConnectionEvicted):
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
async def readiness_check(request: Request):
    worker_health = ai_job_workers.runtime_worker_health()
    for name, worker in getattr(request.app.state, "background_workers", {}).items():
        alive = not worker.done()
        worker_health[name] = {"alive": alive, "healthy": alive}
        worker_health["healthy"] = worker_health["healthy"] and alive
    containment = ai_job_workers.process_containment_readiness()
    runtime_started = getattr(request.app.state, "runtime_started", False)
    ready = runtime_started and worker_health["healthy"] and containment["ok"]
    status = "ready" if ready else ("degraded" if runtime_started else "starting")
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


app.include_router(local_resource_router, prefix="/api")


@app.exception_handler(ResourceError)
async def local_resource_error_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": {"code": exc.code, "message": str(exc)}})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
