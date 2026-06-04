"""
HTTP 请求日志中间件
"""

import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import bind_request_context, get_logger
from app.domains.auth.services import auth_service

access_logger = get_logger(__name__, category="access")


class LoggingMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def _extract_client_ip(request: Request) -> str:
        forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = str(request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip
        if request.client and request.client.host:
            return str(request.client.host)
        return "unknown"

    @staticmethod
    def _extract_user_id(request: Request) -> str | None:
        auth_header = str(request.headers.get("authorization") or "").strip()
        if not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header[7:].strip()
        if not token:
            return None
        try:
            payload = auth_service.decode_token(token, expected_type="access")
        except Exception:
            return None
        user_id = str(payload.get("sub") or "").strip()
        return user_id or None

    async def dispatch(self, request: Request, call_next):
        request_id = str(request.headers.get("x-request-id") or "").strip() or str(uuid.uuid4())
        request.state.request_id = request_id

        method = str(request.method or "").upper()
        path = request.url.path
        client_ip = self._extract_client_ip(request)
        user_id = self._extract_user_id(request)
        started = time.perf_counter()

        with bind_request_context(
            request_id=request_id,
            user_id=user_id,
            client_ip=client_ip,
            method=method,
            path=path,
        ):
            try:
                response = await call_next(request)
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                access_logger.bind(
                    status=response.status_code,
                    duration_ms=duration_ms,
                ).info("HTTP request completed")
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Process-Time"] = str(duration_ms)
                return response
            except Exception:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                access_logger.bind(
                    status=500,
                    duration_ms=duration_ms,
                ).exception("HTTP request failed")
                raise
