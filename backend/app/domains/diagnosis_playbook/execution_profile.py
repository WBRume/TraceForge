"""Diagnosis's opt-in shared-engine profile and durable provider ownership."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import secrets
import time
import uuid
from app.agents.contract import AgentRunRequest, EXECUTION_KIND_LOCAL_PROCESS
from app.agents.runtime_control import ContextAnchor, ExecutionPolicy, SessionHandle
from app.core.offload import run_db_txn
from app.engine.session.execution_profile import ExecutionScope
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.websocket.ws.manager import manager
from app.domains.task.models.task import SddTask
from .models import PlaybookRun, PlaybookSpec
from .contracts import PlaybookError, digest
from . import service


class DiagnosisExecutionProfile:
    def __init__(self, *, run_id, task_id, environment, tool_url, backend_key, owner_id=None, hypothesis_id=None):
        self.run_id = run_id
        self.hypothesis_id = hypothesis_id
        parent_scope = "playbook:" + run_id
        self.scope = ExecutionScope(task_id, parent_scope + (":hypothesis:" + hypothesis_id if hypothesis_id else ""), parent_scope if hypothesis_id else "main")
        self.environment = environment
        self.tool_url = tool_url
        self.backend_key = backend_key
        self.owner_id = owner_id or str(uuid.uuid4())
        self.token = secrets.token_urlsafe(32)
        self.call_id = str(uuid.uuid4())
        self.control = None
        self.handle = None
        self.policy = None
        self.request = None
        self.run_epoch = None

    async def prepare_turn(self, engine, prompt):
        self.control = engine.cli.get_runtime_control()
        def load(db):
            run = db.get(PlaybookRun, self.run_id)
            spec = db.get(PlaybookSpec, run.spec_id)
            return service.snapshot(run), deepcopy(run.data_json), deepcopy(spec.spec_json["spec"])
        current, data, spec = await run_db_txn(load)
        self.run_epoch = current["run_epoch"]
        if current["state"] != "READY" or data["cancel_requested"]:
            raise PlaybookError("DISPATCH_REVOKED", status=409)
        stage = next(s for s in spec["stages"] if s["id"] == current["active_step"])
        env = {**self.environment, "allow_advisory": bool(data["advisory_ack"] and spec.get("environment", {}).get("allowAdvisory"))}
        capabilities = await self.control.negotiate(env)
        if isinstance(capabilities, dict):
            raise PlaybookError("RUNTIME_CONTROL_UNSUPPORTED", status=409,
                                missing_facts=capabilities.get("missing_facts", []))
        # MCP installation on WebHosts must be a run-dedicated host binding;
        # configuring a shared host would expose another task's tools/ticket.
        advisory = capabilities.readonly_enforcement == "ADVISORY_GUARD"
        if not advisory and engine.cli.name != "claude-code" and not env.get("dedicated_backend_host"):
            raise PlaybookError("DEDICATED_BACKEND_HOST_REQUIRED", status=409)
        stored_handle = data.get("provider_handles", {}).get(self.scope.scope_id)
        if stored_handle is None and not self.hypothesis_id:
            stored_handle = data.get("provider_handle")
        self.handle = SessionHandle(**stored_handle) if stored_handle else SessionHandle(str(uuid.uuid4()), engine.cli.name,
            capabilities.host_identity, None, "READY", 1, env.get("locator_ref", "run:" + self.run_id))
        anchor = ContextAnchor(str(uuid.uuid4()), self.run_id, current["run_epoch"], current["active_step"], self.scope.scope_id,
                               data["session_generation"], env["environment_digest"], env["source_snapshot_digest"],
                               digest(data["gate_decisions"]), None, tuple(h["id"] for h in data["hypotheses"] if h["state"] == "SUPPORTED"))
        self.handle = await self.control.resume_session(self.handle, anchor)
        source_dir = env["bindings"]["patch"] if stage["phase"] == "PATCH" else env["bindings"]["source"]
        previous_scope = data.get("scopes", {}).get(self.scope.scope_id, data.get("active_scope", {}))
        if stored_handle and previous_scope.get("project_path") != source_dir:
            # A resumed provider session can retain its original working tree.
            # Rehydrate at a new path unless native cwd rebinding is certified.
            self.handle = replace(self.handle, provider_session_id=None, state="READY",
                                  binding_revision=self.handle.binding_revision + 1)
        self.policy = ExecutionPolicy(stage["agentTier"], data["policy_epoch"], self.scope.scope_id, source_dir,
                                      capabilities.readonly_enforcement, self.call_id,
                                      {} if advisory else {"type": "http", "url": self.tool_url + "/" + self.run_id,
                                       "headers": {"Authorization": "Bearer " + self.token}})
        receipt = await self.control.apply_permission_tier(self.handle, self.policy, self.handle.binding_revision)
        def reserve(db):
            run = db.get(PlaybookRun, self.run_id)
            if run.state_version != current["state_version"] or run.state != "READY" or run.data_json["cancel_requested"]:
                raise PlaybookError("STATE_VERSION_CONFLICT", status=409)
            next_data = deepcopy(run.data_json)
            next_data["active_scope"] = {"scope_id": self.scope.scope_id, "call_id": self.call_id,
                "run_epoch": run.epoch, "step_id": run.active_step, "ticket_hash": "" if advisory else hashlib.sha256(self.token.encode()).hexdigest(),
                "expires_at": time.time() + 3600, "state": "DISPATCH_INTENT", "tool_calls": {},
                "owner_id": self.owner_id, "lease_until": time.time() + 120,
                "project_path": source_dir, "backend_key": self.backend_key,
                "hypothesis_id": self.hypothesis_id,
                "dispatch_at": time.time(),
                "handle": asdict(self.handle), "policy_receipt": asdict(receipt)}
            next_data["capabilities"] = asdict(capabilities)
            next_data["context_anchor"] = asdict(anchor)
            next_data["environment"] = env
            service.transition(db, run, next_data, state="AGENT_RUNNING", kind="playbook.agent_started")
            run.lease_owner, run.lease_until = self.owner_id, time.time() + 120
        await run_db_txn(reserve)
        context = {"anchor": asdict(anchor), "hypotheses": data["hypotheses"], "gates": data["gate_decisions"],
                   "physical_evidence": [{"step_id": e["step_id"], "execution_id": e["execution_id"],
                       "facts": e["facts"], "receipt_digest": e["receipt_digest"]} for e in data["evidence"][-4:]],
                   "repair_feedback": data.get("repair_feedback"),
                   "registered_discriminators": env.get("registered_discriminators", []),
                   "target_contract": env.get("target_contract"),
                   "branch_hypothesis": next((h for h in data["hypotheses"] if h["id"] == self.hypothesis_id), None),
                   "objective": stage["objective"], "phase": stage["phase"], "inputs": {k: v for k, v in data["inputs"].items() if spec.get("inputs", {}).get(k, {}).get("type") != "connection_ref"}}
        import json
        text = prompt + "\n诊断上下文（平台只读事实）：\n" + json.dumps(context, ensure_ascii=False)
        if self.hypothesis_id:
            text += "\n这是独立假说分支。只分析 branch_hypothesis 的可证伪条件与区分实验，不得修改兄弟假说。物理结果由随后独立 fixture 实验决定。"
        elif stage["phase"] == "HYPOTHESIZE":
            text += "\n必须调用 propose_hypotheses 工具提交 2 至 3 个可证伪假说，不能以聊天文本代替。"
            if env.get("registered_discriminators"):
                text += "\ndiscriminator_script 必须选择 registered_discriminators 中对应的已注册实验引用，每个假说选择不同实验。"
        text += "\n实验文件只能用 propose_experiment 提交候选，不得修改证据、oracle 或基线。所有通过结论由平台物理验证决定。"
        if advisory:
            from .advisory import prompt_contract
            # This replaces the MCP instructions, not the ordinary agent toolset.
            text = prompt + "\n诊断上下文：\n" + json.dumps(context, ensure_ascii=False)
            text += prompt_contract(stage["phase"], bool(self.hypothesis_id))
        options = {"execution_policy": asdict(self.policy)}
        if not advisory and engine.cli.name == "dsh":
            options["guard_control"] = env.get("guard_control")
        if not advisory and engine.cli.name == "opencode":
            options["dedicated_backend_host"] = bool(env.get("dedicated_backend_host"))
        if self.handle.state == "FORK_PENDING":
            options["fork_session"] = True
        self.request = AgentRunRequest(run_id=self.call_id, prompt=text, project_path=source_dir, session_id=self.handle.provider_session_id,
                                       permission_mode="read-only" if stage["agentTier"] == "READONLY" else "default",
                                       provider_options=options, timeout_seconds=1800,
                                       env={"TRACEFORGE_RUN_TOKEN": self.call_id, "WORKER_BOOT_ID": self.run_id},
                                       execution_kind=engine.cli.capabilities.execution_kind,
                                       metadata={"task_id": self.scope.task_id, "scope_id": self.scope.scope_id, "playbook_run_id": self.run_id},
                                       on_process_started=self.on_process_started)
        return self.request

    async def before_dispatch(self, request):
        def check(db):
            run = db.get(PlaybookRun, self.run_id)
            task = db.get(SddTask, run.task_id)
            scope = run.data_json.get("active_scope", {})
            if run.state != "AGENT_RUNNING" or run.data_json["cancel_requested"] or scope.get("call_id") != self.call_id or scope.get("run_epoch") != run.epoch or task.session_generation != run.data_json["session_generation"] or task.session_revision != run.data_json["session_revision"]:
                raise PlaybookError("DISPATCH_REVOKED", status=409)
            if run.lease_owner != self.owner_id or run.lease_until <= time.time():
                raise PlaybookError("PROVIDER_LEASE_EXPIRED", status=409)
        await run_db_txn(check)

    async def heartbeat(self):
        def renew(db):
            run = db.get(PlaybookRun, self.run_id)
            scope = run.data_json.get("active_scope", {})
            if run.state not in {"AGENT_RUNNING", "RECOVERING"}:
                return
            if run.lease_owner != self.owner_id or scope.get("call_id") != self.call_id:
                raise PlaybookError("PROVIDER_LEASE_LOST", status=409)
            # A heartbeat is internal bookkeeping, not a user-visible event.
            from sqlalchemy import update
            changed = db.execute(update(PlaybookRun).where(PlaybookRun.id == run.id,
                PlaybookRun.lease_owner == self.owner_id,
                PlaybookRun.state.in_(["AGENT_RUNNING", "RECOVERING"])).values(lease_until=time.time() + 120),
                execution_options={"synchronize_session": False})
            if changed.rowcount != 1:
                raise PlaybookError("STATE_VERSION_CONFLICT", status=409)
        await run_db_txn(renew)

    async def on_process_started(self, identity):
        await self.before_dispatch(self.request)
        def attach(db):
            run = db.get(PlaybookRun, self.run_id)
            data = deepcopy(run.data_json)
            data["active_scope"]["process_identity"] = {"pid": identity.pid, "started_at": identity.started_at.isoformat(),
                                                         "process_group_id": identity.process_group_id, "containment_id": identity.containment_id}
            service.transition(db, run, data)
        await run_db_txn(attach)
        return True

    async def on_event(self, event):
        # Events are observations, never evidence gates. No main chat persistence.
        if event.type == "session_started":
            provider_id = str(event.payload.get("provider_session_id") or "")
            if provider_id:
                if self.handle.state == "FORK_PENDING" and provider_id == self.handle.provider_session_id:
                    raise PlaybookError("FORK_CHILD_ID_PENDING", status=409)
                self.handle = replace(self.handle, provider_session_id=provider_id, state="READY")
                def save(db):
                    run = db.get(PlaybookRun, self.run_id)
                    data = deepcopy(run.data_json)
                    if data.get("active_scope", {}).get("call_id") != self.call_id:
                        raise PlaybookError("STALE_PROVIDER_SESSION", status=409)
                    data["active_scope"]["handle"] = asdict(self.handle)
                    data.setdefault("provider_handles", {})[self.scope.scope_id] = asdict(self.handle)
                    if not self.hypothesis_id:
                        data["provider_handle"] = asdict(self.handle)
                    service.transition(db, run, data)
                await run_db_txn(save)
        await manager.send_message_to_room(self.scope.task_id, WSMessage(type="playbook.agent_event", payload={
            "task_id": self.scope.task_id, "run_id": self.run_id, "scope_id": self.scope.scope_id,
            "call_id": self.call_id, "run_epoch": self.run_epoch, "provider_type": event.type, "payload": event.payload}))

    async def after_provider_settled(self, result):
        if result.session_id:
            self.handle = replace(self.handle, provider_session_id=result.session_id, state="READY")
        if self.request.execution_kind == EXECUTION_KIND_LOCAL_PROCESS:
            if result.termination_confirmed_dead is not True:
                raise PlaybookError("PROVIDER_TERMINATION_UNKNOWN", status=409)
            stop = {"confirmed": True, "call_id": self.call_id, "termination_confirmed_dead": True}
        else:
            stop = await self.control.await_quiescence(self.handle, self.call_id)
        def settle(db):
            run = db.get(PlaybookRun, self.run_id)
            if run.state == "CANCELLED":
                return
            if run.data_json.get("active_scope", {}).get("call_id") != self.call_id:
                raise PlaybookError("PROVIDER_SCOPE_CHANGED", status=409)
            task = db.get(SddTask, run.task_id)
            if (task.session_generation, task.session_revision) != (
                run.data_json["session_generation"], run.data_json["session_revision"]
            ) or run.data_json["active_scope"].get("run_epoch") != run.epoch:
                from .models import TaskPlaybookBinding
                data = deepcopy(run.data_json)
                data["cancel_requested"] = True
                data["missing_facts"] = ["TASK_SESSION_CHANGED"]
                data["active_scope"].update(state="SETTLED", ticket_hash="", stop_receipt=stop)
                db.get(TaskPlaybookBinding, run.task_id).active_run_id = None
                service.transition(db, run, data, state="CANCELLED")
                run.lease_until = 0
                return
            proposal_error = None
            if self.policy.enforcement == "ADVISORY_GUARD" and result.success and not run.data_json["cancel_requested"]:
                from .advisory import accept_result
                try:
                    with db.begin_nested():
                        accept_result(db, run, result.result_text or "")
                except PlaybookError as exc:
                    # Bulk CAS is outside ORM change tracking; refresh the
                    # identity map after the savepoint restores the SQL rows.
                    db.refresh(run)
                    proposal_error = str(exc)
            data = deepcopy(run.data_json)
            data["active_scope"].update(state="SETTLED", ticket_hash="", stop_receipt=stop,
                                        provider_success=result.success, provider_result=result.result_text)
            data.setdefault("provider_handles", {})[self.scope.scope_id] = asdict(self.handle)
            data.setdefault("scopes", {})[self.scope.scope_id] = deepcopy(data["active_scope"])
            if not self.hypothesis_id:
                data["provider_handle"] = asdict(self.handle)
            else:
                data.setdefault("branch_turns", {})[self.hypothesis_id] = {"run_epoch": run.epoch,
                    "state": "AGENT_REVIEWED" if result.success else "NEEDS_INPUT", "scope_id": self.scope.scope_id}
            if data["cancel_requested"]:
                from .models import TaskPlaybookBinding
                db.get(TaskPlaybookBinding, run.task_id).active_run_id = None
                state = "CANCELLED"
            elif result.success and not proposal_error and (run.phase != "HYPOTHESIZE" or len(data["hypotheses"]) >= 2):
                state = "READY"
            else:
                state = "NEEDS_INPUT"
                data["missing_facts"] = [proposal_error] if proposal_error else (["STRUCTURED_HYPOTHESES_REQUIRED"] if run.phase == "HYPOTHESIZE" else ["PROVIDER_TURN_FAILED"])
            service.transition(db, run, data, state=state, kind="playbook.agent_settled")
            run.lease_until = 0
        await run_db_txn(settle)

    async def on_error(self, error):
        def fail(db):
            run = db.get(PlaybookRun, self.run_id)
            if run.state != "AGENT_RUNNING" or run.data_json.get("active_scope", {}).get("call_id") != self.call_id:
                return
            data = deepcopy(run.data_json)
            data["active_scope"]["ticket_hash"] = ""
            data["active_scope"]["lease_until"] = 0
            run.lease_until = 0
            data["missing_facts"] = [type(error).__name__]
            service.transition(db, run, data, state="RECOVERING")
        await run_db_txn(fail)

    async def cancel(self, engine):
        def revoke(db):
            run = db.get(PlaybookRun, self.run_id)
            data = deepcopy(run.data_json)
            data["cancel_requested"] = True
            if data.get("active_scope"):
                data["active_scope"]["ticket_hash"] = ""
            service.transition(db, run, data, state="RECOVERING")
        await run_db_txn(revoke)
        stopped = await engine.cli.cancel()
        confirmed = stopped.local_process_confirmed_dead is True if stopped.execution_kind == EXECUTION_KIND_LOCAL_PROCESS else stopped.stop_acknowledged
        if confirmed:
            def finish(db):
                from .models import TaskPlaybookBinding
                run = db.get(PlaybookRun, self.run_id)
                data = deepcopy(run.data_json)
                data["active_scope"].update(state="SETTLED", stop_receipt=asdict(stopped))
                db.get(TaskPlaybookBinding, run.task_id).active_run_id = None
                service.transition(db, run, data, state="CANCELLED")
            await run_db_txn(finish)
        return stopped
