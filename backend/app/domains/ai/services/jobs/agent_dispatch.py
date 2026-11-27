"""Persist native session identity before the adapter submits work."""

from app.agents.contract import AgentBackend, current_agent_attempt
from app.agents.errors import AgentError
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob


def _record_native_session(attempt, identity, checkpoint=None):
    with SessionLocal.begin() as db:
        job = db.query(SddAiJob).filter_by(id=attempt.job_id).with_for_update().one()
        if (
            job.run_token != attempt.run_token
            or job.worker_boot_id != attempt.worker_boot_id
            or job.status != AiJobStatus.RUNNING
            or job.cancel_requested_at is not None
            or not job.agent_service_binding
        ):
            raise AgentError("Remote session locator belongs to a stale attempt")
        job.agent_service_binding = {**job.agent_service_binding, "native_session": identity}
        job.agent_backend = job.agent_service_binding["backend"]
        job.session_id = identity["id"]
        if checkpoint is not None:
            # Commit the prepared input with its session before any callback can stop the job.
            job.provider_execution_json = checkpoint


async def record_dsh_prompt(session_id, request_id):
    attempt = current_agent_attempt()
    if not attempt or not attempt.agent_service_binding:
        return
    await run_db(_record_dsh_prompt_sync, attempt, session_id, request_id)


def _record_dsh_prompt_sync(attempt, session_id, request_id):
    with SessionLocal.begin() as db:
        job = db.query(SddAiJob).filter_by(id=attempt.job_id).with_for_update().one()
        if (
            job.run_token != attempt.run_token
            or job.worker_boot_id != attempt.worker_boot_id
            or job.status != AiJobStatus.RUNNING
            or job.cancel_requested_at is not None
        ):
            raise AgentError("DSH prompt belongs to a stale attempt")
        job.provider_execution_json = {"provider": "dsh", "session_id": session_id, "request_id": request_id}


def guard_native_session(backend: AgentBackend, request, sink):
    attempt = current_agent_attempt()
    binding = attempt.agent_service_binding if attempt else None
    if not binding or backend.name != binding["backend"]:
        return sink

    async def guarded(event):
        if event.type == "session_started" and not request.execution_checkpoint:
            sid = event.payload["provider_session_id"]
            identity = {
                "id": sid,
                "directory": request.project_path,
                "created": getattr(backend, "_native_created", None),
            }
            checkpoint = None
            if backend.name == "opencode" and request.on_execution_checkpoint is not None:
                from app.domains.ai.services.jobs.remote_recovery import valid_checkpoint

                checkpoint = dict(getattr(backend, "_execution_checkpoint", {}))
                if (
                    not valid_checkpoint(checkpoint)
                    or checkpoint["phase"] != "prepared"
                    or checkpoint["session_id"] != sid
                ):
                    raise AgentError("OpenCode dispatch is missing its prepared input checkpoint")
            await run_db(_record_native_session, attempt, identity, checkpoint)
            backend._dispatch_identity = identity
        await sink(event)

    return guarded


async def verify_bound_stop(backend, session_id):
    from app.agents.service_binding import OLD_SERVICE_MESSAGE, OLD_SERVICE_UNKNOWN, matches_native_session

    identity = getattr(backend, "_dispatch_identity", None)
    if identity:
        try:
            if await matches_native_session(backend, identity, session_id):
                return
        except Exception:
            pass
        raise AgentError(OLD_SERVICE_MESSAGE, failure_code=OLD_SERVICE_UNKNOWN)


def has_bound_dispatch(backend):
    attempt = current_agent_attempt()
    binding = attempt.agent_service_binding if attempt else None
    return bool(binding and binding["backend"] == backend.name)
