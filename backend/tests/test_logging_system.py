import asyncio
import json
import os
import sys
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.core.logging import (  # noqa: E402
    audit_log,
    bind_request_context,
    get_logger,
    setup_logging,
)
from app.middleware.logging_middleware import LoggingMiddleware  # noqa: E402


class LoggingSystemTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = {
            "LOG_DIR": settings.LOG_DIR,
            "AI_SESSION_LOG_DIR": settings.AI_SESSION_LOG_DIR,
            "LOG_LEVEL": settings.LOG_LEVEL,
            "LOG_JSON_FILES": settings.LOG_JSON_FILES,
            "LOG_ROTATION": settings.LOG_ROTATION,
            "LOG_RETENTION": settings.LOG_RETENTION,
            "LOG_ENQUEUE": settings.LOG_ENQUEUE,
        }
        self._tmp = tempfile.TemporaryDirectory()
        settings.LOG_DIR = os.path.join(self._tmp.name, "logs")
        settings.AI_SESSION_LOG_DIR = os.path.join(settings.LOG_DIR, "ai_sessions")
        settings.LOG_LEVEL = "DEBUG"
        settings.LOG_JSON_FILES = True
        settings.LOG_ROTATION = "5 MB"
        settings.LOG_RETENTION = "3 days"
        settings.LOG_ENQUEUE = False
        setup_logging(force=True)

    def tearDown(self) -> None:
        settings.LOG_DIR = self._orig["LOG_DIR"]
        settings.AI_SESSION_LOG_DIR = self._orig["AI_SESSION_LOG_DIR"]
        settings.LOG_LEVEL = self._orig["LOG_LEVEL"]
        settings.LOG_JSON_FILES = self._orig["LOG_JSON_FILES"]
        settings.LOG_ROTATION = self._orig["LOG_ROTATION"]
        settings.LOG_RETENTION = self._orig["LOG_RETENTION"]
        settings.LOG_ENQUEUE = self._orig["LOG_ENQUEUE"]
        setup_logging(force=True)
        self._tmp.cleanup()

    def _read_file(self, *parts: str) -> str:
        path = os.path.join(settings.LOG_DIR, *parts)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as file:
            return file.read()

    def _read_json_lines(self, *parts: str) -> list[dict]:
        path = os.path.join(settings.LOG_DIR, *parts)
        if not os.path.exists(path):
            return []
        rows: list[dict] = []
        with open(path, "r", encoding="utf-8") as file:
            for raw in file:
                line = raw.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows

    def test_setup_logging_routes_categories_and_error_stack(self):
        get_logger("tests.app").info("app_message")
        get_logger("tests.access", category="access").info("access_message")
        get_logger("tests.task", category="task_execution").info("task_message")
        get_logger("tests.ai", category="ai_session").info("ai_message")
        get_logger("tests.api_mock", category="api_mock").info("api_mock_message")
        get_logger("tests.app").debug("debug_message")
        audit_log(
            action="unit_test_audit",
            outcome="success",
            resource_type="test_resource",
            resource_id="res-1",
            user_id="u-1",
        )
        try:
            raise RuntimeError("stack_boom")
        except RuntimeError:
            get_logger("tests.app").exception("stack_trace_message")

        app_log = self._read_file("app", "sdd_app.log")
        access_log = self._read_file("access", "access.log")
        task_log = self._read_file("tasks", "task_execution.log")
        ai_log = self._read_file("ai_sessions", "ai_sessions.log")
        api_mock_log = self._read_file("api_mock", "api_mock.log")
        audit_text = self._read_file("audit", "audit.log")
        debug_text = self._read_file("debug", "debug.log")
        error_text = self._read_file("error", "error.log")

        self.assertIn("app_message", app_log)
        self.assertIn("access_message", access_log)
        self.assertIn("task_message", task_log)
        self.assertIn("ai_message", ai_log)
        self.assertIn("api_mock_message", api_mock_log)
        self.assertIn("unit_test_audit", audit_text)
        self.assertIn("debug_message", debug_text)
        self.assertIn("stack_trace_message", error_text)
        self.assertIn("Traceback", error_text)

    def test_contextvars_flow_into_async_child_task(self):
        async def _emit() -> None:
            with bind_request_context(
                request_id="req-ctx-1",
                user_id="user-ctx-1",
                method="GET",
                path="/ctx",
            ):
                async def _child() -> None:
                    get_logger("tests.context").info("child_ctx_message")

                await asyncio.create_task(_child())

        asyncio.run(_emit())
        app_rows = self._read_json_lines("app", "sdd_app.log")
        target = None
        for row in app_rows:
            record = row.get("record", {})
            if record.get("message") == "child_ctx_message":
                target = record
                break

        self.assertIsNotNone(target)
        extra = (target or {}).get("extra", {})
        self.assertEqual(extra.get("request_id"), "req-ctx-1")
        self.assertEqual(extra.get("user_id"), "user-ctx-1")
        self.assertEqual(extra.get("method"), "GET")
        self.assertEqual(extra.get("path"), "/ctx")

    def test_logging_middleware_emits_structured_access_log(self):
        app = FastAPI()
        app.add_middleware(LoggingMiddleware)

        @app.get("/ping")
        def _ping():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/ping")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))

        access_rows = self._read_json_lines("access", "access.log")
        target = None
        for row in access_rows:
            record = row.get("record", {})
            if record.get("message") == "HTTP request completed":
                extra = record.get("extra", {})
                if extra.get("path") == "/ping":
                    target = record
                    break

        self.assertIsNotNone(target)
        extra = (target or {}).get("extra", {})
        self.assertEqual(extra.get("method"), "GET")
        self.assertEqual(extra.get("path"), "/ping")
        self.assertEqual(extra.get("status"), 200)
        self.assertTrue(float(extra.get("duration_ms")) >= 0)
        self.assertTrue(str(extra.get("client_ip")))


if __name__ == "__main__":
    unittest.main()
