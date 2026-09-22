"""Optional control plane. Static adapter flags never certify enforcement."""
from dataclasses import dataclass, asdict, replace
import hashlib
import json
from pathlib import Path
import time
import uuid
from enum import Enum
from typing import Literal


class PermissionTier(str, Enum):
    READONLY = "READONLY"
    WORKSPACE_WRITE = "WORKSPACE_WRITE"


class EnforcementLevel(str, Enum):
    CONTAINER_SANDBOX = "CONTAINER_SANDBOX"
    WORKTREE_BROKER = "WORKTREE_BROKER"
    ADVISORY_GUARD = "ADVISORY_GUARD"


@dataclass(frozen=True)
class SessionHandle:
    logical_session_id: str
    backend_key: str
    host_identity: str
    provider_session_id: str | None
    state: Literal["READY", "FORK_PENDING", "LOST"]
    binding_revision: int
    opaque_locator_ref: str


@dataclass(frozen=True)
class ContextAnchor:
    anchor_id: str
    playbook_run_id: str
    run_epoch: int
    step_id: str
    branch_id: str
    session_generation: int
    environment_digest: str
    workspace_snapshot_digest: str
    evidence_manifest_digest: str
    dialogue_checkpoint_ref: str | None
    accepted_hypotheses: tuple[str, ...]


def _digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class RuntimeCapabilities:
    protocol_version: str
    resume: str
    fork: str
    fork_rebinds_cwd: bool
    readonly_enforcement: str
    permission_change: str
    event_replay: str
    remote_stop_verifiable: bool
    host_identity: str
    runtime_version: str
    capability_digest: str


@dataclass(frozen=True)
class PolicyReceipt:
    effective_tier: str
    scope_digest: str
    policy_epoch: int
    host_identity: str
    provider_session_id: str | None
    enforcement: str
    applied_at: float
    guard_digest: str
    binding_revision: int


@dataclass(frozen=True)
class ExecutionPolicy:
    tier: str
    policy_epoch: int
    scope_id: str
    project_path: str
    enforcement: str
    dispatch_ticket: str
    mcp_config: dict


