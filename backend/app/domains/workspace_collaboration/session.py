"""Page-scoped driver leases and download-only snapshots."""

from datetime import datetime

from . import content, service
from .models import CollaborationSnapshot


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
    state = service._state(db, task.id)
    if task.execution_location != "SERVER":
        service._fail("SERVER_TASK_REQUIRED", "Only server tasks have downloadable cloud code")
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
    service._assert_no_writer(db, task.id)
    repositories = service.repository_metadata(db, task)
    service._ensure_store(db, task)
    captured = service._inventory(task.id, task.project_path, repositories, stable=True)
    digest = content.digest(captured)
    previous = (
        db.query(CollaborationSnapshot)
        .filter_by(task_id=task.id, content_digest=digest, source="DOWNLOAD")
        .order_by(CollaborationSnapshot.created_at.desc())
        .first()
    )
    if previous and (previous.manifest_json["session_generation"], previous.manifest_json["session_revision"]) == (
        task.session_generation,
        task.session_revision,
    ):
        return previous.manifest_json
    # Transient metadata only: no driver or collaboration state is created.
    from .models import CollaborationState

    metadata = CollaborationState(
        workspace_revision=state.workspace_revision if state else 0,
        session_generation=task.session_generation or 0,
        session_revision=task.session_revision or 0,
        repository_set_digest=content.digest(repositories),
    )
    return service._snapshot(db, task, metadata, "DOWNLOAD", captured)
