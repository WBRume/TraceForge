"""
HTTP 请求日志中间件
"""

import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = str(uuid.uuid4())
        logger.bind(req_id=req_id).info(f"Incoming: {request.method} {request.url.path}")
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            process_time = (time.time() - start_time) * 1000
            
            logger.bind(req_id=req_id, status=response.status_code).info(
                f"Completed {response.status_code} OK in {process_time:.2f}ms"
            )
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Process-Time"] = str(process_time)
            return response
            
        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            logger.bind(req_id=req_id).error(
                f"Completed 500 Internal Server Error in {process_time:.2f}ms - {str(e)}"
            )
            raise
