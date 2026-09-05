"""Task chat WebSocket connection lifecycle and inbound message handlers."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.agents.selection import resolve_task_backend
from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import get_logger
from app.core.offload import run_db
from app.domains.ai.schemas.websocket import WSChatPayload, WSMessage
from app.domains.ai.services import ai_job_service, chat_message_idempotency_service
from app.domains.ai.services.chat_message_idempotency_service import ChatMessageClaim
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import (
    pre_input_service,
    task_session_control_service,
    task_session_service,
)
from app.domains.websocket.ws.manager import ConnectionManager, manager
from app.engine.workflow_engine import WorkflowEngine, get_engine


task_logger = get_logger(__name__, category="task_execution")


@dataclass(frozen=True)
class TaskWebSocketUser:
    """Authenticated user fields needed by the task WebSocket protocol."""

    id: str
    display_name: str
    is_workspace_expert: bool
    avatar_url: str | None = None
    avatar_svg: str | None = None


@dataclass(frozen=True)
class _ChatMessageRequest:
    content: str
    client_message_id: str


class TaskWebSocketHandler:
    """Process one authenticated task WebSocket connection."""

    def __init__(
        self,
        websocket: WebSocket,
        task_id: str,
        user: TaskWebSocketUser,
        *,
        session_factory: Callable[[], Session],
        connection_manager: ConnectionManager = manager,
        engine_getter: Callable[[str], WorkflowEngine | None] | None = None,
        engine_factory: Callable[..., WorkflowEngine] | None = None,
    ) -> None:
        self._websocket = websocket
        self._task_id = task_id
        self._user = user
        self._session_factory = session_factory
        self._manager = connection_manager
        self._engine_getter = engine_getter or get_engine
        self._engine_factory = engine_factory or WorkflowEngine

    async def run(self) -> None:
        """Accept, serve, and always unregister the connection."""
        await self._manager.connect(self._websocket, self._task_id)
        try:
            while True:
                message = await self._websocket.receive_json()
                await self._dispatch(message)
        except WebSocketDisconnect:
            pass
        except Exception:
            task_logger.exception("Task websocket endpoint failed")
        finally:
            self._manager.disconnect(self._websocket, self._task_id)

    async def _dispatch(self, message: Any) -> None:
        if not isinstance(message, dict):
            task_logger.warning(
                f"Ignored non-object websocket message for task {self._task_id}"
            )
            return

        message_type = message.get("type")
        if message_type == "chat_message":
            await self._handle_chat_message(message)
        elif message_type == "hitl_response":
            await self._handle_hitl_response(message)
        elif isinstance(message_type, str) and message_type.startswith("pre_input_"):
            await self._handle_pre_input(message_type, self._payload(message))

    @staticmethod
    def _payload(message: dict[str, Any]) -> dict[str, Any]:
        payload = message.get("payload")
        return payload if isinstance(payload, dict) else {}

    def _parse_chat_message(self, message: dict[str, Any]) -> _ChatMessageRequest:
        payload = self._payload(message)
        content = str(payload.get("content") or "")
        client_message_id = str(
            payload.get("client_message_id")
            or message.get("client_message_id")
            or uuid.uuid4()
        ).strip()
        return _ChatMessageRequest(content=content, client_message_id=client_message_id)

    async def _handle_chat_message(self, message: dict[str, Any]) -> None:
        request = self._parse_chat_message(message)
        if not request.content.strip():
            return

        # Do not persist prompt text in logs; undo must be able to forget it.
        task_logger.info(
            f"User chat for task {self._task_id}: message_length={len(request.content)}"
        )
        task_status = await run_db(self._load_task_status_sync, self._task_id)
        if task_status is None:
            await self._send_chat_ack(request, status="failed", message="Task not found")
            return

        claim = await self._claim_chat_message(self._task_id, request)
        if claim is None:
            return
        if task_status == str(getattr(TaskStatus.INTERRUPTED, "value", TaskStatus.INTERRUPTED)):
            await self._resume_interrupted_task(request, claim)
            return
        created = await self._persist_chat_message(request, claim)

        if created is not None:
            await self._publish_chat_message(request, created)

    def _load_task_status_sync(self, task_id: str) -> str | None:
        """任务状态轻量查询（调用方需在事件循环外经 run_db 执行）。"""
        db = self._session_factory()
        try:
            status = db.query(SddTask.status).filter(SddTask.id == task_id).scalar()
            if status is None:
                return None
            return str(getattr(status, "value", status))
        finally:
            db.close()

    async def _claim_chat_message(
        self,
        task_id: str,
        request: _ChatMessageRequest,
    ) -> ChatMessageClaim | None:
        try:
            claim = await chat_message_idempotency_service.claim_message(
                task_id=task_id,
                user_id=self._user.id,
                client_message_id=request.client_message_id,
                content=request.content,
            )
        except chat_message_idempotency_service.ChatMessageIdempotencyUnavailable as exc:
            task_logger.warning(
                f"Chat idempotency unavailable for task {self._task_id}: {exc}"
            )
            await self._send_chat_ack(
                request,
                status="failed",
                message="Chat idempotency service is unavailable. Please retry.",
            )
            return None

        if claim.claimed:
            return claim

        existing = claim.existing or {}
        await self._send_chat_ack(
            request,
            status="duplicate" if claim.status == "done" else claim.status,
            chat_message_id=existing.get("chat_message_id"),
            ai_job_id=existing.get("ai_job_id"),
            created_at=existing.get("finished_at"),
            message=(
                "client_message_id was reused with different content"
                if claim.status == "conflict"
                else None
            ),
        )
        return None

    async def _persist_chat_message(
        self,
        request: _ChatMessageRequest,
        claim: ChatMessageClaim,
    ) -> task_session_service.CreatedChatTurn | None:
        try:
            async with lock_task(self._task_id):
                created = await task_session_service.create_task_chat_turn(
                    task_id=self._task_id,
                    actor_user_id=self._user.id,
                    content=request.content,
                    context_json={"client_message_id": request.client_message_id},
                    client_message_id=request.client_message_id,
                )
            await chat_message_idempotency_service.mark_message_done(
                claim,
                chat_message_id=created.message_id,
                ai_job_id=created.job_id,
            )
            return created
        except (
            task_session_service.TaskSessionUndoError,
            task_session_control_service.TaskSessionControlError,
            LockAcquireTimeout,
        ) as exc:
            await self._mark_chat_claim_failed(claim)
            await self._send_chat_ack(
                request,
                status="failed",
                message=(
                    "Task is busy; please retry."
                    if isinstance(exc, LockAcquireTimeout)
                    else str(exc)
                ),
            )
            return None
        except Exception:
            await self._mark_chat_claim_failed(claim)
            raise

    async def _resume_interrupted_task(
        self,
        request: _ChatMessageRequest,
        claim: ChatMessageClaim,
    ) -> None:
        async with lock_task(self._task_id):
            result = await task_session_control_service.resume_interrupted_task(
                task_id=self._task_id,
                actor_user_id=self._user.id,
                prompt=request.content,
                confirm_continue=False,
                client_message_id=request.client_message_id,
            )
        job = result.get("job") or {}
        context = job.get("context_json") or {}
        chat_message_id = str(context.get("chat_message_id") or "") or None
        job_id = str(job.get("id") or "") or None
        await chat_message_idempotency_service.mark_message_done(
            claim,
            chat_message_id=chat_message_id or "",
            ai_job_id=job_id,
        )
        await self._send_chat_ack(
            request,
            status="accepted",
            chat_message_id=chat_message_id,
            ai_job_id=job_id,
            session_turn_id=job.get("session_turn_id"),
            session_generation=job.get("session_generation"),
        )

    async def _mark_chat_claim_failed(self, claim: ChatMessageClaim) -> None:
        try:
            await chat_message_idempotency_service.mark_message_failed(claim)
        except Exception:
            task_logger.warning(
                f"Failed to clear chat idempotency claim for task {self._task_id}"
            )

    async def _publish_chat_message(
        self,
        request: _ChatMessageRequest,
        created: task_session_service.CreatedChatTurn,
    ) -> None:
        created_at = created.created_at.isoformat() if created.created_at else None
        try:
            await self._send_chat_ack(
                request,
                status="accepted",
                chat_message_id=created.message_id,
                ai_job_id=created.job_id,
                created_at=created_at,
                session_turn_id=created.session_turn_id,
                session_generation=created.session_generation,
            )
            await self._manager.send_message_to_room(
                self._task_id,
                WSMessage(
                    type="chat_message",
                    payload=WSChatPayload(
                        task_id=self._task_id,
                        role="user",
                        content=request.content,
                        message_type="text",
                        id=created.message_id,
                        client_message_id=request.client_message_id,
                        creator_id=self._user.id,
                        creator_display_name=self._user.display_name,
                        creator_is_workspace_expert=self._user.is_workspace_expert,
                        creator_avatar_url=self._user.avatar_url,
                        creator_avatar_svg=self._user.avatar_svg,
                        created_at=created_at,
                        session_turn_id=created.session_turn_id,
                        session_generation=created.session_generation,
                    ).model_dump(),
                ),
            )
        finally:
            # The turn is already durable. Client I/O must not leave its job
            # pending until the next process-level queue recovery.
            await ai_job_service.enqueue_task_chat_job(created.job_id)

    async def _send_chat_ack(
        self,
        request: _ChatMessageRequest,
        *,
        status: str,
        chat_message_id: str | None = None,
        ai_job_id: str | None = None,
        created_at: str | None = None,
        session_turn_id: str | None = None,
        session_generation: int | None = None,
        message: str | None = None,
    ) -> None:
        payload = {
            "task_id": self._task_id,
            "status": status,
            "client_message_id": request.client_message_id,
            "id": chat_message_id,
            "chat_message_id": chat_message_id,
            "ai_job_id": ai_job_id,
            "role": "user",
            "content": request.content,
            "message_type": "text",
            "creator_id": self._user.id,
            "creator_display_name": self._user.display_name,
            "creator_is_workspace_expert": self._user.is_workspace_expert,
            "created_at": created_at,
            "session_turn_id": session_turn_id,
            "session_generation": session_generation,
            "message": message,
        }
        await self._websocket.send_json({"type": "chat_message_ack", "payload": payload})

    async def _handle_hitl_response(self, message: dict[str, Any]) -> None:
        payload = self._payload(message)
        response = str(payload.get("response") or "")
        job_id = payload.get("job_id")
        if not response.strip():
            return

        task_logger.info(
            f"HITL response for task {self._task_id}: message_length={len(response)}"
        )
        try:
            resumed = await ai_job_service.resume_waiting_hitl_job(
                task_id=self._task_id,
                response=response.strip(),
                job_id=str(job_id) if job_id else None,
            )
        except ai_job_service.AiJobConflictError as exc:
            # 会话/总结互斥：总结进行中拒绝恢复会话（不能让 WS 连接断开）
            task_logger.warning(f"HITL response rejected for task {self._task_id}: {exc}")
            await self._websocket.send_json(
                {
                    "type": "hitl_rejected",
                    "payload": {"task_id": self._task_id, "message": str(exc)},
                }
            )
            return
        if resumed:
            return

        engine = self._engine_getter(self._task_id)
        if engine:
            asyncio.create_task(engine.send_message(response))
            return

        await self._rebuild_engine_for_hitl(response)

    async def _rebuild_engine_for_hitl(self, response: str) -> None:
        task_meta = await run_db(self._load_hitl_task_meta_sync)
        if not task_meta:
            task_logger.warning(
                f"No engine and task not found for HITL task {self._task_id}, "
                "response ignored"
            )
            return
        task_logger.warning(
            f"No engine for HITL task {self._task_id}, "
            "rebuilding engine from DB and running response"
        )
        recovered_engine = self._engine_factory(
            task_id=task_meta["id"],
            ws_id=task_meta["workspace_id"],
            user_id=self._user.id,
            backend_name=task_meta["agent_backend"],
        )
        asyncio.create_task(recovered_engine.run(response))

    def _load_hitl_task_meta_sync(self) -> dict | None:
        """HITL 重建所需的任务元数据（线程内执行：含 resolve_task_backend 的查询/提交）。"""
        db = self._session_factory()
        try:
            task = db.query(SddTask).filter(SddTask.id == self._task_id).first()
            if not task:
                return None
            return {
                "id": task.id,
                "workspace_id": task.workspace_id,
                "agent_backend": resolve_task_backend(db, task.id),
            }
        finally:
            db.close()

    async def _handle_pre_input(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            await self._dispatch_pre_input_action(action, payload)
        except pre_input_service.PreInputError as exc:
            await self._send_pre_input_error(action, exc.message)
        except Exception:
            task_logger.exception(
                f"Failed to process {action} for task {self._task_id}"
            )
            await self._send_pre_input_error(action, "Failed to process pre input")

    async def _dispatch_pre_input_action(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        if action == "pre_input_create":
            await pre_input_service.create_pre_input(
                task_id=self._task_id,
                creator_id=self._user.id,
                main_text=str(payload.get("main_text") or ""),
                mentioned_user_ids=payload.get("mentioned_user_ids") or [],
                edit_permission=str(payload.get("edit_permission") or "NONE"),
                wait_seconds=int(payload.get("wait_seconds") or 180),
            )
            return

        known_actions = {
            "pre_input_edit_document",
            "pre_input_replace_span",
            "pre_input_mark_done",
            "pre_input_submit",
            "pre_input_cancel",
        }
        if action not in known_actions:
            raise pre_input_service.PreInputError("Unknown pre input action")

        pre_input_brief = await pre_input_service.get_active_pre_input_brief(self._task_id)
        if not pre_input_brief:
            raise pre_input_service.PreInputError("No collecting pre input")
        pre_input_id = pre_input_brief["id"]

        if action == "pre_input_edit_document":
            await pre_input_service.edit_pre_input_document(
                pre_input_id=pre_input_id,
                task_id=self._task_id,
                user_id=self._user.id,
                is_expert=self._user.is_workspace_expert,
                new_text=str(payload.get("text") or ""),
            )
        elif action == "pre_input_replace_span":
            await pre_input_service.replace_pre_input_span(
                pre_input_id=pre_input_id,
                task_id=self._task_id,
                user_id=self._user.id,
                is_expert=self._user.is_workspace_expert,
                start=int(payload.get("start") or 0),
                end=int(payload.get("end") or 0),
                anchor_text=str(payload.get("anchor_text") or ""),
                replacement=str(payload.get("replacement") or ""),
            )
        elif action == "pre_input_mark_done":
            await pre_input_service.mark_pre_input_done(
                pre_input_id=pre_input_id,
                task_id=self._task_id,
                user_id=self._user.id,
            )
        elif action == "pre_input_submit":
            if self._user.id != pre_input_brief["creator_id"]:
                raise pre_input_service.PreInputError("Only the creator can submit")
            await pre_input_service.submit_pre_input(
                pre_input_id=pre_input_id,
                actor_user_id=self._user.id,
                reason="manual",
            )
        elif action == "pre_input_cancel":
            await pre_input_service.cancel_pre_input(
                pre_input_id=pre_input_id,
                task_id=self._task_id,
                actor_user_id=self._user.id,
            )

    async def _send_pre_input_error(self, action: str, message: str) -> None:
        await self._websocket.send_json(
            {
                "type": "pre_input_error",
                "payload": {
                    "task_id": self._task_id,
                    "action": action,
                    "message": message,
                },
            }
        )
