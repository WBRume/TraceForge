"""An isolated real TraceForge queue/engine process for live recovery acceptance."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import pkgutil
import sys
import time
from pathlib import Path

from tests.live_opencode.transport import LiveTransport, record


def configure(root: Path):
    # Credentials still come from backend/.env; infrastructure and data are isolated.
    os.environ["DISTRIBUTED_LOCK_BACKEND"] = "local"
    os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
    os.environ["LOG_DIR"] = str(root / "logs")
    os.environ["AI_SESSION_LOG_DIR"] = str(root / "ai-logs")
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="INFO", backtrace=False, diagnose=False)
    from app.config import settings

    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    settings.AGENT_MAX_RUNTIME_HOURS = config["hard_seconds"] / 3600
    settings.AGENT_IDLE_TIMEOUT_MINUTES = config["idle_seconds"] / 60
    settings.OPENCODE_RECONCILE_INTERVAL_SECONDS = 1
    settings.AI_JOB_HEARTBEAT_SECONDS = 1
    settings.AI_JOB_LEASE_SECONDS = 5
    from sqlalchemy import create_engine

    from app import database, domains

    database.engine = create_engine(
        "sqlite:///" + (root / "state.sqlite").as_posix(),
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    database.SessionLocal.configure(bind=database.engine)
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
    database.Base.metadata.create_all(database.engine)
    return config, database.SessionLocal


def seed(root, config, factory):
    from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
    from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
    from app.domains.task.models.task import SddTask, TaskStatus

    with factory() as db:
        if db.get(SddAiJob, config["job_id"]):
            return
        user = User(
            id=config["user_id"],
            email="live-recovery@example.invalid",
            hashed_password="unused",
            display_name="Live test",
        )
        workspace = Workspace(
            id=config["workspace_id"],
            name="Isolated OpenCode recovery test",
            owner_id=user.id,
            project_path=str(root / "work"),
            agent_backend="opencode",
        )
        task = SddTask(
            id=config["task_id"],
            workspace_id=workspace.id,
            creator_id=user.id,
            name=config["case"],
            status=TaskStatus.CODING,
            project_path=str(root / "work"),
            session_revision=0,
            session_generation=1,
            agent_backend="opencode",
        )
        db.add_all(
            [
                user,
                workspace,
                task,
                WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER),
            ]
        )
        db.add(
            SddAiJob(
                id=config["job_id"],
                task_id=task.id,
                workspace_id=workspace.id,
                creator_id=user.id,
                channel=AiJobChannel.TASK_CHAT,
                status=AiJobStatus.PENDING,
                queue_key=f"TASK_CHAT:{task.id}",
                prompt_text=config["prompt"],
                session_revision=0,
                session_generation=1,
                context_json={
                    "client_message_id": config["request_id"],
                    "agent_model": {"model": config["model"], "backend": "opencode"},
                },
            )
        )
        db.commit()


def snapshot(factory, job_id):
    from app.domains.ai.models.ai_job import SddAiJob
    from app.domains.task.models.chat import ChatMessage

    with factory() as db:
        job = db.get(SddAiJob, job_id)
        if not job:
            return None
        messages = db.query(ChatMessage).filter_by(task_id=job.task_id).all()
        return {
            "status": job.status.value,
            "job_id": job.id,
            "task_id": job.task_id,
            "session_id": job.session_id,
            "checkpoint": job.provider_execution_json,
            "run_token": job.run_token,
            "worker_boot_id": job.worker_boot_id,
            "attempt_count": job.attempt_count,
            "failure_code": job.failure_code,
            "error": job.error_message,
            "interrupt_reason": job.interrupt_reason,
            "result": job.result_json,
            "messages": [
                {
                    "id": m.id,
                    "role": str(getattr(m.role, "value", m.role)),
                    "content": m.content,
                    "metadata": m.metadata_json,
                }
                for m in messages
            ],
        }


async def run(root: Path):
    config, factory = configure(root)
    log = root / f"worker-{os.getpid()}.jsonl"
    import httpx

    from app.agents.adapters import register_all
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.registry import AGENT_BACKENDS

    register_all()

    class LiveAdapter(OpenCodeAdapter):
        async def _ensure_client(self):
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    auth=self._auth,
                    timeout=30,
                    trust_env=False,
                    transport=LiveTransport(root, log, mute_session_events=config.get("mute_sse", False)),
                )
            return self._client

    AGENT_BACKENDS["opencode"] = LiveAdapter
    from app.domains.ai.services.jobs import reaper
    from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, runtime
    from app.engine.session.registry import shutdown_active_engines

    seed(root, config, factory)
    record(log, "worker_started", pid=os.getpid(), worker_boot_id=WORKER_BOOT_ID)
    initial = snapshot(factory, config["job_id"])
    if initial["status"] == "PENDING":
        runtime.schedule_queue(f"TASK_CHAT:{config['task_id']}")
    deadline = time.monotonic() + config["hard_seconds"] + 90
    previous = None
    while time.monotonic() < deadline:
        await reaper.reap_stale_jobs()
        state = snapshot(factory, config["job_id"])
        compact = {
            key: state[key]
            for key in ("status", "session_id", "checkpoint", "run_token", "worker_boot_id", "attempt_count")
        }
        if compact != previous:
            record(log, "state", **compact)
            previous = compact
        if state["status"] in {"SUCCESS", "INTERRUPTED", "FAILED", "ORPHANED", "CANCELLED"}:
            (root / f"result-{os.getpid()}.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            record(log, "worker_finished", status=state["status"])
            for runner in list(runtime.queue_runners.values()):
                await asyncio.wait_for(asyncio.shield(runner), 20)
            await shutdown_active_engines()
            return
        await asyncio.sleep(0.2)
    raise TimeoutError("Isolated worker did not converge")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.root.resolve()))
