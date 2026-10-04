"""Real MySQL fixtures and lifecycle controls for explicit HTTP acceptance only."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
from pathlib import Path
import pkgutil
import subprocess
import sys
import time
import uuid

import httpx
import psutil

from tests.live_opencode.verify_recovery import BACKEND, emit

BASE_URL = "http://127.0.0.1:8000"


def load_models():
    from app import domains
    for _, name, _ in pkgutil.iter_modules(domains.__path__):
        try:
            models = importlib.import_module(f"app.domains.{name}.models")
        except ModuleNotFoundError as exc:
            if exc.name != f"app.domains.{name}.models":
                raise
            continue
        if hasattr(models, "__path__"):
            for _, module, _ in pkgutil.walk_packages(models.__path__, prefix=models.__name__ + "."):
                importlib.import_module(module)


def baseline():
    from app.database import engine
    from sqlalchemy import text
    assert engine.dialect.name == "mysql", "This acceptance requires the configured MySQL"
    with engine.connect() as db:
        active = [dict(row) for row in db.execute(text(
            "SELECT id, status FROM sdd_ai_jobs WHERE status IN ('PENDING', 'RUNNING', 'WAITING_HITL', 'TERMINATING')"
        )).mappings()]
        assert not active, f"Other jobs are active; do not restart: {active}"
        orphaned = db.execute(text("SELECT id FROM sdd_ai_jobs WHERE status = 'ORPHANED'")).scalars().all()
        migration = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    return {"dialect": "mysql", "migration": migration, "preexisting_orphaned_ids": orphaned}


def seed_workspace(root):
    from app.database import SessionLocal
    from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
    from app.domains.auth.services.auth_service import hash_password
    password = uuid.uuid4().hex + "-Live"
    ids = {name: str(uuid.uuid4()) for name in ("workspace_id", "owner_id", "reader_id")}
    users = []
    with SessionLocal() as db:
        for role in ("owner", "reader"):
            user = User(id=ids[f"{role}_id"], email=f"live-http-{role}-{uuid.uuid4().hex[:10]}@example.invalid",
                        display_name=f"OpenCode HTTP acceptance {role}", hashed_password=hash_password(password))
            db.add(user)
            users.append({"email": user.email, "password": password})
        db.flush()
        db.add(Workspace(id=ids["workspace_id"], name=f"LiveHTTP-{root.name[-6:]}",
                         owner_id=ids["owner_id"], project_path=str(root / "workspace"), agent_backend="opencode"))
        db.flush()
        for role, membership in (("owner", WorkspaceRole.OWNER), ("reader", WorkspaceRole.VIEWER)):
            db.add(WorkspaceMember(workspace_id=ids["workspace_id"], user_id=ids[f"{role}_id"], role=membership))
        db.commit()
    (root / "fixture-ids.json").write_text(json.dumps(ids, indent=2), encoding="utf-8")
    return ids, users


def seed_task(config, ids, root):
    from app.database import SessionLocal
    from app.domains.task.models.task import SddTask, TaskStatus
    with SessionLocal() as db:
        db.add(SddTask(id=config["task_id"], workspace_id=ids["workspace_id"], creator_id=ids["owner_id"],
                       name=config["case"].replace("http_", ""), status=TaskStatus.CODING,
                       project_path=str(root / "work"), session_generation=1, session_revision=0,
                       agent_backend="opencode"))
        db.commit()


def read_state(task_id):
    from app.database import SessionLocal
    from app.domains.ai.models.ai_job import SddAiJob
    from app.domains.task.models.chat_submission import TaskChatSubmission
    from tests.live_opencode.worker import snapshot
    with SessionLocal() as db:
        job = db.query(SddAiJob).filter_by(task_id=task_id).one_or_none()
        receipt = db.query(TaskChatSubmission).filter_by(task_id=task_id).one_or_none()
        data = {"receipt_status": receipt.status if receipt else None,
                "receipt_id": receipt.id if receipt else None,
                "receipt_error": receipt.error_message if receipt else None}
        job_id = job.id if job else None
    if job_id:
        data.update(snapshot(SessionLocal, job_id))
    return data


async def until(check, *, seconds, label):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        last = await check()
        if last:
            return last
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Waiting for {label}; last={last}")


async def readiness():
    try:
        async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
            r = await client.get(BASE_URL + "/health/ready")
            return r.json() if r.status_code == 200 and r.json().get("ready") else None
    except httpx.HTTPError:
        return None


async def cleanup_fixture(root):
    """Use normal delete APIs for only the IDs/paths recorded by this harness."""
    from app.database import SessionLocal
    from app.domains.auth.models.user import User, Workspace
    from app.domains.auth.services.auth_service import create_access_token
    from app.domains.task.models.task import SddTask
    from app.domains.notification.models.task_awareness import TaskAwarenessEvent, TaskWebhookDelivery
    from sqlalchemy import delete
    ids = json.loads((root / "fixture-ids.json").read_text(encoding="utf-8"))
    expected_task_ids = [json.loads(path.read_text(encoding="utf-8"))["task_id"]
                         for path in root.glob("*/config.json")]
    with SessionLocal() as db:
        workspace = db.get(Workspace, ids["workspace_id"])
        tasks = db.query(SddTask).filter_by(workspace_id=ids["workspace_id"]).all()
        if workspace:
            assert workspace.owner_id == ids["owner_id"]
            assert Path(workspace.project_path).resolve() == (root / "workspace").resolve()
        for task in tasks:
            assert Path(task.project_path).resolve().is_relative_to(root.resolve())
        task_ids = [t.id for t in tasks]
        assert set(task_ids).issubset(expected_task_ids)
        for uid in (ids["owner_id"], ids["reader_id"]):
            user = db.get(User, uid)
            assert user is None or user.email.startswith("live-http-") and user.email.endswith("@example.invalid")
    headers = {"Authorization": "Bearer " + create_access_token(ids["owner_id"])}
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=45, trust_env=False) as client:
        for task_id in task_ids:
            prefix = f'/api/workspaces/{ids["workspace_id"]}/tasks/{task_id}'
            state = await asyncio.to_thread(read_state, task_id)
            if state.get("status") in {"PENDING", "RUNNING", "TERMINATING", "ORPHANED"}:
                response = await client.post(prefix + "/interrupt", json={"reason": "Live acceptance fixture cleanup"})
                response.raise_for_status()
            response = await client.delete(prefix)
            response.raise_for_status()
        if workspace:
            response = await client.delete(f'/api/workspaces/{ids["workspace_id"]}')
            response.raise_for_status()
    with SessionLocal() as db:
        event_ids = db.query(TaskAwarenessEvent.id).filter_by(workspace_id=ids["workspace_id"])
        deliveries = db.query(TaskWebhookDelivery).filter(TaskWebhookDelivery.event_id.in_(event_ids)).count()
        assert deliveries == 0, "This fixture must never generate an external webhook delivery"
        db.execute(delete(TaskAwarenessEvent).where(TaskAwarenessEvent.workspace_id == ids["workspace_id"]))
        db.execute(delete(User).where(User.id.in_([ids["owner_id"], ids["reader_id"]])))
        db.commit()
        assert not db.get(Workspace, ids["workspace_id"])
        assert not db.query(SddTask).filter_by(workspace_id=ids["workspace_id"]).count()
    (root / "cleanup.json").write_text(json.dumps({"workspace_deleted": True, "users_deleted": True,
                                                  "webhook_deliveries": deliveries,
                                                  "task_ids_deleted": expected_task_ids}, indent=2), encoding="utf-8")
    emit("http_fixtures_cleaned", workspace_id=ids["workspace_id"], tasks=len(task_ids))


class FullService:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.case_root = None
        self.original = None
        self.original_env = None

    def capture_original(self):
        listeners = {c.pid for c in psutil.net_connections(kind="tcp")
                     if c.status == "LISTEN" and c.laddr.port == 8000}
        assert len(listeners) == 1, f"Expected one current HTTP service, found {listeners}"
        process = psutil.Process(listeners.pop())
        command = process.cmdline()
        self.original_env = process.environ()
        assert any("main.py" in part or "uvicorn" in part for part in command), command
        self.original = {"pid": process.pid, "command": command, "cwd": process.cwd(),
                         "created_at": process.create_time()}
        (self.root / "original-service.json").write_text(json.dumps(self.original, indent=2), encoding="utf-8")

    async def stop_original(self):
        baseline()  # Recheck immediately before disturbing the listening process.
        process = psutil.Process(self.original["pid"])
        assert process.create_time() == self.original["created_at"]
        process.kill()
        await asyncio.to_thread(process.wait, 15)
        emit("original_http_stopped", pid=process.pid)

    async def start(self, case_root, hard_seconds):
        assert self.process is None or self.process.poll() is not None
        self.case_root = case_root
        self.process = self._spawn(
            [sys.executable, "-m", "tests.live_opencode.http_service", str(case_root),
             "--hard-seconds", str(hard_seconds)], BACKEND, case_root / f"service-{time.time_ns()}.log")
        await until(readiness, seconds=90, label="complete HTTP service ready")
        assert self.process.poll() is None, "A different service owns port 8000"
        emit("http_ready", pid=self.process.pid)

    def _spawn(self, command, cwd, log_path):
        with log_path.open("w", encoding="utf-8") as output:
            return subprocess.Popen(command, cwd=cwd, env=self.original_env,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    async def stop(self, *, graceful):
        if self.process is None or self.process.poll() is not None:
            return
        if graceful:
            (self.case_root / f"stop-{self.process.pid}").write_text("stop", encoding="utf-8")
        else:
            self.process.kill()
        await asyncio.to_thread(self.process.wait, 60)
        if graceful:
            assert self.process.returncode == 0, "Graceful HTTP shutdown failed"
        emit("http_stopped", pid=self.process.pid, graceful=graceful)

    async def restore(self):
        await self.stop(graceful=True)
        process = self._spawn(self.original["command"], self.original["cwd"], self.root / "restored-service.log")
        ready = await until(readiness, seconds=90, label="original HTTP service restored")
        assert process.poll() is None
        (self.root / "restored-service.json").write_text(json.dumps(
            {"pid": process.pid, "command": self.original["command"], "ready": ready}, indent=2), encoding="utf-8")
        emit("original_http_restored", pid=process.pid)
