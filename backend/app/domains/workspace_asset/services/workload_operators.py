"""Fixed, versioned workload operators using observable events only."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import log2
from typing import Generic, ParamSpec, TypeVar

from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.workspace_asset.schemas.workload import WorkloadExecution

GRAPH_VERSION = 2


@dataclass(frozen=True)
class Operator:
    name: str
    version: int
    inputs: tuple[str, ...]
    output: str
    scope: str
    missing: str


_SPECS = (
    Operator("ExecutionProject", 2, ("durable_records",), "executions", "attempt", "uncertain"),
    Operator("EventNormalize", 1, ("durable_records", "executions"), "events", "workspace", "exclude invalid signal"),
    Operator("HumanItemProject", 2, ("durable_records", "executions"), "human_items", "request", "retain known items"),
    Operator("InteractionAccumulator", 2, ("events",), "interaction", "conversation", "start observing"),
    Operator("SlotProjection", 1, ("executions", "human_items", "interaction"), "slots", "attempt", "incomplete"),
    Operator(
        "FollowupCheckProject",
        2,
        ("durable_records", "executions"),
        "checks",
        "delivery cycle",
        "unassigned or unspecified",
    ),
    Operator("MemberAggregate", 1, ("slots", "human_items", "checks"), "members", "workspace", "retain facts"),
)
OPERATOR_SPECS = {spec.name: spec for spec in _SPECS}
P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class RegisteredOperator(Generic[P, R]):
    spec: Operator
    evaluate: Callable[P, R]

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        return self.evaluate(*args, **kwargs)


_registered: dict[str, Operator] = {}


def register(name: str):
    def bind(evaluate: Callable[P, R]) -> RegisteredOperator[P, R]:
        if name in _registered:
            raise ValueError(f"Duplicate workload operator: {name}")
        spec = OPERATOR_SPECS[name]
        _registered[name] = spec
        return RegisteredOperator(spec, evaluate)

    return bind


def verify_graph() -> None:
    available = {"durable_records"}
    for spec in _SPECS:
        if spec.name not in _registered or not set(spec.inputs) <= available or spec.output in available:
            raise ValueError(f"Invalid workload operator dependency: {spec.name}")
        available.add(spec.output)


@dataclass(frozen=True)
class InteractionPolicy:
    half_life_seconds: float = 60
    ceiling: float = 2
    enter: float = 1.2
    leave: float = 0.5

    def __post_init__(self):
        if self.half_life_seconds <= 0 or not 0 < self.leave < self.enter <= self.ceiling:
            raise ValueError("Invalid workload interaction policy")


POLICY = InteractionPolicy()


@dataclass(frozen=True)
class Interaction:
    strength: float
    following: bool
    next_evaluate_at: datetime | None


@register("InteractionAccumulator")
def interaction_accumulator(
    events: Iterable[tuple[str, datetime]],
    as_of: datetime,
    *,
    since: datetime | None = None,
    policy: InteractionPolicy = POLICY,
) -> Interaction:
    """Replay one conversation generation, with an optional confirmed phase boundary."""
    strength, following, last = 0.0, False, None
    seen: set[str] = set()
    for key, occurred_at in sorted(events, key=lambda event: (event[1], event[0])):
        if key in seen or occurred_at > as_of:
            continue
        # A replay cannot move a business submission across the phase boundary.
        seen.add(key)
        if since is not None and occurred_at < since:
            continue
        if last is not None:
            strength *= 2 ** (-(occurred_at - last).total_seconds() / policy.half_life_seconds)
            following = following and strength > policy.leave
        strength = min(policy.ceiling, strength + 1)
        following = following or strength >= policy.enter
        last = occurred_at
    if last is None:
        return Interaction(0, False, None)
    deadline = last + timedelta(seconds=policy.half_life_seconds * log2(strength / policy.leave)) if following else None
    strength *= 2 ** (-(as_of - last).total_seconds() / policy.half_life_seconds)
    if deadline is not None and as_of >= deadline:
        deadline = None
    return Interaction(strength, deadline is not None, deadline)


def execution_state(job, as_of: datetime, current_revision: int) -> str | None:
    if job.status in (AiJobStatus.ORPHANED, AiJobStatus.TERMINATING):
        return "uncertain"
    if job.status != AiJobStatus.RUNNING:
        return None
    if (
        not job.started_at
        or job.started_at > as_of
        or (job.lease_expires_at and job.lease_expires_at <= as_of)
        or (job.session_revision is not None and job.session_revision != current_revision)
    ):
        return "uncertain"
    return "active"


@register("SlotProjection")
def slot_projection(job, task, state, pending, interaction: Interaction, as_of: datetime) -> WorkloadExecution:
    if state == "uncertain":
        slot, reason = "uncertain", "uncertain"
    elif pending:
        slot, reason = "interactive", "reply"
    elif interaction.following:
        slot, reason = "interactive", "recent_activity"
    elif task.status.value == "AWAITING_INPUT" or job.agent_backend not in {"opencode", "claude", "claude_code", "dsh"}:
        slot, reason = "incomplete", "incomplete"
    else:
        slot, reason = "background", "started" if (as_of - job.started_at).total_seconds() < 60 else "running"
    return WorkloadExecution(
        id=job.id, title=task.name, task_id=task.id, slot=slot, reason=reason, since=job.started_at
    )
