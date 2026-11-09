"""Seed domain inputs and their single execution identity in database tests."""

from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.api_mock.models.api_mock import SddApiMockJob
from app.domains.skill.models.skill import SddSkillAnalysis
from app.domains.workflow.models.provision_job import SddProvisionJob


def seed_domain_job(model, kind, source, **kwargs):
    job_id = kwargs.pop("id", None) or str(uuid4())
    fields = {
        key: kwargs.pop(key)
        for key in list(kwargs)
        if key
        in {
            "status",
            "progress",
            "stage",
            "message",
            "error_message",
            "started_at",
            "finished_at",
            "updated_at",
        }
    }
    if "updated_at" in fields:
        fields["state_changed_at"] = fields.pop("updated_at")
    if kind != "SKILL_ANALYSIS" and "result_json" in kwargs:
        fields["result_json"] = kwargs.pop("result_json")
    cancel = kwargs.pop("cancel_requested", False)
    fields["status"] = AiJobStatus(getattr(fields.get("status", "PENDING"), "value", fields.get("status", "PENDING")))
    resource = kwargs.get("project_id") or job_id
    execution = SddAiJob(
        id=job_id,
        workspace_id=kwargs.get("workspace_id"),
        task_id=kwargs.get("task_id"),
        creator_id=kwargs.get("creator_id") or kwargs.get("created_by_id"),
        channel=AiJobChannel.BACKGROUND,
        queue_key=f"DOMAIN_JOB:{kind}:{resource}",
        queue_source=source,
        job_type=str(getattr(kwargs.get("job_type", kind), "value", kwargs.get("job_type", kind))),
        resource_id=resource,
        context_json={"job_kind": kind, "inputs": {}},
        cancel_requested_at=datetime.utcnow() if cancel else None,
        **fields,
    )
    return model(id=job_id, execution=execution, **kwargs)


def make_analysis(**kwargs):
    return seed_domain_job(SddSkillAnalysis, "SKILL_ANALYSIS", "skill_analysis", **kwargs)


def make_mock_job(**kwargs):
    return seed_domain_job(SddApiMockJob, "API_MOCK", "api_mock", **kwargs)


def make_provision_job(**kwargs):
    return seed_domain_job(SddProvisionJob, "PROVISION", "provision", **kwargs)


@contextmanager
def bound_domain_attempt(db, job_id):
    from unittest.mock import patch

    from sqlalchemy.orm import sessionmaker

    from app.agents import bind_agent_attempt, reset_agent_attempt
    from app.domains.ai.services.jobs import attempts, registry, store
    from tests.ai.jobs.ai_job_test_utils import patched_ai_job_db

    db.commit()
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    with (
        patched_ai_job_db(factory),
        patch("app.database.SessionLocal", factory),
        patch.object(registry.runtime, "shutting_down", False),
    ):
        with patch.object(store, "resolve_execution_kind_for_claim", lambda *_args, **_kwargs: "LOCAL_PROCESS"):
            queue = db.get(SddAiJob, job_id).queue_key
            db.commit()
            assert store.take_next_pending_job_id_sync(queue) == job_id
        token = bind_agent_attempt(attempts.load_attempt_context_sync(job_id))
        try:
            db.expire_all()
            yield
        finally:
            reset_agent_attempt(token)


_active_provision_runs = {}


async def run_provision_job(service, job_id):
    """Exercise provisioning through the real claim/attempt/finalizer boundary."""
    from contextlib import ExitStack
    from unittest.mock import patch

    from app.domains.ai.services.jobs import queue_runner, registry
    from tests.ai.jobs.ai_job_test_utils import patched_ai_job_db

    factory = service.SessionLocal
    with factory() as db:
        key = db.get(SddAiJob, job_id).queue_key
    state = _active_provision_runs.get(factory)
    if state is None:
        stack = ExitStack()
        stack.enter_context(patched_ai_job_db(factory))
        stack.enter_context(patch("app.database.SessionLocal", factory))
        stack.enter_context(patch.object(registry.runtime, "shutting_down", False))
        stack.enter_context(patch.object(registry.runtime, "schedule_queue", lambda *_args: None))

        async def no_broadcast(*_args):
            pass

        stack.enter_context(patch("app.domains.ai.services.jobs.publishing.broadcast_job_payload", no_broadcast))
        state = [stack, 0]
        _active_provision_runs[factory] = state
    state[1] += 1
    try:
        await queue_runner.run_queue(key)
    finally:
        state[1] -= 1
        if not state[1]:
            state[0].close()
            del _active_provision_runs[factory]
