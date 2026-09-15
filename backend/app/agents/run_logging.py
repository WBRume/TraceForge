"""统一 AgentBackend 底层调用的 AI 会话日志。

TraceForge 的统一执行入口（WorkflowEngine / LegacyBridgeShim）在调用
``backend.run()`` 时都经过这里，从而避免每个 adapter 单独重复写日志。
除了 loguru 的 ``ai_session`` 分类日志外，还会像 Claude 一样在
``AI_SESSION_LOG_DIR`` 下生成独立的会话 trace 文件（``时间戳_会话id.log``）。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Optional

from app.agents.contract import (
    AgentBackend,
    AgentEvent,
    AgentEventSink,
    AgentRunRequest,
    AgentRunResult,
)
from app.config import settings
from app.core.logging import bind_ai_context, bind_task_context, get_logger

logger = get_logger("agent.run", category="ai_session")

_TEXT_LIMIT = 2000
_PROMPT_LIMIT = 300
_RESULT_LIMIT = 500
_ERROR_LIMIT = 1000


def _safe_text(value: Any, limit: int = _TEXT_LIMIT) -> str:
    return str(value or "").strip()[:limit]


def _usage_payload(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    data = getattr(usage, "__dict__", None)
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k != "raw"}
    if isinstance(usage, dict):
        return {k: v for k, v in usage.items() if k != "raw"}
    return {"raw": str(usage)}


def _context_from_request(request: AgentRunRequest) -> dict[str, Optional[str]]:
    meta = request.metadata if isinstance(request.metadata, dict) else {}
    env = request.env if isinstance(request.env, dict) else {}
    return {
        "job_id": str(meta.get("ai_job_id") or env.get("AI_JOB_ID") or "").strip() or None,
        "task_id": str(meta.get("task_id") or env.get("TASK_ID") or "").strip() or None,
        "workspace_id": str(meta.get("workspace_id") or env.get("WORKSPACE_ID") or "").strip() or None,
        "user_id": str(meta.get("user_id") or env.get("USER_ID") or "").strip() or None,
    }


class _AgentSessionTrace:
    """为一次 AgentBackend.run() 生成独立的 ai_sessions trace 文件。"""

    def __init__(self, request: AgentRunRequest, backend_name: str) -> None:
        self._request = request
        self._backend_name = backend_name
        self._fp: Any = None
        self._path: Optional[str] = None
        self._started_at: Optional[datetime] = None
        self._pending_lines: list[str] = []

    @staticmethod
    def _sanitize_filename_part(value: str, fallback: str = "session") -> str:
        source = str(value or "").strip()
        cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in source)
        cleaned = cleaned.strip("-_.")
        return cleaned or fallback

    @property
    def path(self) -> Optional[str]:
        return self._path

    def _trace_dir(self) -> str:
        raw_dir = (settings.AI_SESSION_LOG_DIR or "").strip() or os.path.join(settings.LOG_DIR, "ai_sessions")
        trace_dir = os.path.abspath(raw_dir)
        os.makedirs(trace_dir, exist_ok=True)
        return trace_dir

    def _write(self, text: str = "") -> None:
        if self._fp is None:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        try:
            for line in str(text or "").splitlines() or [""]:
                self._fp.write(f"{timestamp} | {line}\n")
            self._fp.flush()
        except Exception:
            pass

    def open(self, session_id: Optional[str] = None) -> None:
        if self._fp is not None:
            return
        started_at = datetime.now()
        sid = str(session_id or self._request.session_id or "").strip()
        sid_part = self._sanitize_filename_part(sid, "new")
        backend_part = self._sanitize_filename_part(self._backend_name, "agent")
        # 会话 id 已带 agent 前缀（如 dsh-cli-...）时不再重复拼接；
        # 否则补上 agent 类型，避免出现 new.log 这类无法识别来源的文件名。
        backend_token = self._backend_name.lower().split("-", 1)[0]
        if sid_part != "new" and sid_part.lower().startswith(backend_token):
            name_core = f"{sid_part}.log"
        else:
            name_core = f"{backend_part}_{sid_part}.log"
        trace_name = f"{started_at:%Y%m%d_%H%M%S_%f}_{name_core}"
        trace_dir = self._trace_dir()
        trace_path = os.path.join(trace_dir, trace_name)
        try:
            fp = open(trace_path, "w", encoding="utf-8")
        except Exception:
            return
        self._fp = fp
        self._path = trace_path
        self._started_at = started_at

        self._write("=== AGENT SESSION TRACE ===")
        self._write(f"trace_file: {trace_path}")
        self._write(f"backend: {self._backend_name}")
        self._write(f"cwd: {os.path.abspath(self._request.project_path or os.getcwd())}")
        self._write(f"session_mode: {'resume' if self._request.session_id else 'new'}")
        self._write(f"session_id: {sid or '-'}")
        if self._request.model:
            self._write(f"model: {self._request.model}")
        if self._request.run_id:
            self._write(f"run_id: {self._request.run_id}")
        if self._request.permission_mode:
            self._write(f"permission_mode: {self._request.permission_mode}")
        self._write("----- USER PROMPT BEGIN -----")
        self._write(f"prompt_length: {len(str(self._request.prompt or ''))}")
        self._write("----- USER PROMPT END -----")

    def _flush_pending(self) -> None:
        if self._fp is None:
            return
        for line in self._pending_lines:
            self._write(line)
        self._pending_lines.clear()

    def event(self, event: AgentEvent) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if self._fp is None:
            sid: Optional[str] = None
            if event.type == "session_started":
                sid = str(
                    payload.get("provider_session_id") or self._request.session_id or ""
                ).strip() or None
            if event.type == "session_started" or self._request.session_id:
                self.open(sid)
            else:
                # 新会话尚未拿到真实 session id 前先缓存事件行，
                # 等 session_started 或最终结果再落盘，避免生成 new.log。
                self._pending_lines.append(f"[{event.type}] {_safe_text(str(payload), 500)}")
                return
            self._flush_pending()
        if self._fp is None:
            return

        line = f"[{event.type}]"
        if event.type == "session_started":
            sid = str(payload.get("provider_session_id") or self._request.session_id or "")
            line += f" provider_session_id={sid}"
            if payload.get("model"):
                line += f" model={payload.get('model')}"
        elif event.type in ("text", "text_delta"):
            text = _safe_text(payload.get("text"), 1000)
            if text:
                line += f" text_length={len(text)}"
        elif event.type == "thinking":
            text = _safe_text(payload.get("text"), 500)
            if text:
                line += f" text_length={len(text)}"
        elif event.type == "tool_use":
            line += f" tool={_safe_text(payload.get('tool_name') or payload.get('tool'), 200)}"
            tool_input = payload.get("tool_input")
            if tool_input is not None:
                line += f" input_present=true input_length={len(str(tool_input))}"
        elif event.type == "tool_result":
            line += (
                f" tool={_safe_text(payload.get('tool_name') or payload.get('tool'), 200)}"
                f" is_error={bool(payload.get('is_error'))}"
            )
        elif event.type == "usage":
            line += f" usage={_safe_text(_usage_payload(payload), 500)}"
        elif event.type == "ask_user":
            question = _safe_text(payload.get("question") or payload.get("prompt"), 300)
            line += f" question_present={bool(question)} question_length={len(question)}"
        elif event.type == "result":
            line += (
                f" success={bool(payload.get('success', True))}"
                f" finish_reason={_safe_text(payload.get('finish_reason'), 100)}"
            )
            result_text = _safe_text(payload.get("result"), 500)
            line += f" result_length={len(result_text)}"
        elif event.type == "error":
            error_text = _safe_text(payload.get("result") or payload.get("message"), 500)
            line += f" error_length={len(error_text)}"
        else:
            line += f" {_safe_text(str(payload), 500)}"
        self._write(line)

    def finish(self, result: AgentRunResult) -> None:
        if self._fp is None:
            self.open(result.session_id or self._request.session_id)
        if self._fp is None:
            return
        self._flush_pending()
        self._write(f"result_success: {result.success}")
        self._write(f"finish_reason: {_safe_text(result.finish_reason, 100)}")
        if result.duration_ms is not None:
            self._write(f"duration_ms: {result.duration_ms}")
        if result.cost_usd is not None:
            self._write(f"cost_usd: {result.cost_usd}")
        if result.usage is not None:
            self._write(f"usage: {_safe_text(_usage_payload(result.usage), 500)}")
        if result.result_text:
            self._write("----- RESULT TEXT BEGIN -----")
            self._write(result.result_text)
            self._write("----- RESULT TEXT END -----")
        self.close(reason="completed" if result.success else "failed", return_code=result.return_code)

    def finish_error(self, exc: BaseException) -> None:
        if self._fp is None:
            self.open(self._request.session_id)
        if self._fp is None:
            return
        self._flush_pending()
        self._write(f"error: {_safe_text(str(exc), _ERROR_LIMIT)}")
        self.close(reason="error")

    def close(self, *, reason: str, return_code: Optional[int] = None) -> None:
        if self._fp is None:
            return
        try:
            self._write(f"session_end_reason: {reason}")
            if return_code is not None:
                self._write(f"return_code: {return_code}")
            if self._started_at is not None:
                elapsed = (datetime.now() - self._started_at).total_seconds()
                self._write(f"elapsed_seconds: {elapsed:.3f}")
            self._write("=== END SESSION TRACE ===")
        finally:
            try:
                self._fp.close()
            except Exception:
                pass
            self._fp = None
            self._path = None
            self._started_at = None


async def run_agent_backend_with_logging(
    backend: AgentBackend,
    request: AgentRunRequest,
    on_event: AgentEventSink,
) -> AgentRunResult:
    """执行 AgentBackend.run()，并在底层统一打印 ai_session 日志与会话 trace 文件。

    日志覆盖：回合开始、会话启动、流式文本/工具/用量、最终结果与异常。
    """
    started_at = time.monotonic()
    ctx = _context_from_request(request)
    trace = _AgentSessionTrace(request, backend.name)
    with bind_task_context(
        task_id=ctx["task_id"],
        workspace_id=ctx["workspace_id"],
        user_id=ctx["user_id"],
    ), bind_ai_context(
        job_id=ctx["job_id"],
        task_id=ctx["task_id"],
        session_id=request.session_id,
        model=request.model,
        event_type="agent_run",
    ):
        base_extra = {
            "backend": backend.name,
            "run_id": request.run_id,
            "provider_session_id": request.session_id,
            "project_path": request.project_path,
            "permission_mode": request.permission_mode,
            "resumed": bool(request.session_id),
        }

        logger.bind(
            **base_extra,
            prompt_length=len(str(request.prompt or "")),
        ).info("agent run start")

        async def _logged_event(event: AgentEvent) -> None:
            payload = event.payload if isinstance(event.payload, dict) else {}
            extra = {
                "backend": backend.name,
                "provider": event.provider or backend.name,
                "agent_event": event.type,
                "event_type": event.type,
            }
            if event.type == "session_started":
                sid = str(payload.get("provider_session_id") or request.session_id or "")
                extra["provider_session_id"] = sid
                logger.bind(**extra).info("agent session started")
            elif event.type in ("text", "text_delta"):
                text = _safe_text(payload.get("text"))
                if text:
                    logger.bind(**extra, text_length=len(text)).debug("agent text")
            elif event.type == "thinking":
                text = _safe_text(payload.get("text"), 500)
                if text:
                    logger.bind(**extra, text_length=len(text)).debug("agent thinking")
            elif event.type == "tool_use":
                logger.bind(
                    **extra,
                    tool_name=_safe_text(payload.get("tool_name") or payload.get("tool") or "", 200),
                    tool_use_id=_safe_text(payload.get("tool_use_id") or "", 200),
                ).debug("agent tool use")
            elif event.type == "tool_result":
                logger.bind(
                    **extra,
                    tool_name=_safe_text(payload.get("tool_name") or payload.get("tool") or "", 200),
                    tool_use_id=_safe_text(payload.get("tool_use_id") or "", 200),
                    is_error=bool(payload.get("is_error")),
                ).debug("agent tool result")
            elif event.type == "usage":
                logger.bind(**extra, usage=_usage_payload(payload)).debug("agent usage")
            elif event.type == "ask_user":
                logger.bind(
                    **extra,
                    ask_user_id=_safe_text(payload.get("ask_user_id") or "", 200),
                    question_length=len(_safe_text(payload.get("question") or payload.get("prompt") or "", 300)),
                ).info("agent ask user")
            elif event.type == "result":
                logger.bind(
                    **extra,
                    success=bool(payload.get("success", True)),
                    finish_reason=_safe_text(payload.get("finish_reason") or "", 100),
                    result_length=len(_safe_text(payload.get("result"), _RESULT_LIMIT)),
                ).info("agent result")
            elif event.type == "error":
                logger.bind(
                    **extra,
                    error_length=len(_safe_text(payload.get("result") or payload.get("message"), _ERROR_LIMIT)),
                ).error("agent error")
            else:
                logger.bind(**extra).debug(f"agent event: {event.type}")

            trace.event(event)
            await on_event(event)

        try:
            result = await backend.run(request, _logged_event)
            result_extra = {
                "backend": backend.name,
                "run_id": request.run_id,
                "session_id": result.session_id or request.session_id or "",
                "finish_reason": result.finish_reason,
                "duration_ms": result.duration_ms if result.duration_ms is not None else int(
                    (time.monotonic() - started_at) * 1000
                ),
                "cost_usd": result.cost_usd,
                "usage": _usage_payload(result.usage),
                "result_length": len(_safe_text(result.result_text, _RESULT_LIMIT)),
            }
            if result.success:
                logger.bind(**result_extra).info("agent run success")
            else:
                logger.bind(**result_extra).warning("agent run failed")
            trace_path = trace.path
            trace.finish(result)
            if result.raw_trace is None and trace_path:
                result.raw_trace = trace_path
            return result
        except Exception as exc:
            logger.bind(
                backend=backend.name,
                run_id=request.run_id,
                provider_session_id=request.session_id,
                duration_ms=int((time.monotonic() - started_at) * 1000),
                error=_safe_text(str(exc), _ERROR_LIMIT),
            ).exception("agent run error")
            trace.finish_error(exc)
            raise
