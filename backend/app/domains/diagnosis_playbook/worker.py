"""Single-flight local dispatcher with durable intents and replayable outbox.

CAS permits multiple workers to inspect the queue; only the reservation winner
may execute. A VERIFYING run is reconciled by execution ID, never re-dispatched.
"""
import asyncio
from copy import deepcopy
from pathlib import Path
import logging
import time
import uuid
from app.core.offload import run_db_txn
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.websocket.ws.manager import manager
from app.domains.task.models.task import SddTask
from app.runtime.evidence_runner.supervisor import EvidenceRunner
from app.runtime.evidence_runner.registry import registry
from . import broker, service
from .contracts import ExecutionEnvelope, PlaybookError
from .models import PlaybookRun, PlaybookSpec
from .projector import project

logger = logging.getLogger(__name__)


class PlaybookWorker:
    def __init__(self, evidence_root):
        self.runner = EvidenceRunner(Path(evidence_root))
        self.owner_id = str(uuid.uuid4())

    @staticmethod
    async def publish(run_id):
        def read(db):
            run = db.get(PlaybookRun, run_id)
            return [deepcopy(e) for e in run.data_json.get("events", []) if e["event_seq"] > run.published_seq], service.snapshot(run)
        events, snapshot = await run_db_txn(read)
        for event in events:
            wire = {k: v for k, v in event.items() if k != "delivered"}
            wire["payload"] = {"snapshot": snapshot} if event["state_version"] == snapshot["state_version"] else {}
            await manager.send_message_to_room(event["task_id"], WSMessage(type=event["type"], payload=wire))
            def delivered(db):
                from sqlalchemy import update
                db.execute(update(PlaybookRun).where(PlaybookRun.id == run_id, PlaybookRun.published_seq < event["event_seq"]).values(published_seq=event["event_seq"]))
            await run_db_txn(delivered)

    async def tick(self, run_id):
        def load(db):
            run = db.get(PlaybookRun, run_id)
            spec = db.get(PlaybookSpec, run.spec_id)
            db.expunge(run)
            db.expunge(spec)
            return run, spec
        run, spec = await run_db_txn(load)
        scope = run.data_json.get("active_scope", {})
        if run.state == "AGENT_RUNNING" or (run.state == "RECOVERING" and scope.get("state") == "DISPATCH_INTENT"):
            await self.recover_provider(run)
            await self.publish(run_id)
            return
        if run.state == "PROJECTING":
            await run_db_txn(lambda db: project(db, db.get(PlaybookRun, run_id)))
            await self.publish(run_id)
            return
        if run.state not in {"READY", "VERIFYING", "RECOVERING"}:
            await self.publish(run_id)
            return
        try:
            bundle = registry.resolve(spec.spec_json["spec"]["execution"]["bundle"])
            if run.state == "READY":
                # Only a trusted probe receives execution-internal state.
                context = {**service.snapshot(run), "workspace_id": run.workspace_id, "internal": deepcopy(run.data_json)}
                environment = await asyncio.to_thread(bundle.probe, context, deepcopy(run.data_json["inputs"]))
                scope = run.data_json.get("active_scope", {})
                settled = scope.get("state") == "SETTLED" and scope.get("step_id") == run.active_step and scope.get("run_epoch") == run.epoch
                if not settled:
                    retry_branch = scope.get("hypothesis_id") if scope.get("step_id") == run.active_step and scope.get("run_epoch") == run.epoch else None
                    await self.run_agent(run, environment, retry_branch)
                    await self.publish(run_id)
                    return
                if run.phase == "HYPOTHESIZE":
                    turns = run.data_json.get("branch_turns", {})
                    pending_branch = next((h for h in run.data_json["hypotheses"] if h["state"] != "EXCLUDED" and
                        (turns.get(h["id"], {}).get("run_epoch") != run.epoch or turns[h["id"]].get("state") != "AGENT_REVIEWED")), None)
                    if pending_branch:
                        await self.run_agent(run, environment, pending_branch["id"])
                        await self.publish(run_id)
                        return
                envelope = broker.bind(run, spec, bundle, environment)
                def reserve(db):
                    current = db.get(PlaybookRun, run_id)
                    if current.state_version != run.state_version:
                        raise PlaybookError("STATE_VERSION_CONFLICT", status=409)
                    task = db.get(SddTask, run.task_id)
                    if (task.session_generation, task.session_revision) != (run.data_json["session_generation"], run.data_json["session_revision"]):
                        raise PlaybookError("TASK_SESSION_CHANGED", status=409)
                    broker.reserve(db, current, envelope, environment, self.owner_id)
                await run_db_txn(reserve)
            else:
                if run.lease_until > time.time():
                    await self.publish(run_id)
                    return
                attempt = run.data_json["attempts"][-1] if run.data_json["attempts"] else None
                if not attempt:
                    raise PlaybookError("EXECUTION_UNKNOWN", status=409)
                envelope = ExecutionEnvelope(**attempt["envelope"])
                try:
                    receipt = self.runner.inspect(envelope)
                except PlaybookError as exc:
                    if str(exc) != "EXECUTION_UNKNOWN":
                        raise
                    if not await self.claim_expired_lease(run):
                        return
                    receipt = await self.runner.reconcile(envelope, bundle)
                if receipt is None:
                    # DB intent may precede a lost spawn; absence isn't proof of no execution.
                    raise PlaybookError("EXECUTION_UNKNOWN", status=409)
                await run_db_txn(lambda db: service.accept_receipt(db, db.get(PlaybookRun, run_id), receipt))
                await self.publish(run_id)
                return
            async def emit(kind, payload):
                if kind == "runner.heartbeat":
                    def renew(db):
                        from sqlalchemy import update
                        changed = db.execute(update(PlaybookRun).where(PlaybookRun.id == run_id,
                            PlaybookRun.lease_owner == self.owner_id).values(lease_until=time.time() + 120))
                        if changed.rowcount != 1:
                            raise PlaybookError("RUNNER_LEASE_LOST", status=409)
                    await run_db_txn(renew)
                await manager.send_message_to_room(run.task_id, WSMessage(type=kind, payload={
                    "task_id": run.task_id, "run_id": run.id, "run_epoch": envelope.run_epoch,
                    "execution_id": envelope.execution_id, **payload}))
            async def cancelled():
                def check(db):
                    current = db.get(PlaybookRun, run_id)
                    task = db.get(SddTask, run.task_id)
                    return current.data_json["cancel_requested"] or current.epoch != envelope.run_epoch or task.session_revision != current.data_json["session_revision"] or task.session_generation != current.data_json["session_generation"]
                return await run_db_txn(check)
            await self.publish(run_id)
            receipt = await self.runner.execute(envelope, bundle, emit=emit, cancelled=cancelled)
            await run_db_txn(lambda db: service.accept_receipt(db, db.get(PlaybookRun, run_id), receipt))
        except PlaybookError as exc:
            if str(exc) == "STATE_VERSION_CONFLICT":
                return
            def fail(db):
                current = db.get(PlaybookRun, run_id)
                if current.state in service.TERMINAL:
                    return
                data = deepcopy(current.data_json)
                data["missing_facts"] = exc.detail["missing_facts"] or [str(exc)]
                data["pending"] = False
                state = "RECOVERING" if current.state in service.BUSY else "ENVIRONMENT_BLOCKED"
                if data.get("missing_facts") == current.data_json.get("missing_facts") and current.state == state:
                    return
                service.transition(db, current, data, state=state)
            await run_db_txn(fail)
        await self.publish(run_id)

    async def claim_expired_lease(self, run):
        def claim(db):
            from sqlalchemy import update
            changed = db.execute(update(PlaybookRun).where(PlaybookRun.id == run.id,
                PlaybookRun.state_version == run.state_version, PlaybookRun.lease_until <= time.time()).values(
                lease_owner=self.owner_id, lease_until=time.time() + 120), execution_options={"synchronize_session": False})
            return changed.rowcount == 1
        return await run_db_txn(claim)

    async def recover_provider(self, run):
        """Reclaim an expired owner; never treat an absent worker as a stop ACK."""
        from dataclasses import asdict
        from datetime import datetime, timezone
        from app.agents.supervision.supervisor import process_supervisor
        from .models import TaskPlaybookBinding
        scope = run.data_json.get("active_scope", {})
        if run.lease_until > time.time():
            return

        def claim(db):
            from sqlalchemy import update
            claimed = db.execute(update(PlaybookRun).where(PlaybookRun.id == run.id,
                PlaybookRun.state_version == run.state_version, PlaybookRun.lease_until <= time.time()).values(
                lease_owner=self.owner_id, lease_until=time.time() + 120), execution_options={"synchronize_session": False})
            if claimed.rowcount != 1:
                return False
            current = db.get(PlaybookRun, run.id)
            db.refresh(current)
            if current.state_version != run.state_version:
                return False
            data = deepcopy(current.data_json)
            data["active_scope"].update(owner_id=self.owner_id, lease_until=time.time() + 120, ticket_hash="")
            service.transition(db, current, data, state="RECOVERING")
            current.lease_owner, current.lease_until = self.owner_id, time.time() + 120
            return True
        if not await run_db_txn(claim):
            return
        confirmed, evidence = False, {}
        if scope.get("backend_key") == "claude-code":
            identity = scope.get("process_identity")
            if identity:
                stopped = await process_supervisor.stop_persisted(identity["pid"],
                    datetime.fromisoformat(identity["started_at"]), "playbook_owner_lost",
                    process_group_id=identity.get("process_group_id"), run_token=scope["call_id"],
                    not_before=datetime.fromtimestamp(scope["dispatch_at"], timezone.utc))
            else:
                stopped = await process_supervisor.stop_by_run_token_discovery(scope["call_id"],
                    "playbook_owner_lost", not_before=datetime.fromtimestamp(scope["dispatch_at"], timezone.utc))
            if stopped is not None:
                confirmed, evidence = stopped.confirmed_dead, asdict(stopped)
        else:
            from app.agents.selection import create_agent_backend_by_name
            handle = scope.get("handle", {})
            if handle.get("provider_session_id"):
                backend = create_agent_backend_by_name(scope["backend_key"])
                env = run.data_json.get("environment", {})
                if env.get("dedicated_backend_host") and env.get("backend_url"):
                    backend.server_url = env["backend_url"].rstrip("/")
                try:
                    stopped = await backend.cancel_persisted_session(handle["provider_session_id"])
                    confirmed, evidence = stopped.stop_acknowledged, asdict(stopped)
                finally:
                    client = getattr(backend, "_client", None)
                    if client is not None:
                        await client.aclose()

        def finish(db):
            current = db.get(PlaybookRun, run.id)
            data = deepcopy(current.data_json)
            active = data.get("active_scope", {})
            if active.get("owner_id") != self.owner_id or active.get("call_id") != scope.get("call_id"):
                return
            if confirmed:
                active.update(state="INTERRUPTED", stop_receipt=evidence, ticket_hash="")
                data["missing_facts"] = ["PROVIDER_TURN_INTERRUPTED"]
                state = "CANCELLED" if data["cancel_requested"] else "NEEDS_INPUT"
                if state == "CANCELLED":
                    db.get(TaskPlaybookBinding, current.task_id).active_run_id = None
            else:
                data["missing_facts"] = ["PROVIDER_TERMINATION_UNKNOWN"]
                state = "RECOVERING"
            service.transition(db, current, data, state=state)
        await run_db_txn(finish)

    async def run_agent(self, run, environment, hypothesis_id=None):
        from app.config import settings
        from app.engine.session.engine import TaskAgentEngine
        from .execution_profile import DiagnosisExecutionProfile
        from app.agents.errors import AgentError
        def resolve_backend(db):
            from app.agents.selection import resolve_workspace_backend
            task = db.get(SddTask, run.task_id)
            backend = task.agent_backend or resolve_workspace_backend(db, task.workspace_id)
            task.agent_backend = backend
            return backend
        backend_key = await run_db_txn(resolve_backend)
        profile = DiagnosisExecutionProfile(run_id=run.id, task_id=run.task_id, environment=environment,
                                            tool_url=settings.DIAGNOSIS_PLAYBOOK_TOOL_URL, backend_key=backend_key,
                                            owner_id=self.owner_id, hypothesis_id=hypothesis_id)
        engine = TaskAgentEngine(run.task_id, run.workspace_id, run.creator_id, backend_name=backend_key, execution_profile=profile)
        if environment.get("dedicated_backend_host") and environment.get("backend_url"):
            # Dedicated adapter instance only; never reconfigure a shared host.
            if hasattr(engine.cli, "server_url"):
                engine.cli.server_url = environment["backend_url"].rstrip("/")
        task = asyncio.create_task(engine.run("按照当前规程步骤开展问题定位，并提交必要的结构化候选。"))
        try:
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2)
                except TimeoutError:
                    await profile.heartbeat()
                    cancel = await run_db_txn(lambda db: db.get(PlaybookRun, run.id).data_json["cancel_requested"])
                    if cancel:
                        await engine.stop()
            await task
        except AgentError as exc:
            raise PlaybookError("RUNTIME_CONTROL_UNAVAILABLE", status=409, missing_facts=[str(exc)]) from exc
        finally:
            if not task.done():
                # Worker shutdown/loss is not the user's cancel command.
                # Reclaim the provider, preserve the run for fenced recovery.
                await engine.cli.cancel()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            client = getattr(engine.cli, "_client", None)
            if client is not None:
                await client.aclose()

    async def run(self):
        active = {}
        async def dispatch(run_id):
            try:
                await self.tick(run_id)
            except Exception:
                logger.exception("Playbook dispatch failed: %s", run_id)
                def mark_unknown(db):
                    run = db.get(PlaybookRun, run_id)
                    if run is None or run.state in service.TERMINAL:
                        return
                    data = deepcopy(run.data_json)
                    state = "RECOVERING" if run.state in service.BUSY else "ENVIRONMENT_BLOCKED"
                    if data.get("missing_facts") == ["DISPATCH_INFRASTRUCTURE_ERROR"] and run.state == state:
                        return
                    data["missing_facts"] = ["DISPATCH_INFRASTRUCTURE_ERROR"]
                    service.transition(db, run, data, state=state)
                try:
                    await run_db_txn(mark_unknown)
                    await self.publish(run_id)
                except Exception:
                    logger.exception("Unable to persist playbook dispatch failure: %s", run_id)
        try:
            while True:
                try:
                    from sqlalchemy import or_
                    active = {key: task for key, task in active.items() if not task.done()}
                    ids = await run_db_txn(lambda db: [r.id for r in db.query(PlaybookRun).filter(or_(PlaybookRun.state.in_(["READY", "AGENT_RUNNING", "VERIFYING", "RECOVERING", "PROJECTING"]), PlaybookRun.published_seq < PlaybookRun.event_seq)).order_by(PlaybookRun.updated_at).limit(100).all()])
                    for run_id in ids:
                        if run_id not in active and len(active) < 4:
                            active[run_id] = asyncio.create_task(dispatch(run_id))
                except Exception:
                    logger.exception("Playbook queue unavailable")
                await asyncio.sleep(2)
        finally:
            for task in active.values():
                task.cancel()
            await asyncio.gather(*active.values(), return_exceptions=True)
