"""Real Git + job orchestration; opt into isolated MySQL/Redis with TF_LIVE_PROVISION=1."""

import asyncio
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.core import distributed_lock as locks
from app.core.redis_client import close_redis_client
from app.database import Base
from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import git_worktree_service as git
from app.domains.task.services.provisioning import resources
from app.domains.task.services.task_records.commands import delete_task
from app.domains.workflow.models.provision_job import ProvisionJobStatus, ProvisionJobType
from app.domains.workflow.services import provision_job_service as jobs
from app.domains.workspace.services.workspace_service import delete_workspace


def command(directory, *args):
    return subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, check=True, text=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def provision_engine(tmp_path_factory):
    root = tmp_path_factory.mktemp("parallel-provision")
    admin = None
    schema = "tf_provision_" + uuid4().hex[:16]
    if os.getenv("TF_LIVE_PROVISION") == "1":
        from dotenv import dotenv_values

        config = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
        url = URL.create(
            "mysql+pymysql",
            username=config.get("DB_USER", settings.DB_USER),
            password=config.get("DB_PASSWORD", settings.DB_PASSWORD),
            host=config.get("DB_HOST", settings.DB_HOST),
            port=int(config.get("DB_PORT", settings.DB_PORT)),
            query={"charset": "utf8mb4"},
        )
        admin = create_engine(url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4"))
        engine = create_engine(url.set(database=schema), pool_size=12)
    else:
        engine = create_engine(
            f"sqlite:///{root / 'db.sqlite3'}", connect_args={"check_same_thread": False, "timeout": 30}
        )
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        if admin:
            assert schema.startswith("tf_provision_") and len(schema) == 29
            with admin.connect() as connection:
                connection.execute(text(f"DROP DATABASE `{schema}`"))
            admin.dispose()


@pytest.fixture()
def scenario(provision_engine, tmp_path, monkeypatch):
    factory = sessionmaker(bind=provision_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(jobs, "SessionLocal", factory)
    monkeypatch.setattr(settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    monkeypatch.setattr(settings, "PROVISION_QUEUE_MAX_CONCURRENT", 2)
    if os.getenv("TF_LIVE_PROVISION") == "1":
        from dotenv import dotenv_values

        config = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
        for key in ("REDIS_URL", "REDIS_PASSWORD"):
            monkeypatch.setattr(settings, key, config.get(key, getattr(settings, key)))
        monkeypatch.setattr(settings, "DISTRIBUTED_LOCK_BACKEND", "redis")
        monkeypatch.setattr(settings, "DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK", False)
        monkeypatch.setattr(settings, "DISTRIBUTED_LOCK_KEY_PREFIX", "tf-provision-test-" + uuid4().hex)
        monkeypatch.setattr(locks, "_PROVIDER", None)
        # Each test owns an asyncio.run loop; reset the provider bootstrap lock
        # along with the provider rather than reuse a lock bound by contention.
        monkeypatch.setattr(locks, "_PROVIDER_LOCK", asyncio.Lock())
    source, base = tmp_path / "source", tmp_path / "base"
    upstream = os.getenv("TF_PROVISION_SOURCE")
    if upstream:
        command(tmp_path, "clone", "--no-hardlinks", upstream, str(source))
        command(source, "checkout", "-B", "main", "HEAD")
    else:
        source.mkdir()
        command(source, "init", "-b", "main")
    command(source, "config", "user.name", "Provision test")
    command(source, "config", "user.email", "test@example.com")
    command(source, "config", "core.autocrlf", "false")
    count = int(os.getenv("TF_PROVISION_FILES", "200"))
    if not upstream:
        for index in range(count):
            (source / f"file-{index}.txt").write_text(f"{index}:" + "content\n" * 128, encoding="utf-8")
        command(source, "add", ".")
        command(source, "commit", "-m", "baseline")
    command(tmp_path, "clone", str(source), str(base))
    with factory() as db:
        user = User(id=str(uuid4()), email=f"{uuid4().hex}@example.com", hashed_password="x", display_name="Test")
        workspace = Workspace(
            id=str(uuid4()), name="Concurrent", owner_id=user.id, project_path=str(base), git_repo_url=str(source)
        )
        db.add_all([user, workspace])
        db.commit()

    def create():
        with factory() as db:
            task = SddTask(
                id=str(uuid4()),
                workspace_id=workspace.id,
                creator_id=user.id,
                name="Parallel",
                project_path=str(tmp_path / "tasks" / uuid4().hex),
                git_repo_url=str(source),
                status=TaskStatus.PROVISIONING,
            )
            db.add(task)
            db.commit()
            job = jobs.create_job(
                db,
                job_type=ProvisionJobType.CREATE_TASK,
                creator_id=user.id,
                workspace_id=workspace.id,
                task_id=task.id,
            )
            return task, job

    def run(*coroutines):
        async def execute():
            try:
                return await asyncio.gather(*coroutines)
            finally:
                await close_redis_client()

        return asyncio.run(execute())

    yield factory, workspace, source, base, create, run
    if os.getenv("TF_LIVE_PROVISION") == "1":
        import redis

        prefix = settings.DISTRIBUTED_LOCK_KEY_PREFIX
        assert prefix.startswith("tf-provision-test-") and len(prefix) == 50
        client = redis.Redis.from_url(settings.REDIS_URL, password=settings.REDIS_PASSWORD or None)
        try:
            keys = list(client.scan_iter(match=prefix + ":*"))
            if keys:
                client.delete(*keys)
        finally:
            client.close()


def test_fixed_commits_checkout_and_snapshots_overlap(scenario, monkeypatch, tmp_path):
    factory, workspace, source, base, create, run = scenario
    first, job_a = create()
    second, job_b = create()
    original_sha = command(base, "rev-parse", "HEAD")
    checkout_barrier, snapshot_barrier = threading.Barrier(2, timeout=45), threading.Barrier(2, timeout=45)
    first_started = threading.Event()
    events = []
    real_checkout, real_snapshot = git.checkout_registered_worktree, resources._prepare_initial_workspace_checkpoint

    def checkout(**kwargs):
        events.append((kwargs["task_id"], "checkout_start", time.perf_counter()))
        if kwargs["task_id"] == first.id:
            (source / "remote-added.txt").write_text("new remote commit", encoding="utf-8")
            command(source, "add", ".")
            command(source, "commit", "-m", "advance remote while first checks out")
            first_started.set()
        checkout_barrier.wait()
        real_checkout(**kwargs)
        events.append((kwargs["task_id"], "checkout_end", time.perf_counter()))

    def snapshot(db, ws, task):
        events.append((task.id, "snapshot_start", time.perf_counter()))
        with factory() as probe:
            assert probe.get(SddTask, task.id).status == TaskStatus.PROVISIONING
            with pytest.raises(ValueError, match="准备"):
                delete_workspace(probe, ws.id)
            with pytest.raises(ValueError, match="准备"):
                delete_task(probe, task.id, ws.id)
        snapshot_barrier.wait()
        real_snapshot(db, ws, task)
        events.append((task.id, "snapshot_end", time.perf_counter()))

    monkeypatch.setattr(git, "checkout_registered_worktree", checkout)
    monkeypatch.setattr(resources, "_prepare_initial_workspace_checkpoint", snapshot)

    async def second_job():
        assert await asyncio.to_thread(first_started.wait, 45)
        await jobs.run_create_task_job(job_b.id)

    run(jobs.run_create_task_job(job_a.id), second_job())
    with factory() as db:
        for task, job in ((first, job_a), (second, job_b)):
            assert jobs.get_job(db, job.id).status == ProvisionJobStatus.SUCCESS
            actual = db.get(SddTask, task.id)
            assert actual.status == TaskStatus.PENDING
            assert Path(actual.task_meta_json["initial_workspace_checkpoint"]).exists()
            assert command(task.project_path, "status", "--porcelain") == ""
            assert (Path(task.project_path) / "file-0.txt").is_file()
        assert command(first.project_path, "rev-parse", "HEAD") == original_sha
        assert command(second.project_path, "rev-parse", "HEAD") == command(source, "rev-parse", "HEAD")
        assert not (Path(first.project_path) / "remote-added.txt").exists()
        assert (Path(second.project_path) / "remote-added.txt").exists()
    # Re-delivery must preserve edits rather than reset a ready worktree.
    marker = Path(first.project_path) / "file-0.txt"
    marker.write_text("user edit", encoding="utf-8")
    run(jobs.run_create_task_job(job_a.id), jobs.run_create_task_job(job_a.id))
    assert marker.read_text() == "user edit"
    report = {
        "database": provision_engine_name(factory),
        "files": int(os.getenv("TF_PROVISION_FILES", "200")),
        "events": events,
    }
    (tmp_path / "concurrency.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("CONCURRENCY_EVIDENCE", json.dumps(report))


def provision_engine_name(factory):
    return factory.kw["bind"].dialect.name


def test_workspace_deletion_rechecks_tasks_after_permission_snapshot(scenario):
    factory, workspace, source, base, create, run = scenario
    with factory() as stale_request:
        assert stale_request.query(SddTask.id).filter_by(workspace_id=workspace.id).all() == []
        task, job = create()
        with pytest.raises(ValueError, match="准备"):
            delete_workspace(stale_request, workspace.id)
    assert base.exists()
    with factory() as db:
        assert db.get(SddTask, task.id).status == TaskStatus.PROVISIONING


def test_cleanup_waits_past_repository_lock_timeout(scenario, monkeypatch):
    factory, workspace, source, base, create, run = scenario
    task, job = create()
    monkeypatch.setattr(settings, "DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS", 0.05)

    async def cleanup_while_busy():
        async with locks.lock_workspace_repo(workspace.id):
            await asyncio.to_thread(
                jobs._register_task_sync, workspace_id=workspace.id, task_id=task.id, job_id=job.id
            )
            cleanup = asyncio.create_task(
                jobs._rollback_task_resources(workspace_id=workspace.id, task_id=task.id, job_id=job.id)
            )
            await asyncio.sleep(0.25)
            assert not cleanup.done()
            assert Path(task.project_path, ".git").exists()
            with factory() as db:
                assert jobs.get_job(db, job.id).stage == "CANCELLING"
        await cleanup

    run(cleanup_while_busy())
    assert not Path(task.project_path).exists()
    with factory() as db:
        assert db.get(SddTask, task.id) is None


@pytest.mark.parametrize("outcome", ["cancel", "failure"])
def test_snapshot_failure_or_cancel_only_removes_its_own_task(scenario, monkeypatch, outcome):
    factory, workspace, source, base, create, run = scenario
    first, job_a = create()
    second, job_b = create()
    snapshot = resources._prepare_initial_workspace_checkpoint
    barrier = threading.Barrier(2, timeout=45)

    def checkpoint(db, ws, task):
        barrier.wait()
        snapshot(db, ws, task)
        if task.id == first.id:
            if outcome == "failure":
                raise OSError("Injected snapshot failure after real capture")
            with factory() as session:
                jobs.get_job(session, job_a.id).cancel_requested = True
                session.commit()

    monkeypatch.setattr(resources, "_prepare_initial_workspace_checkpoint", checkpoint)
    run(jobs.run_create_task_job(job_a.id), jobs.run_create_task_job(job_b.id))
    with factory() as db:
        assert db.get(SddTask, first.id) is None
        assert jobs.get_job(db, job_a.id).stage == ("CANCELLED" if outcome == "cancel" else "FAILED")
        assert jobs.get_job(db, job_b.id).status == ProvisionJobStatus.SUCCESS
        assert db.get(SddTask, second.id).status == TaskStatus.PENDING
    assert not Path(first.project_path).exists()
    assert (Path(second.project_path) / "file-0.txt").is_file()
    assert first.id not in command(base, "worktree", "list", "--porcelain")
    assert first.id not in command(base, "branch", "--list")


def test_duplicate_dispatch_materializes_once(scenario, monkeypatch):
    factory, workspace, source, base, create, run = scenario
    hook = base / ".git/hooks/post-checkout"
    hook.write_text('#!/bin/sh\nprintf "1\\n" >> "$(git rev-parse --git-common-dir)/checkout-hook-count"\n', encoding="utf-8")
    hook.chmod(0o755)
    task, job = create()
    checkouts = []
    original = git.checkout_registered_worktree

    def checkout(**kwargs):
        checkouts.append(kwargs["task_id"])
        return original(**kwargs)

    monkeypatch.setattr(git, "checkout_registered_worktree", checkout)
    run(jobs.run_create_task_job(job.id), jobs.run_create_task_job(job.id))
    assert checkouts == [task.id]
    assert (base / ".git/checkout-hook-count").read_text().splitlines() == ["1"]
    with factory() as db:
        assert jobs.get_job(db, job.id).status == ProvisionJobStatus.SUCCESS


def test_coroutine_cancellation_drains_checkout_before_removing_worktree(scenario, monkeypatch):
    factory, workspace, source, base, create, run = scenario
    task, job = create()
    entered, release = threading.Event(), threading.Event()
    checkout = git.checkout_registered_worktree

    def held_checkout(**kwargs):
        entered.set()
        assert release.wait(30)
        checkout(**kwargs)

    monkeypatch.setattr(git, "checkout_registered_worktree", held_checkout)

    async def cancel_during_checkout():
        worker = asyncio.create_task(jobs.run_create_task_job(job.id))
        try:
            assert await asyncio.to_thread(entered.wait, 30)
            worker.cancel()
            await asyncio.sleep(0.1)
            assert not worker.done()
            assert Path(task.project_path, ".git").exists()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await worker

    run(cancel_during_checkout())
    assert not Path(task.project_path).exists()
    with factory() as db:
        assert db.get(SddTask, task.id) is None
        assert jobs.get_job(db, job.id).stage == "CANCELLED"


@pytest.mark.skipif(os.getenv("TF_PROVISION_BENCHMARK") != "1", reason="opt-in real creation timing")
def test_creation_batch_timing(scenario):
    factory, workspace, source, base, create, run = scenario
    measurements = {
        "source": os.getenv("TF_PROVISION_SOURCE", "generated"),
        "commit": command(source, "rev-parse", "HEAD"),
        "tracked_files": len(command(source, "ls-files", "-z").split("\0")) - 1,
    }
    for mode in ("serial", "parallel"):
        batch = [create(), create()]
        started = time.perf_counter()
        if mode == "serial":
            for _, job in batch:
                run(jobs.run_create_task_job(job.id))
        else:
            run(*(jobs.run_create_task_job(job.id) for _, job in batch))
        measurements[mode] = round(time.perf_counter() - started, 3)
        with factory() as db:
            for task, job in batch:
                assert jobs.get_job(db, job.id).status == ProvisionJobStatus.SUCCESS
                assert db.get(SddTask, task.id).status == TaskStatus.PENDING
    print("CREATION_BATCH_TIMING", json.dumps(measurements))
