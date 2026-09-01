"""
FastAPI 主入口
包含 CORS 配置、路由挂载和 WebSocket 端点
"""

import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError

from app.config import settings
from app.core.redis_client import close_redis_client
from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import (
    bind_log_context,
    bind_task_context,
    get_logger,
    setup_logging,
)

setup_logging()
logger = get_logger(__name__)
task_logger = get_logger(__name__, category="task_execution")
api_mock_logger = get_logger(__name__, category="api_mock")

from app.database import SessionLocal
from app.domains.api_mock.models.api_mock import ApiMockCollabEventType
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.auth.models.user import User
from app.engine.workflow_engine import WorkflowEngine, get_engine
from app.agents.selection import resolve_task_backend
from app.middleware.logging_middleware import LoggingMiddleware
from app.domains.ai.routers import agent
from app.domains.auth.routers import auth
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
from app.domains.ai.schemas.websocket import WSChatPayload, WSMessage
from app.domains.ai.services import ai_job_service
from app.domains.api_mock.services import api_mock_service
from app.domains.auth.services import auth_service
from app.domains.ai.services import chat_message_idempotency_service
from app.domains.task.services import task_service
from app.domains.task.services import task_session_control_service
from app.domains.task.services import task_session_service
from app.domains.workspace.services import workspace_service
from app.domains.websocket.ws.manager import manager
from app.domains.notification.routers import notification as notification_router
from app.domains.notification.ws.notification_manager import notification_ws_manager
from app.domains.task.services import pre_input_service
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

# ── 路由挂载 ──
app.include_router(auth.router, prefix="/api")
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
app.include_router(rag_outbox_router.router, prefix="/api")
app.include_router(api_mock.gateway_router)

# ── 静态文件挂载 ──
# app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


def _serialize_chat_ack(
    *,
    task_id: str,
    status: str,
    client_message_id: str,
    content: str = "",
    chat_message_id: str | None = None,
    ai_job_id: str | None = None,
    user_id: str | None = None,
    display_name: str | None = None,
    is_workspace_expert: bool = False,
    created_at: str | None = None,
    session_turn_id: str | None = None,
    session_generation: int | None = None,
    message: str | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "status": status,
        "client_message_id": client_message_id,
        "id": chat_message_id,
        "chat_message_id": chat_message_id,
        "ai_job_id": ai_job_id,
        "role": "user",
        "content": content,
        "message_type": "text",
        "creator_id": user_id,
        "creator_display_name": display_name,
        "creator_is_workspace_expert": bool(is_workspace_expert),
        "created_at": created_at,
        "session_turn_id": session_turn_id,
        "session_generation": session_generation,
        "message": message,
    }


