"""
Centralized logging setup and context propagation (Loguru).
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import sys
from typing import Any, Dict, Iterator, Optional

from loguru import logger as _loguru_logger

from app.config import settings

DEFAULT_CATEGORY = "application"
KNOWN_CONTEXT_KEYS = (
    "request_id",
    "user_id",
    "workspace_id",
    "task_id",
    "job_id",
    "session_id",
    "client_ip",
    "method",
    "path",
    "status",
    "duration_ms",
)

_LOG_CONTEXT: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "sdd_log_context",
    default=None,
)
_LOGGING_READY = False


def _coerce_category(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    return text or DEFAULT_CATEGORY


def _normalize_level_name(raw_level: str) -> str:
    level = str(raw_level or "INFO").strip().upper()
    if level in {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}:
        return level
    return "INFO"


def _current_context() -> Dict[str, Any]:
    value = _LOG_CONTEXT.get()
    if isinstance(value, dict):
        return dict(value)
    return {}


def _clean_fields(values: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        text_key = str(key).strip()
        if not text_key:
            continue
        cleaned[text_key] = value
    return cleaned


@contextlib.contextmanager
def bind_log_context(**values: Any) -> Iterator[None]:
    current = _current_context()
    merged = dict(current)
    merged.update(_clean_fields(values))
    token = _LOG_CONTEXT.set(merged)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def bind_request_context(
    *,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
) -> contextlib.AbstractContextManager[None]:
    return bind_log_context(
        request_id=request_id,
        user_id=user_id,
        workspace_id=workspace_id,
        task_id=task_id,
        client_ip=client_ip,
        method=method,
        path=path,
    )


def bind_task_context(
    *,
    task_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> contextlib.AbstractContextManager[None]:
    return bind_log_context(
        task_id=task_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )


def bind_ai_context(
    *,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    model: Optional[str] = None,
    round: Optional[int] = None,
    event_type: Optional[str] = None,
) -> contextlib.AbstractContextManager[None]:
    return bind_log_context(
        job_id=job_id,
        task_id=task_id,
        session_id=session_id,
        model=model,
        round=round,
        event_type=event_type,
    )


def bind_audit_context(
    *,
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> contextlib.AbstractContextManager[None]:
    return bind_log_context(
        user_id=user_id,
        workspace_id=workspace_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )


def _record_patcher(record: Dict[str, Any]) -> None:
    extra = record["extra"]
    context = _current_context()
    for key, value in context.items():
        extra.setdefault(key, value)
    extra["category"] = _coerce_category(extra.get("category"))
    extra.setdefault("logger_name", record.get("name") or "unknown")
    for key in KNOWN_CONTEXT_KEYS:
        extra.setdefault(key, "-")


def get_logger(name: Optional[str] = None, category: str = DEFAULT_CATEGORY):
    bound = _loguru_logger.bind(category=_coerce_category(category))
    if name:
        bound = bound.bind(logger_name=name)
    return bound


def _category_filter(expected: str):
    category = _coerce_category(expected)
    return lambda record: _coerce_category(record["extra"].get("category")) == category


def _error_filter(record: Dict[str, Any]) -> bool:
    return int(record["level"].no) >= logging.ERROR


def _debug_filter(record: Dict[str, Any]) -> bool:
    return record["level"].name == "DEBUG"


def _is_safe_extra_value(value: Any) -> bool:
    """仅放行可序列化的标量值，避免把 uvicorn websocket/app 等对象带进 loguru enqueue 队列。"""
    if value is None:
        return True
    if isinstance(value, (str, int, float, bool)):
        return True
    return False


class _InterceptHandler(logging.Handler):
    def __init__(self, *, category: Optional[str] = None):
        super().__init__()
        self._category = _coerce_category(category) if category else None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: Any = _loguru_logger.level(record.levelname).name
        except Exception:
            level = record.levelno

        std_keys = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
        }
        bound_payload = {
            "logger_name": record.name,
            "category": self._category or DEFAULT_CATEGORY,
        }
        for key, value in record.__dict__.items():
            if key in std_keys:
                continue
            if key.startswith("_"):
                continue
            if not _is_safe_extra_value(value):
                continue
            bound_payload[key] = value

        _loguru_logger.bind(**bound_payload).opt(
            depth=6,
            exception=record.exc_info,
        ).log(level, record.getMessage())


def _configure_stdlib_logging() -> None:
    logging.captureWarnings(True)
    root = logging.getLogger()
    root.handlers = [_InterceptHandler()]
    root.setLevel(logging.NOTSET)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.asgi", "fastapi"):
        std_logger = logging.getLogger(logger_name)
        std_logger.handlers = [_InterceptHandler()]
        std_logger.propagate = False
        std_logger.setLevel(logging.NOTSET)

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers = []
    uvicorn_access.propagate = False
    uvicorn_access.disabled = True


def _ensure_log_paths() -> Dict[str, str]:
    log_root = os.path.abspath(str(settings.LOG_DIR or "").strip() or "logs")
    paths = {
        "app": os.path.join(log_root, "app", "sdd_app.log"),
        "access": os.path.join(log_root, "access", "access.log"),
        "error": os.path.join(log_root, "error", "error.log"),
        "tasks": os.path.join(log_root, "tasks", "task_execution.log"),
        "ai_sessions": os.path.join(log_root, "ai_sessions", "ai_sessions.log"),
        "api_mock": os.path.join(log_root, "api_mock", "api_mock.log"),
        "audit": os.path.join(log_root, "audit", "audit.log"),
        "debug": os.path.join(log_root, "debug", "debug.log"),
    }
    for file_path in paths.values():
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
    return paths


def setup_logging(*, force: bool = False) -> None:
    global _LOGGING_READY
    if _LOGGING_READY and not force:
        return

    _loguru_logger.remove()
    _loguru_logger.configure(patcher=_record_patcher)
    _configure_stdlib_logging()

    paths = _ensure_log_paths()
    level_name = _normalize_level_name(settings.LOG_LEVEL)
    use_json = bool(settings.LOG_JSON_FILES)
    enqueue = bool(settings.LOG_ENQUEUE)
    enqueue_fallback_used = False

    def _safe_add_sink(*args: Any, **kwargs: Any) -> int:
        nonlocal enqueue_fallback_used
        try:
            return _loguru_logger.add(*args, **kwargs)
        except PermissionError:
            if not kwargs.get("enqueue"):
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs["enqueue"] = False
            enqueue_fallback_used = True
            return _loguru_logger.add(*args, **fallback_kwargs)
        except OSError:
            if not kwargs.get("enqueue"):
                raise
            fallback_kwargs = dict(kwargs)
            fallback_kwargs["enqueue"] = False
            enqueue_fallback_used = True
            return _loguru_logger.add(*args, **fallback_kwargs)

    _safe_add_sink(
        sys.stdout,
        level=level_name,
        enqueue=enqueue,
        colorize=True,
        backtrace=False,
        diagnose=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[category]}</cyan> | "
            "rid=<magenta>{extra[request_id]}</magenta> "
            "uid=<magenta>{extra[user_id]}</magenta> "
            "tid=<magenta>{extra[task_id]}</magenta> "
            "jid=<magenta>{extra[job_id]}</magenta> - "
            "<level>{message}</level>"
        ),
    )

    common_sink_kwargs = {
        "rotation": settings.LOG_ROTATION,
        "retention": settings.LOG_RETENTION,
        "serialize": use_json,
        "enqueue": enqueue,
        "backtrace": True,
        "diagnose": False,
    }

    _safe_add_sink(
        paths["app"],
        level=level_name,
        filter=_category_filter("application"),
        **common_sink_kwargs,
    )
    _safe_add_sink(
        paths["access"],
        level="INFO",
        filter=_category_filter("access"),
        **common_sink_kwargs,
    )
    _safe_add_sink(
        paths["tasks"],
        level=level_name,
        filter=_category_filter("task_execution"),
        **common_sink_kwargs,
    )
    _safe_add_sink(
        paths["ai_sessions"],
        level=level_name,
        filter=_category_filter("ai_session"),
        **common_sink_kwargs,
    )
    _safe_add_sink(
        paths["api_mock"],
        level=level_name,
        filter=_category_filter("api_mock"),
        **common_sink_kwargs,
    )
    _safe_add_sink(
        paths["audit"],
        level="INFO",
        filter=_category_filter("audit"),
        **common_sink_kwargs,
    )
    _safe_add_sink(
        paths["error"],
        level="ERROR",
        filter=_error_filter,
        **common_sink_kwargs,
    )
    if level_name == "DEBUG":
        _safe_add_sink(
            paths["debug"],
            level="DEBUG",
            filter=_debug_filter,
            **common_sink_kwargs,
        )

    settings.AI_SESSION_LOG_DIR = os.path.dirname(paths["ai_sessions"])
    _LOGGING_READY = True
    startup_logger = get_logger(__name__).bind(
        configured_level=level_name,
        log_dir=settings.LOG_DIR,
    )
    startup_logger.info("Structured logging initialized")
    if enqueue_fallback_used:
        startup_logger.warning("Logging enqueue fallback applied: switched to synchronous sinks")


def audit_log(
    action: str,
    outcome: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    **extra: Any,
) -> None:
    payload = {
        "action": str(action or "").strip(),
        "outcome": str(outcome or "").strip() or "unknown",
        "resource_type": str(resource_type or "").strip() or "unknown",
        "resource_id": str(resource_id).strip() if resource_id is not None else None,
    }
    payload.update(_clean_fields(extra))
    get_logger("audit", category="audit").bind(**payload).info("audit_event")
