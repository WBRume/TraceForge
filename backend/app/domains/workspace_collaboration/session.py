"""Page-scoped driver leases and download-only snapshots."""

from datetime import datetime

from . import content, manifest_store, service
from .models import CollaborationSnapshot


def uses_local_input(state, actor_id):
    return bool(
        state and state.enabled and state.driver_user_id == actor_id and state.lease_expires_at > datetime.utcnow()
    )


def cloud_input_available(state):
    return state.sync_phase in {"READY", "DELIVERY_PENDING", "CONFLICT_PENDING"} or (
        state.sync_phase == "RECOVERY_REQUIRED" and state.recovery_kind == "LOCAL_DELIVERY"
    )


def is_cloud_input(db, task_id, submission_id):
    from app.domains.task.models.chat_submission import TaskChatSubmission

    submission = db.get(TaskChatSubmission, submission_id) if submission_id else None
    return bool(
        submission and submission.task_id == task_id and "collaboration" not in (submission.metadata_json or {})
    )


def request_cloud_input(db, task, state, submission_id):
    """Pin existing cloud code; a detached desktop is never an input dependency."""
    if not cloud_input_available(state):
        service._fail("CLOUD_WORKSPACE_NOT_READY", "Wait for the cloud execution or workspace recovery to finish")
    service._assert_no_writer(db, task.id)
    service.get_snapshot(db, task.id, state.snapshot_id)
    state.pending_submission_id = submission_id
    state.input_submission_id = submission_id
    state.input_snapshot_id = state.snapshot_id
    state.input_cut_seq = None
    state.run_id = None
    state.progress_snapshot_id = None
    state.recovery_kind = None
    state.recovery_message = None
    state.sync_phase = "PREPARING"
    service._bump(state)
    db.flush()
    return service.get_state(db, task)


def download(db, task, user_id, base_snapshot_id):
    target = latest_snapshot(db, task, user_id, None)
    if base_snapshot_id:
        from .delta import between

        try:
            base = service.get_snapshot(db, task.id, base_snapshot_id)
        except service.CollaborationError as exc:
            if exc.status_code != 404:
                raise
        else:
            return between(base, target)
    return target


def release_driver(db, task, user_id, request):
    state = service._state(db, task.id)
    if state is None or not state.enabled:
        return service.get_state(db, task)
    previous = service._operation(db, task.id, request.operation_id, "RELEASE_DRIVER", request.model_dump())
    if previous and state.driver_user_id == user_id:
        return service.get_state(db, task)
    service._check_driver_identity(state, user_id, request)
    # Fence queued uploads/heartbeats immediately, without stopping the Agent or
    # deleting delivery/conflict evidence needed by the next connection.
    state.lease_epoch += 1
    state.lease_expires_at = datetime.utcnow()
    service._bump(state)
    return service._record(db, task, request.operation_id, "RELEASE_DRIVER", request.model_dump())


def latest_snapshot(db, task, _user_id, _request):
    """Downloading never enables collaboration, takes a lease or acknowledges delivery."""
    service._check_task(task)
    state = service._state(db, task.id)
    if state and state.enabled:
        service._check_session(state, task)
        service._check_repositories(db, state, task)
        snapshot_id = (
            state.progress_snapshot_id or state.snapshot_id
            if state.sync_phase in service.ACTIVE_PHASES
            else state.snapshot_id
        )
        if not snapshot_id:
            service._fail("SNAPSHOT_NOT_READY", "No published cloud version is available yet")
        return service.get_snapshot(db, task.id, snapshot_id)
    service._assert_no_writer(db, task.id, read_only=True)
    repositories = service.repository_metadata(db, task)
    service._ensure_store(db, task)
    captured = service._inventory(task, task.project_path, repositories, stable=True)
    digest = content.digest(captured)
    previous = (
        db.query(CollaborationSnapshot)
        .filter_by(task_id=task.id, content_digest=digest, source="DOWNLOAD")
        .order_by(CollaborationSnapshot.created_at.desc(), CollaborationSnapshot.id.desc())
        .first()
    )
    if previous and (previous.manifest_json["session_generation"], previous.manifest_json["session_revision"]) == (
        task.session_generation,
        task.session_revision,
    ):
        return manifest_store.read_manifest(db, previous)
    # Transient metadata only: no driver or collaboration state is created.
    from .models import CollaborationState

    metadata = CollaborationState(
        workspace_revision=state.workspace_revision if state else 0,
        session_generation=task.session_generation or 0,
        session_revision=task.session_revision or 0,
        repository_set_digest=content.digest(repositories),
    )
    return service._snapshot(db, task, metadata, "DOWNLOAD", captured)
