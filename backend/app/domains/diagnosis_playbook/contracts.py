"""Immutable, canonical contracts and typed failure semantics."""
import hashlib
import json
from dataclasses import dataclass
from typing import Any


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class PlaybookError(ValueError):
    def __init__(self, code: str, *, status: int = 422, missing_facts=(), version=None):
        super().__init__(code)
        self.status = status
        self.detail = {"code": code, "missing_facts": list(missing_facts), "recoverable": status == 409, "current_state_version": version}


@dataclass(frozen=True)
class ExecutionEnvelope:
    execution_id: str
    run_id: str
    run_epoch: int
    step_id: str
    step_attempt_id: str
    branch_id: str
    contract_digest: str
    environment_digest: str
    source_snapshot_digest: str
    policy_epoch: int
    bundle_digest: str
    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: int
    enforcement: str