async def _send_chat_ack(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_json({"type": "chat_message_ack", "payload": payload})


def _authenticate_task_ws(websocket: WebSocket, task_id: str) -> dict | None:
    token = str(websocket.query_params.get("token") or "").strip()
    if not token:
        return None

    db = SessionLocal()
    try:
        try:
            payload = auth_service.decode_token(token, expected_type="access")
        except JWTError:
            return None

        user_id = str(payload.get("sub") or "").strip()
        if not user_id:
            return None

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


def _authenticate_user_ws(websocket: WebSocket) -> dict | None:
    """按用户维度认证（通知通道）：仅校验 JWT，不绑定工作区。"""
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
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        return {"user_id": user.id, "display_name": user.display_name}
    finally:
        db.close()


# ── WebSocket 端点 ──
@app.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    ws_context = _authenticate_task_ws(websocket, task_id)
    if not ws_context:
        await websocket.close(code=1008, reason="Unauthorized task websocket")
        return

    user_id = str(ws_context["user_id"])
    user_display_name = str(ws_context.get("display_name") or "")
    user_is_expert = bool(ws_context.get("is_workspace_expert"))
    user_avatar_url = ws_context.get("avatar_url") or None
    user_avatar_svg = ws_context.get("avatar_svg") or None

    with bind_task_context(
        task_id=task_id,
        workspace_id=str(ws_context.get("workspace_id") or ""),
        user_id=user_id,
    ):
        await manager.connect(websocket, task_id)
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "chat_message":
                    # 用户发送消息 → Redis 幂等门禁 → 保存并创建异步 AI 作业
                    payload = data.get("payload", {})
                    user_content = str(payload.get("content", "") or "")
                    client_message_id = str(
                        payload.get("client_message_id")
                        or data.get("client_message_id")
                        or uuid.uuid4()
                    ).strip()
                    if not user_content.strip():
                        continue

                    # Do not put prompt text in persisted/file logs; undo is
                    # required to forget sensitive user content.
                    task_logger.info(f"User chat for task {task_id}: message_length={len(user_content)}")

                    task_meta = None
                    job_id = None
                    saved_message = None
                    claim = None
                    db = SessionLocal()
                    try:
                        task_obj = db.query(SddTask).filter(SddTask.id == task_id).first()
                        if not task_obj:
                            await _send_chat_ack(
                                websocket,
                                _serialize_chat_ack(
                                    task_id=task_id,
                                    status="failed",
                                    client_message_id=client_message_id,
                                    content=user_content,
                                    user_id=user_id,
                                    display_name=user_display_name,
                                    is_workspace_expert=user_is_expert,
                                    message="Task not found",
                                ),
                            )
                            continue

                        task_meta = {
                            "id": task_obj.id,
                            "workspace_id": task_obj.workspace_id,
                        }

                        try:
                            claim = await chat_message_idempotency_service.claim_message(
                                task_id=task_obj.id,
                                user_id=user_id,
                                client_message_id=client_message_id,
                                content=user_content,
                            )
                        except chat_message_idempotency_service.ChatMessageIdempotencyUnavailable as exc:
                            task_logger.warning(f"Chat idempotency unavailable for task {task_id}: {exc}")
                            await _send_chat_ack(
                                websocket,
                                _serialize_chat_ack(
                                    task_id=task_id,
                                    status="failed",
                                    client_message_id=client_message_id,
                                    content=user_content,
                                    user_id=user_id,
                                    display_name=user_display_name,
                                    is_workspace_expert=user_is_expert,
                                    message="Chat idempotency service is unavailable. Please retry.",
                                ),
                            )
                            continue

                        if not claim.claimed:
                            existing = claim.existing or {}
                            duplicate_status = "duplicate" if claim.status == "done" else claim.status
                            await _send_chat_ack(
                                websocket,
                                _serialize_chat_ack(
                                    task_id=task_id,
                                    status=duplicate_status,
                                    client_message_id=client_message_id,
                                    content=user_content,
                                    chat_message_id=existing.get("chat_message_id"),
                                    ai_job_id=existing.get("ai_job_id"),
                                    user_id=user_id,
                                    display_name=user_display_name,
                                    is_workspace_expert=user_is_expert,
                                    created_at=existing.get("finished_at"),
                                    message=(
                                        "client_message_id was reused with different content"
                                        if claim.status == "conflict"
                                        else None
                                    ),
                                ),
                            )
                            continue

                        try:
                            if task_obj.status == TaskStatus.INTERRUPTED:
                                async with lock_task(task_id):
                                    resume_payload = await task_session_control_service.resume_interrupted_task(
                                        db,
                                        task=task_obj,
                                        actor_user_id=user_id,
                                        prompt=user_content,
                                        confirm_continue=False,
                                        client_message_id=client_message_id,
                                    )
                                resume_job = resume_payload.get("job") or {}
                                resume_context = resume_job.get("context_json") or {}
                                await chat_message_idempotency_service.mark_message_done(
                                    claim,
                                    chat_message_id=str(resume_context.get("chat_message_id") or ""),
                                    ai_job_id=str(resume_job.get("id") or "") or None,
                                )
                                await _send_chat_ack(
                                    websocket,
                                    _serialize_chat_ack(
                                        task_id=task_id,
                                        status="accepted",
                                        client_message_id=client_message_id,
                                        content=user_content,
                                        user_id=user_id,
                                        display_name=user_display_name,
                                        is_workspace_expert=user_is_expert,
                                        chat_message_id=str(resume_context.get("chat_message_id") or "") or None,
                                        ai_job_id=str(resume_job.get("id") or "") or None,
                                        session_turn_id=resume_job.get("session_turn_id"),
                                        session_generation=resume_job.get("session_generation"),
                                    ),
                                )
                                continue

                            async with lock_task(task_id):
                                _turn, saved_message, job, _checkpoint = await task_session_service.create_task_chat_turn(
                                    db,
                                    task=task_obj,
                                    actor_user_id=user_id,
                                    content=user_content,
                                    context_json={"client_message_id": client_message_id},
                                    client_message_id=client_message_id,
                                )
                            job_id = job.id
                            await chat_message_idempotency_service.mark_message_done(
                                claim,
                                chat_message_id=saved_message.id,
                                ai_job_id=job_id,
                            )
                        except (task_session_service.TaskSessionUndoError, LockAcquireTimeout) as exc:
                            if claim:
                                try:
                                    await chat_message_idempotency_service.mark_message_failed(claim)
                                except Exception:
                                    task_logger.warning(
                                        f"Failed to clear chat idempotency claim for task {task_id}"
                                    )
                            await _send_chat_ack(
                                websocket,
                                _serialize_chat_ack(
                                    task_id=task_id,
                                    status="failed",
                                    client_message_id=client_message_id,
                                    content=user_content,
                                    user_id=user_id,
                                    display_name=user_display_name,
                                    is_workspace_expert=user_is_expert,
                                    message=(
                                        "Task is busy; please retry."
                                        if isinstance(exc, LockAcquireTimeout)
                                        else str(exc)
                                    ),
                                ),
                            )
                            continue
                        except Exception:
                            if claim:
                                try:
                                    await chat_message_idempotency_service.mark_message_failed(claim)
                                except Exception:
                                    task_logger.warning(
                                        f"Failed to clear chat idempotency claim for task {task_id}"
                                    )
                            raise
                    finally:
                        db.close()

                    if not task_meta or not job_id or not saved_message:
                        task_logger.warning(f"Task {task_id} not found, message ignored")
                        continue
                    await _send_chat_ack(
                        websocket,
                        _serialize_chat_ack(
                            task_id=task_id,
                            status="accepted",
                            client_message_id=client_message_id,
                            content=user_content,
                            chat_message_id=saved_message.id,
                            ai_job_id=job_id,
                            user_id=user_id,
                            display_name=user_display_name,
                            is_workspace_expert=user_is_expert,
                            created_at=saved_message.created_at.isoformat(),
                            session_turn_id=saved_message.session_turn_id,
                            session_generation=saved_message.session_generation,
                        ),
                    )
                    await manager.send_message_to_room(
                        task_id,
                        WSMessage(
                            type="chat_message",
                            payload=WSChatPayload(
                                task_id=task_id,
                                role="user",
                                content=user_content,
                                message_type="text",
                                id=saved_message.id,
                                client_message_id=client_message_id,
                                creator_id=user_id,
                                creator_display_name=user_display_name,
                                creator_is_workspace_expert=user_is_expert,
                                creator_avatar_url=user_avatar_url,
                                creator_avatar_svg=user_avatar_svg,
                                created_at=saved_message.created_at.isoformat(),
                                session_turn_id=saved_message.session_turn_id,
                                session_generation=saved_message.session_generation,
                            ).model_dump(),
                        ),
                    )
                    await ai_job_service.enqueue_task_chat_job(job_id)

                elif msg_type == "hitl_response":
                    # HITL 回复 → 以用户回答恢复 CLI 会话
                    payload = data.get("payload", {})
                    response = payload.get("response", "")
                    job_id = payload.get("job_id")
                    if not response.strip():
                        continue

                    task_logger.info(f"HITL response for task {task_id}: message_length={len(response)}")
                    resumed = await ai_job_service.resume_waiting_hitl_job(
                        task_id=task_id,
                        response=response.strip(),
                        job_id=str(job_id) if job_id else None,
                    )
                    if resumed:
                        continue

                    engine = get_engine(task_id)
                    if engine:
                        asyncio.create_task(engine.send_message(response))
                    else:
                        task_meta = None
                        db = SessionLocal()
                        try:
                            task_obj = db.query(SddTask).filter(SddTask.id == task_id).first()
                            if task_obj:
                                task_meta = {
                                    "id": task_obj.id,
                                    "workspace_id": task_obj.workspace_id,
                                    "creator_id": user_id,
                                    "agent_backend": resolve_task_backend(db, task_obj.id),
                                }
                        finally:
                            db.close()
                        if not task_meta:
                            task_logger.warning(
                                f"No engine and task not found for HITL task {task_id}, response ignored"
                            )
                            continue
                        task_logger.warning(
                            f"No engine for HITL task {task_id}, rebuilding engine from DB and running response"
                        )
                        recovered_engine = WorkflowEngine(
                            task_id=task_meta["id"],
                            ws_id=task_meta["workspace_id"],
                            user_id=user_id,
                            backend_name=task_meta.get("agent_backend"),
                        )
                        asyncio.create_task(recovered_engine.run(response))

                elif msg_type and msg_type.startswith("pre_input_"):
                    # 协作预输入：发起 / 贡献 / 编辑 / 提交 / 取消，逻辑封装在 pre_input_service
                    payload = data.get("payload", {}) or {}
                    db = SessionLocal()
                    try:
                        task_obj = db.query(SddTask).filter(SddTask.id == task_id).first()
                        if not task_obj:
                            await websocket.send_json({
                                "type": "pre_input_error",
                                "payload": {"task_id": task_id, "message": "Task not found"},
                            })
                            continue

                        error_payload: dict | None = None
                        if msg_type == "pre_input_create":
                            try:
                                await pre_input_service.create_pre_input(
                                    db,
                                    task=task_obj,
                                    creator_id=user_id,
                                    main_text=str(payload.get("main_text") or ""),
                                    mentioned_user_ids=payload.get("mentioned_user_ids") or [],
                                    edit_permission=str(payload.get("edit_permission") or "NONE"),
                                    wait_seconds=int(payload.get("wait_seconds") or 180),
                                )
                            except pre_input_service.PreInputError as exc:
                                error_payload = {"action": msg_type, "message": exc.message}
                        elif msg_type == "pre_input_edit_document":
                            pre_input = pre_input_service.get_active_pre_input(db, task_id)
                            if not pre_input:
                                error_payload = {"action": msg_type, "message": "No collecting pre input"}
                            else:
                                try:
                                    await pre_input_service.edit_pre_input_document(
                                        db,
                                        pre_input=pre_input,
                                        user_id=user_id,
                                        is_expert=user_is_expert,
                                        new_text=str(payload.get("text") or ""),
                                    )
                                except pre_input_service.PreInputError as exc:
                                    error_payload = {"action": msg_type, "message": exc.message}
                        elif msg_type == "pre_input_replace_span":
                            pre_input = pre_input_service.get_active_pre_input(db, task_id)
                            if not pre_input:
                                error_payload = {"action": msg_type, "message": "No collecting pre input"}
                            else:
                                try:
                                    await pre_input_service.replace_pre_input_span(
                                        db,
                                        pre_input=pre_input,
                                        user_id=user_id,
                                        is_expert=user_is_expert,
                                        start=int(payload.get("start") or 0),
                                        end=int(payload.get("end") or 0),
                                        anchor_text=str(payload.get("anchor_text") or ""),
                                        replacement=str(payload.get("replacement") or ""),
                                    )
                                except pre_input_service.PreInputError as exc:
                                    error_payload = {"action": msg_type, "message": exc.message}
                        elif msg_type == "pre_input_mark_done":
                            pre_input = pre_input_service.get_active_pre_input(db, task_id)
                            if not pre_input:
                                error_payload = {"action": msg_type, "message": "No collecting pre input"}
                            else:
                                try:
                                    await pre_input_service.mark_pre_input_done(
                                        db,
                                        pre_input=pre_input,
                                        user_id=user_id,
                                    )
                                except pre_input_service.PreInputError as exc:
                                    error_payload = {"action": msg_type, "message": exc.message}
                        elif msg_type == "pre_input_submit":
                            pre_input = pre_input_service.get_active_pre_input(db, task_id)
                            if not pre_input:
                                error_payload = {"action": msg_type, "message": "No collecting pre input"}
                            elif user_id != pre_input.creator_id:
                                error_payload = {"action": msg_type, "message": "Only the creator can submit"}
                            else:
                                try:
                                    await pre_input_service.submit_pre_input(
                                        db,
                                        pre_input=pre_input,
                                        actor_user_id=user_id,
                                        reason="manual",
                                    )
                                except pre_input_service.PreInputError as exc:
                                    error_payload = {"action": msg_type, "message": exc.message}
                        elif msg_type == "pre_input_cancel":
                            pre_input = pre_input_service.get_active_pre_input(db, task_id)
                            if not pre_input:
                                error_payload = {"action": msg_type, "message": "No collecting pre input"}
                            else:
                                try:
                                    await pre_input_service.cancel_pre_input(
                                        db,
                                        pre_input=pre_input,
                                        actor_user_id=user_id,
                                    )
                                except pre_input_service.PreInputError as exc:
                                    error_payload = {"action": msg_type, "message": exc.message}
                        else:
                            error_payload = {"action": msg_type, "message": f"Unknown pre input action"}

                        if error_payload:
                            await websocket.send_json({
                                "type": "pre_input_error",
                                "payload": {"task_id": task_id, **error_payload},
                            })
                    finally:
                        db.close()

        except WebSocketDisconnect:
            manager.disconnect(websocket, task_id)
        except Exception:
            task_logger.exception("Task websocket endpoint failed")
            manager.disconnect(websocket, task_id)


@app.websocket("/ws/notifications")
async def notification_websocket_endpoint(websocket: WebSocket):
    """站内信实时通道：按用户维度推送，前端断线重连时以 REST 未读数兜底。"""
    context = _authenticate_user_ws(websocket)
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