class BackendRuntimeControl:
    """Adapter-owned idle-boundary control; advisory is never reported as a sandbox.

The orchestrator persists returned handles and receipts. Merely resuming a handle
does not send a prompt, and transport reconnect never establishes quiescence.
"""
    def __init__(self, backend):
        self.backend = backend
        self.host_identity = _digest({"backend": backend.name, "host": getattr(backend, "server_url", "local")})
        self.policy = None
        self.environment = None

    async def negotiate(self, environment):
        from app.agents.errors import AgentConfigurationError
        from app.config import settings
        version = await self.backend.probe()
        self.environment = dict(environment)
        enforcement = settings.DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL
        if enforcement != EnforcementLevel.ADVISORY_GUARD and not (
            environment.get("backend_isolation_verified") is True
            and environment.get("backend_host_identity") == self.host_identity
            and environment.get("enforcement") == enforcement
        ):
            raise AgentConfigurationError("SOP_CONFIGURED_ENFORCEMENT_UNAVAILABLE")
        if self.backend.name == "dsh" and enforcement != EnforcementLevel.ADVISORY_GUARD:
            from app.agents.playbook_guard import guard_request
            guard = await guard_request(environment.get("guard_control"), "/capabilities")
            if guard.get("protocol") != "traceforge-playbook-guard/1" or guard.get("pre_execution_deny") is not True:
                raise AgentConfigurationError("SOP_EXECUTOR_GUARD_UNSUPPORTED")
        facts = dict(protocol_version="1", resume="native" if self.backend.capabilities.supports_resume else "rehydrate",
                     fork="deferred" if self.backend.name == "claude-code" else "eager" if self.backend.capabilities.supports_fork else "rehydrate",
                     fork_rebinds_cwd=False, readonly_enforcement=enforcement,
                     permission_change="restart_resume", event_replay="history_reconcile",
                     remote_stop_verifiable=self.backend.name in {"dsh", "opencode"},
                     host_identity=self.host_identity, runtime_version=str(version))
        self.capabilities = RuntimeCapabilities(**facts, capability_digest=_digest(facts))
        return self.capabilities

    def _require_handle(self, handle):
        from app.agents.errors import AgentConfigurationError
        if handle.backend_key != self.backend.name or handle.host_identity != self.host_identity:
            raise AgentConfigurationError("SOP_SESSION_BINDING_MISMATCH")

    async def resume_session(self, handle, anchor):
        self._require_handle(handle)
        if handle.provider_session_id and handle.state != "FORK_PENDING":
            inspection = await self.inspect_session(handle)
            if inspection.get("existence") == "MISSING":
                handle = replace(handle, state="LOST")
        # LOST is explicitly reconstructed from the platform anchor by the next
        # run request; it is never passed as a native resume ID.
        return replace(handle, provider_session_id=None, state="READY", binding_revision=handle.binding_revision + 1) if handle.state == "LOST" else handle

    async def await_quiescence(self, handle, expected_call):
        self._require_handle(handle)
        from app.agents.errors import AgentConfigurationError
        if not expected_call:
            raise AgentConfigurationError("SOP_CALL_IDENTITY_REQUIRED")
        if self.backend.name == "claude-code":
            stopped = await self.backend.cancel()
            confirmed = stopped.local_process_confirmed_dead is True
        elif handle.provider_session_id:
            stopped = await self.backend.cancel_persisted_session(handle.provider_session_id)
            confirmed = stopped.stop_acknowledged
        else:
            raise AgentConfigurationError("SOP_REMOTE_SESSION_UNKNOWN")
        if not confirmed:
            raise AgentConfigurationError("SOP_QUIESCENCE_UNKNOWN")
        return {"call_id": expected_call, "host_identity": self.host_identity,
                "provider_session_id": handle.provider_session_id, "confirmed": True,
                "stop_evidence": asdict(stopped)}

    async def apply_permission_tier(self, handle, policy, expected_binding_revision):
        self._require_handle(handle)
        from app.agents.errors import AgentConfigurationError
        if self.backend.is_running() or handle.binding_revision != expected_binding_revision:
            raise AgentConfigurationError("SOP_POLICY_TRANSITION_NOT_QUIESCENT")
        if policy.tier not in {"READONLY", "WORKSPACE_WRITE"} or not policy.dispatch_ticket:
            raise AgentConfigurationError("SOP_INVALID_POLICY")
        if not hasattr(self, "capabilities") or policy.enforcement != self.capabilities.readonly_enforcement:
            raise AgentConfigurationError("SOP_POLICY_ENFORCEMENT_MISMATCH")
        if self.policy is not None and policy.policy_epoch < self.policy.policy_epoch:
            raise AgentConfigurationError("SOP_POLICY_EPOCH_STALE")
        self.policy = policy
        return PolicyReceipt(policy.tier, _digest({"scope": policy.scope_id, "path": policy.project_path}),
                             policy.policy_epoch, self.host_identity, handle.provider_session_id,
                             policy.enforcement, time.time(), _digest(asdict(policy)), handle.binding_revision)

    async def fork_context(self, handle, anchor, target_binding):
        self._require_handle(handle)
        source = str(Path(target_binding["source_dir"]).resolve(strict=True))
        target = str(Path(target_binding["target_dir"]).resolve(strict=True))
        from app.agents.errors import AgentConfigurationError
        if source == target or not target_binding.get("isolated"):
            raise AgentConfigurationError("SOP_FORK_DIRECTORY_NOT_ISOLATED")
        if not handle.provider_session_id or not self.backend.capabilities.supports_fork:
            return SessionHandle(str(uuid.uuid4()), self.backend.name, self.host_identity, None, "READY", 1, target_binding["locator_ref"])
        provider_id = await self.backend.fork_session(handle.provider_session_id, source_dir=source, target_dir=target)
        pending = self.backend.name == "claude-code" and provider_id == handle.provider_session_id
        if not pending and provider_id == handle.provider_session_id:
            raise AgentConfigurationError("SOP_FORK_NOT_INDEPENDENT")
        return SessionHandle(str(uuid.uuid4()), self.backend.name, self.host_identity, provider_id,
                             "FORK_PENDING" if pending else "READY", 1, target_binding["locator_ref"])

    async def inspect_session(self, handle):
        self._require_handle(handle)
        existence = "UNKNOWN"
        sid = handle.provider_session_id
        if not sid:
            existence = "MISSING"
        elif self.backend.name == "opencode":
            client = await self.backend._ensure_client()
            response = await client.get(f"{self.backend.server_url}/session/{sid}")
            if response.status_code == 200 and self.backend._is_json_response(response):
                existence = "PRESENT" if response.json().get("id") == sid else "UNKNOWN"
            elif response.status_code == 404 and self.backend._is_json_response(response):
                existence = "MISSING"
        elif self.backend.name == "dsh":
            result = await self.backend._rpc("session.list", {})
            items = result.get("items")
            if isinstance(items, list) and all(isinstance(item, dict) and "sessionId" in item for item in items):
                existence = "PRESENT" if any(item["sessionId"] == sid for item in items) else "MISSING"
        elif self.backend.name == "claude-code" and hasattr(self.backend, "_bridge") and self.environment:
            from app.agents.adapters.claude_code.claude_code_adapter import _claude_project_store_dir, _locate_session_file
            import asyncio
            directory = self.environment["bindings"]["source"]
            path = await asyncio.to_thread(_locate_session_file, _claude_project_store_dir(directory), sid)
            existence = "PRESENT" if path else "MISSING"
        return {"handle": asdict(handle), "existence": existence, "locally_running": self.backend.is_running(),
                "quiescence": "UNKNOWN", "host_identity": self.host_identity}


def runtime_control_for(backend):
    control = getattr(backend, "_sop_runtime_control", None)
    if control is None:
        control = BackendRuntimeControl(backend)
        backend._sop_runtime_control = control
    return control


class UnsupportedRuntimeControl:
    async def negotiate(self, environment):
        return {"protocol_version": "1", "resume": "unsupported", "fork": "unsupported",
                "permission_change": "unsupported", "remote_stop_verifiable": False,
                "missing_facts": ["runtime_executor_guard", "verified_policy_receipt"]}

    async def resume_session(self, *args, **kwargs):
        raise NotImplementedError("Runtime control is not certified for this backend")

    await_quiescence = resume_session
    apply_permission_tier = resume_session
    fork_context = resume_session
    inspect_session = resume_session
