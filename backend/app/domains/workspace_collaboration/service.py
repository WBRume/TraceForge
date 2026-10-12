"""Transactional coordinator for complete multi-repository workspace delivery.

Functions accept the caller's SQLAlchemy transaction. Mutations serialize on the
task row (including initial enable) and the collaboration row. Large file bytes
are immutable and stored separately; durable manifests reference verified bytes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, object_session

from app.domains.task.models.task import SddTask
from app.domains.task.models.task_repository import SddTaskRepository

from . import content
from .models import CollaborationHandoff, CollaborationOperation, CollaborationSnapshot, CollaborationState
from .schemas import DeliveryReceipt, EnableRequest, Fence, HandoffRequest, LeaseRequest

LEASE_SECONDS = 60
ACTIVE_PHASES = {"PREPARING", "RUNNING", "WAITING_HITL", "STOPPING", "SETTLING"}


class CollaborationError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _fail(code: str, message: str) -> None:
    raise CollaborationError(code, message)


def _state(db: Session, task_id: str, *, lock: bool = True, nowait: bool = False) -> CollaborationState | None:
    try:
        if lock:
            db.flush()
            db.query(SddTask).filter_by(id=task_id).populate_existing().with_for_update(nowait=nowait).first()
        query = db.query(CollaborationState).filter_by(task_id=task_id)
        return (query.populate_existing().with_for_update(nowait=nowait) if lock else query).first()
    except OperationalError as exc:
        code = exc.orig.args[0] if exc.orig.args else None
        if nowait and (code in {1205, 3572} or getattr(exc.orig, "pgcode", None) == "55P03"):
            _fail("TASK_BUSY", "Workspace capture is in progress; retry shortly")
        raise


def repository_metadata(db: Session, task: SddTask) -> list[dict]:
    rows = db.query(SddTaskRepository).filter_by(task_id=task.id).order_by(SddTaskRepository.id).all()
    if not rows:
        _fail("TASK_REPO_BINDING_MISMATCH", "Task has no prepared repository bindings")
    result = []
    paths = set()
    for row in rows:
        state = getattr(row.state, "value", row.state)
        if state != "READY" or not row.base_commit_sha:
            _fail("TASK_REPO_BINDING_MISMATCH", f"Repository {row.repo_slug} has no ready task baseline")
        content.validate_path(row.rel_path)
        if row.rel_path.casefold() in paths:
            _fail("TASK_REPO_BINDING_MISMATCH", "Task repository paths collide")
        paths.add(row.rel_path.casefold())
        result.append(
            {
                "task_repository_id": row.id,
                "repository_id": row.repository_id,
                "repo_url": row.repo_url,
                "repo_slug": row.repo_slug,
                "rel_path": row.rel_path,
                "branch_name": row.branch_name,
                "base_commit_sha": row.base_commit_sha,
            }
        )
    return result


def _check_session(state: CollaborationState, task: SddTask) -> None:
    if task.execution_location != "SERVER":
        _fail("SERVER_TASK_REQUIRED", "Collaboration binding cannot change task execution location")
    if (state.session_generation, state.session_revision) != (task.session_generation, task.session_revision):
        _fail("SESSION_CHANGED", "Task session changed; collaboration must be reconciled")


def _check_repositories(db: Session, state: CollaborationState, task: SddTask) -> list[dict]:
    repositories = repository_metadata(db, task)
    if content.digest(repositories) != state.repository_set_digest:
        _fail("REPOSITORY_SET_CHANGED", "Task repository bindings changed")
    return repositories


def _check_driver_identity(state: CollaborationState, user_id: str, request: LeaseRequest) -> None:
    if not state.enabled:
        _fail("COLLABORATION_DISABLED", "Local collaboration is disabled")
    if (state.driver_user_id, state.client_id, state.instance_id, state.lease_epoch) != (
        user_id,
        request.client_id,
        request.instance_id,
        request.lease_epoch,
    ):
        _fail("DRIVER_REQUIRED", "Only the active desktop instance can perform this operation")


def _check_driver(state: CollaborationState, user_id: str, request: LeaseRequest) -> None:
    _check_driver_identity(state, user_id, request)
    if state.lease_expires_at <= datetime.utcnow():
        _fail("LEASE_EXPIRED", "The desktop collaboration lease expired")


def _complete_driver_operation(state: CollaborationState, user_id: str, request: LeaseRequest) -> None:
    # Entry validated the live lease; the held task/state locks reserve this
    # epoch until installation finishes and prevent takeover or heartbeat writes.
    _check_driver_identity(state, user_id, request)
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)


def _reserve_driver_lease(state: CollaborationState) -> tuple | None:
    if not state.enabled or state.lease_expires_at <= datetime.utcnow():
        return None
    return (state.driver_user_id, state.client_id, state.instance_id, state.lease_epoch)


def _renew_reserved_lease(state: CollaborationState, reserved: tuple | None) -> None:
    if state.enabled and reserved == (state.driver_user_id, state.client_id, state.instance_id, state.lease_epoch):
        state.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)


def _check_fence(state: CollaborationState, task: SddTask, user_id: str, request: Fence) -> None:
    _check_driver(state, user_id, request)
    _check_session(state, task)
    if (request.session_generation, request.session_revision) != (state.session_generation, state.session_revision):
        _fail("SESSION_CHANGED", "Request belongs to an old task session")
    if request.expected_state_version != state.state_version:
        _fail("STATE_VERSION_MISMATCH", "Collaboration state changed; refresh before retrying")
    if request.expected_workspace_revision != state.workspace_revision:
        _fail("WORKSPACE_REVISION_MISMATCH", "Request targets an old code revision")


def _bump(state: CollaborationState) -> None:
    state.state_version += 1
    db = object_session(state)
    if db is not None:
        from .events import emit_state

        emit_state(db, state)


def get_state(db: Session, task: SddTask) -> dict:
    state = _state(db, task.id, lock=False)
    try:
        repositories = repository_metadata(db, task)
        repository_error = None
    except CollaborationError as exc:
        repositories = []
        repository_error = {"code": exc.code, "message": str(exc)}
    if not state:
        return {
            "enabled": False,
            "capabilities": {"manifest_delta": 1},
            "sync_phase": "OFF",
            "task_id": task.id,
            "state_version": 0,
            "workspace_revision": 0,
            "repositories": repositories,
            "repository_error": repository_error,
            "repository_set_digest": content.digest(repositories),
            "session_generation": task.session_generation,
            "session_revision": task.session_revision,
            "conflicts": [],
            "pending_local_changes": [],
        }
    result = {column.name: getattr(state, column.name) for column in state.__table__.columns}
    result.pop("conflicts_json")
    result.pop("pending_local_changes_json")
    result["conflicts"] = state.conflicts_json or []
    result["pending_local_changes"] = state.pending_local_changes_json or []
    result["repositories"] = repositories
    result["capabilities"] = {"manifest_delta": 1}
    result["repository_error"] = repository_error
    result["lease_expires_at"] = state.lease_expires_at.isoformat() + "Z"
    result["updated_at"] = state.updated_at.isoformat() + "Z" if state.updated_at else None
    result["driver_connected"] = state.enabled and state.lease_expires_at > datetime.utcnow()
    result["input_mode"] = "CLOUD" if state.input_submission_id and state.input_cut_seq is None else "LOCAL"
    return result


def get_snapshot(db: Session, task_id: str, snapshot_id: str) -> dict:
    row = db.query(CollaborationSnapshot).filter_by(task_id=task_id, id=snapshot_id).first()
    if not row:
        raise CollaborationError("SNAPSHOT_NOT_FOUND", "Collaboration snapshot not found", 404)
    return row.manifest_json


def _operation(db: Session, task_id: str, operation_id: str, kind: str, payload: dict) -> dict | None:
    row = db.query(CollaborationOperation).filter_by(task_id=task_id, operation_id=operation_id).first()
    if row:
        if row.kind != kind or row.payload_hash != content.digest(payload):
            _fail("OPERATION_REUSED", "Operation identity was reused with a different request")
        return row.result_json
    return None


def _record(db: Session, task: SddTask, operation_id: str, kind: str, payload: dict) -> dict:
    db.flush()
    result = get_state(db, task)
    db.add(
        CollaborationOperation(
            id=str(uuid4()),
            task_id=task.id,
            operation_id=operation_id,
            kind=kind,
            payload_hash=content.digest(payload),
            result_json=result,
        )
    )
    return result


def _ensure_store(db: Session, task: SddTask) -> content.ObjectStore:
    from app.domains.auth.models.user import Workspace
    from app.domains.task.services import task_session_snapshot_service as snapshots

    metadata = dict(task.task_meta_json or {})
    initial = metadata.get("initial_workspace_checkpoint")
    if not initial:
        # Older tasks can predate provisioning-time snapshots. Establish their
        # first shared store once; a supplied but broken checkpoint never resets.
        workspace = db.get(Workspace, task.workspace_id)
        created = snapshots._create_checkpoint_sync(
            task.project_path,
            [repo["rel_path"] for repo in repository_metadata(db, task)],
            "none",
            None,
            task.workspace_id,
            workspace.name,
            task.id,
            task.name,
        )
        initial = created["root"]
        metadata["initial_workspace_checkpoint"] = initial
        task.task_meta_json = metadata
        db.flush()
    store = content.ObjectStore(task.id)
    store.bind(initial, task.project_path)
    return store


def _capture(db: Session, task: SddTask, state: CollaborationState, source: str, *, stable: bool) -> dict:
    repositories = _check_repositories(db, state, task)
    _ensure_store(db, task)
    captured = _inventory(task.id, task.project_path, repositories, stable=stable)
    return _snapshot(db, task, state, source, captured)


def _inventory(task_id: str, project_path: str, repositories: list[dict], *, stable: bool) -> list[dict]:
    if not project_path:
        _fail("WORKSPACE_UNAVAILABLE", "Task execution directory is unavailable")
    return content.capture_task(
        Path(project_path).resolve(strict=True), content.ObjectStore(task_id), repositories, stable=stable
    )


def _snapshot(db: Session, task: SddTask, state: CollaborationState, source: str, repositories: list[dict]) -> dict:
    snapshot_id = str(uuid4())
    if source != "PROGRESS":
        import json

        from app.domains.task.services import task_snapshot_store

        private_root = content.ObjectStore(task.id).root
        capture_path = private_root / "captures" / (content.digest(repositories) + ".json")
        if capture_path.exists():
            # Bind the full private checkpoint to this exact public snapshot.
            # Its paths and ignored files never enter the public manifest.
            task_snapshot_store.write_json(
                str(private_root / "snapshots" / (snapshot_id + ".json")),
                json.loads(capture_path.read_text(encoding="utf-8")),
            )
    manifest = {
        "protocol_version": 1,
        "snapshot_id": snapshot_id,
        "task_id": task.id,
        "workspace_revision": state.workspace_revision + (0 if source == "PROGRESS" else 1),
        "parent_snapshot_id": state.snapshot_id,
        "session_generation": state.session_generation,
        "session_revision": state.session_revision,
        "repository_set_digest": state.repository_set_digest,
        "source": source,
        "run_id": state.run_id,
        "execution_epoch": state.execution_epoch,
        "progress_seq": state.progress_seq,
        "repositories": repositories,
    }
    db.add(
        CollaborationSnapshot(
            id=snapshot_id,
            task_id=task.id,
            manifest_json=manifest,
            content_digest=content.digest(repositories),
            source=source,
        )
    )
    db.flush()
    return manifest


def _publish(state: CollaborationState, manifest: dict) -> None:
    state.snapshot_id = manifest["snapshot_id"]
    state.workspace_revision = manifest["workspace_revision"]
    _bump(state)


def _record_handoff(
    db: Session,
    task: SddTask,
    state: CollaborationState,
    baseline: dict,
    target: dict,
    operation_id: str,
    submission_id: str | None,
    origin: dict | None = None,
) -> None:
    if db.query(CollaborationHandoff.id).filter_by(task_id=task.id, operation_id=operation_id).first():
        return
    previous = {repo["task_repository_id"]: repo for repo in baseline["repositories"]}
    deltas = []
    for repo in target["repositories"]:
        old = {entry["path"]: entry for entry in previous[repo["task_repository_id"]]["files"]}
        new = {entry["path"]: entry for entry in repo["files"]}
        files = [
            {"path": path, "before": old.get(path), "after": new.get(path)}
            for path in sorted(set(old) | set(new))
            if old.get(path) != new.get(path)
        ]
        if files:
            deltas.append(
                {
                    "task_repository_id": repo["task_repository_id"],
                    "repo_slug": repo["repo_slug"],
                    "branch_name": repo["branch_name"],
                    "files": files,
                }
            )
    if not deltas:
        return
    origin = origin or {
        "actor_user_id": state.driver_user_id,
        "client_id": state.client_id,
        "binding_id": state.binding_id,
        "lease_epoch": state.lease_epoch,
    }
    handoff = CollaborationHandoff(
        id=str(uuid4()),
        task_id=task.id,
        operation_id=operation_id,
        submission_id=submission_id,
        actor_user_id=origin["actor_user_id"],
        client_id=origin["client_id"],
        binding_id=origin["binding_id"],
        lease_epoch=origin["lease_epoch"],
        base_snapshot_id=baseline["snapshot_id"],
        input_snapshot_id=target["snapshot_id"],
        repository_deltas_json=deltas,
    )
    db.add(handoff)
    from .history import record_delta

    record_delta(db, task, handoff)


def handoff_history(db: Session, task_id: str) -> list[dict]:
    return [
        {
            **{
                column.name: getattr(row, column.name)
                for column in row.__table__.columns
                if column.name != "created_at"
            },
            "created_at": row.created_at.isoformat() + "Z",
        }
        for row in db.query(CollaborationHandoff)
        .filter_by(task_id=task_id)
        .order_by(CollaborationHandoff.created_at.desc())
        .limit(100)
    ]


def enable(db: Session, task: SddTask, user_id: str, request: EnableRequest) -> dict:
    state = _state(db, task.id)
    previous = _operation(db, task.id, request.operation_id, "ENABLE", request.model_dump())
    if previous:
        return previous
    if str(task.execution_location) != "SERVER":
        _fail("SERVER_TASK_REQUIRED", "Local collaboration is available only for server tasks")
    if state and state.enabled:
        _fail("ALREADY_ENABLED", "Task collaboration is already enabled")
    _assert_no_writer(db, task.id)
    repos = repository_metadata(db, task)
    if state is None:
        state = CollaborationState(task_id=task.id, state_version=1, workspace_revision=0, lease_epoch=0)
        db.add(state)
    state.enabled = True
    state.sync_phase = "DELIVERY_PENDING"
    state.session_generation = task.session_generation or 0
    state.session_revision = task.session_revision or 0
    state.repository_set_digest = content.digest(repos)
    state.binding_id = str(uuid4())
    state.driver_user_id = user_id
    state.client_id = request.client_id
    state.instance_id = request.instance_id
    state.lease_epoch += 1
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)
    state.conflicts_json = []
    state.pending_local_changes_json = []
    state.pending_submission_id = None
    state.input_submission_id = None
    state.run_id = None
    state.progress_seq = 0
    state.progress_snapshot_id = None
    state.final_progress_seq = None
    state.execution_epoch = 0
    state.reconciled_revision = 0
    state.recovery_kind = None
    state.recovery_message = None
    state.recovery_operation_id = None
    initial = _capture(db, task, state, "INITIAL", stable=True)
    # Initial capture can outlast the lease, before the client can renew it.
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)
    _publish(state, initial)
    state.input_snapshot_id = initial["snapshot_id"]
    return _record(db, task, request.operation_id, "ENABLE", request.model_dump())


def renew_lease(db: Session, task: SddTask, user_id: str, request: LeaseRequest) -> dict:
    try:
        state = _state(db, task.id, nowait=True)
    except OperationalError as exc:
        code = exc.orig.args[0] if exc.orig.args else None
        if code in {1205, 3572} or getattr(exc.orig, "pgcode", None) == "55P03":
            _fail("TASK_BUSY", "Workspace capture is in progress; retry the lease shortly")
        raise
    if state is None:
        _fail("COLLABORATION_DISABLED", "Local collaboration is disabled")
    # Expiration requires an explicit claim and a new epoch, even for the same
    # process, so queued requests from the expired lease stay fenced.
    if (state.driver_user_id, state.client_id, state.instance_id, state.lease_epoch) != (
        user_id,
        request.client_id,
        request.instance_id,
        request.lease_epoch,
    ) or not state.enabled:
        _fail("DRIVER_REQUIRED", "This desktop instance is not the task driver")
    if state.lease_expires_at <= datetime.utcnow():
        _fail("LEASE_EXPIRED", "The desktop lease expired; reclaim the driver before continuing")
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)
    db.flush()
    return get_state(db, task)


def _assert_no_writer(db: Session, task_id: str) -> None:
    from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob

    live = (
        db.query(SddAiJob.id)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.in_(
                [
                    AiJobStatus.PENDING,
                    AiJobStatus.RUNNING,
                    AiJobStatus.WAITING_HITL,
                    AiJobStatus.TERMINATING,
                    AiJobStatus.ORPHANED,
                ]
            ),
        )
        .first()
    )
    if live:
        _fail("WRITER_ACTIVE", "Wait for the server execution writer to stop")


def request_input(db: Session, task: SddTask, submission_id: str, user_id: str) -> dict | None:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return None
    _check_session(state, task)
    _check_repositories(db, state, task)
    if state.pending_submission_id == submission_id:
        return get_state(db, task)
    from app.domains.task.models.chat_submission import TaskChatSubmission

    submission = db.get(TaskChatSubmission, submission_id)
    if submission and "collaboration" not in (submission.metadata_json or {}):
        from .session import request_cloud_input

        return request_cloud_input(db, task, state, submission_id)
    if state.sync_phase != "READY":
        _fail("DELIVERY_REQUIRED", "Complete the current code delivery before starting another round")
    if state.lease_expires_at <= datetime.utcnow():
        _fail("LEASE_EXPIRED", "Open the driver desktop before starting a collaborative round")
    if state.driver_user_id != user_id:
        _fail("DRIVER_REQUIRED", "Only the driver may request a new collaborative round")
    identity = (submission.metadata_json or {}).get("collaboration", {}) if submission else {}
    delegated_input = identity.get("request_driver_input") is True and (
        identity.get("binding_id"),
        identity.get("lease_epoch"),
    ) == (state.binding_id, state.lease_epoch)
    if (
        identity.get("client_id"),
        identity.get("instance_id"),
        identity.get("binding_id"),
        identity.get("lease_epoch"),
    ) != (
        state.client_id,
        state.instance_id,
        state.binding_id,
        state.lease_epoch,
    ) and not delegated_input:
        _fail("DRIVER_REQUIRED", "The message must be sent from the bound desktop instance")
    state.pending_submission_id = submission_id
    state.input_submission_id = None
    state.run_id = None
    state.progress_snapshot_id = None
    state.sync_phase = "PREPARING"
    _bump(state)
    db.flush()
    return get_state(db, task)


def input_ready(db: Session, task_id: str, submission_id: str) -> bool:
    from .session import is_cloud_input

    state = _state(db, task_id, lock=False)
    return (
        not state
        or not state.enabled
        or (
            state.sync_phase == "PREPARING"
            and state.input_submission_id == submission_id
            and state.pending_submission_id == submission_id
            and (state.lease_expires_at > datetime.utcnow() or is_cloud_input(db, task_id, submission_id))
        )
    )


def input_worktree_checkpoint(db: Session, task: SddTask, submission_id: str) -> dict | None:
    """Return the full private H checkpoint, never its filtered wire manifest."""
    import json

    state = _state(db, task.id)
    if not state or not state.enabled:
        return None
    if state.input_submission_id != submission_id or state.pending_submission_id != submission_id:
        _fail("INPUT_REQUIRED", "The checkpoint must belong to this message's fixed input")
    get_snapshot(db, task.id, state.input_snapshot_id)
    path = content.ObjectStore(task.id).root / "snapshots" / (state.input_snapshot_id + ".json")
    if not path.exists():
        return None  # Legacy SHA256-only input still uses a fresh full checkpoint.
    payload = json.loads(path.read_text(encoding="utf-8"))["worktree"]
    if Path(payload["task_root"]).resolve() != Path(task.project_path).resolve() or not payload.get("repositories"):
        _fail("INPUT_REQUIRED", "Full private input checkpoint is unavailable")
    return payload


def _validate_manifest(
    db: Session, task: SddTask, state: CollaborationState, manifest: dict, store: content.ObjectStore | None = None
) -> list[dict]:
    metadata = _check_repositories(db, state, task)
    if (
        manifest["task_id"],
        manifest["repository_set_digest"],
        manifest["session_generation"],
        manifest["session_revision"],
    ) != (
        task.id,
        state.repository_set_digest,
        state.session_generation,
        state.session_revision,
    ):
        _fail("TASK_REPO_BINDING_MISMATCH", "Input manifest identity does not match task binding")
    received = sorted(manifest["repositories"], key=lambda r: r["task_repository_id"])
    if [{key: repo.get(key) for key in metadata[0]} for repo in received] != metadata:
        _fail(
            "REPOSITORY_SET_CHANGED", "Input must contain every task repository with its original branch and baseline"
        )
    store = store or content.ObjectStore(task.id)
    old_repositories = {
        repo["task_repository_id"]: repo for repo in get_snapshot(db, task.id, state.snapshot_id)["repositories"]
    }
    total = 0
    changed_objects = []
    for repo in received:
        seen = set()
        old_files = {entry["path"]: entry for entry in old_repositories[repo["task_repository_id"]]["files"]}
        changed = [entry for entry in repo["files"] if old_files.get(entry["path"]) != entry]
        tracked = (
            content._tracked_modes(
                Path(task.project_path) / repo["rel_path"],
                [entry["path"] for entry in changed] if len(changed) < 500 else None,
            )
            if changed
            else {}
        )
        changed_objects.extend(changed)
        placeholders = (
            content.windows_link_placeholder_paths(Path(task.project_path) / repo["rel_path"])
            if any("120000" in {entry["mode"], old_files.get(entry["path"], {}).get("mode")} for entry in changed)
            else set()
        )
        for entry in repo["files"]:
            folded = entry["path"].casefold()
            if folded in seen:
                _fail("PATH_CONFLICT", "Duplicate or case-colliding input path")
            seen.add(folded)
            total += entry["size"]
            if old_files.get(entry["path"]) == entry:
                continue
            content.validate_path(entry["path"])
            name = Path(entry["path"]).name
            if (name == ".env" or name.startswith(".env.")) and entry["path"] not in tracked:
                _fail("PATH_EXCLUDED", "Untracked environment files cannot be included in collaboration input")
            if "120000" in {entry["mode"], old_files.get(entry["path"], {}).get("mode")} and (
                entry["path"] not in placeholders or entry["mode"] != old_files.get(entry["path"], {}).get("mode")
            ):
                _fail("MODE_UNSUPPORTED", "Git link placeholders cannot be created or converted to another file type")
            if content.os.name == "nt" and entry["mode"] != old_files.get(entry["path"], {}).get("mode", "100644"):
                _fail("MODE_UNSUPPORTED", "Executable mode changes require a server filesystem that supports them")
        repo["files"] = sorted(repo["files"], key=lambda e: e["path"])
        for path in seen:
            if any("/".join(path.split("/")[:count]) in seen for count in range(1, len(path.split("/")))):
                _fail("PATH_CONFLICT", "File and directory input paths overlap")
    if total > content.MAX_MANIFEST_BYTES:
        _fail("SNAPSHOT_TOO_LARGE", "Collaboration snapshot exceeds 512 MiB limit")
    try:
        store.validate_objects(changed_objects)
    except FileNotFoundError:
        _fail("OBJECTS_MISSING", "Input objects have not finished uploading")
    except ValueError as exc:
        _fail("OBJECT_SIZE_MISMATCH", str(exc))
    return received


def handoff(db: Session, task: SddTask, user_id: str, request: HandoffRequest) -> dict:
    from . import delta

    state = _state(db, task.id)
    if not state:
        _fail("COLLABORATION_DISABLED", "Local collaboration is disabled")
    _check_driver(state, user_id, request)
    previous = _operation(db, task.id, request.operation_id, "HANDOFF", request.model_dump())
    if previous:
        return previous
    _check_fence(state, task, user_id, request)
    if request.submission_id:
        from .session import is_cloud_input

        if is_cloud_input(db, task.id, request.submission_id):
            _fail("CLOUD_INPUT_FIXED", "Cloud-only messages do not accept local file uploads")
        if state.sync_phase != "PREPARING" or state.pending_submission_id != request.submission_id:
            _fail("PREPARATION_CHANGED", "Input does not belong to the pending message")
    elif state.sync_phase != "READY":
        _fail("DELIVERY_REQUIRED", "Current code delivery is incomplete")
    _assert_no_writer(db, task.id)
    baseline = get_snapshot(db, task.id, state.snapshot_id)
    manifest = delta.expand(baseline, request.manifest.model_dump())
    store = content.ObjectStore(task.id)
    repositories = _validate_manifest(db, task, state, manifest, store)
    target = {
        **manifest,
        "repositories": repositories,
        "submission_id": request.submission_id,
        "input_cut_seq": request.input_cut_seq,
        "handoff_origin": {
            "actor_user_id": state.driver_user_id,
            "client_id": state.client_id,
            "binding_id": state.binding_id,
            "lease_epoch": state.lease_epoch,
        },
    }
    try:
        content.apply_manifest(Path(task.project_path), baseline, target, store, request.operation_id)
        actual = _capture(db, task, state, "HUMAN_HANDOFF", stable=True)
        if content.digest(actual["repositories"]) != content.digest(repositories):
            _fail("INPUT_CHANGED", "Server input verification did not match captured local input")
        _complete_driver_operation(state, user_id, request)
    except (ValueError, OSError) as exc:
        state.sync_phase = "RECOVERY_REQUIRED"
        state.recovery_kind = "SERVER_INPUT"
        state.recovery_message = str(exc)[:1000]
        state.recovery_operation_id = request.operation_id
        _bump(state)
        # The router commits this failure state before returning the error.
        raise CollaborationError("RECOVERY_REQUIRED", str(exc)) from exc
    _publish(state, actual)
    _record_handoff(db, task, state, baseline, actual, request.operation_id, request.submission_id)
    state.input_snapshot_id = actual["snapshot_id"]
    state.input_submission_id = request.submission_id
    state.input_cut_seq = request.input_cut_seq
    state.reconciled_revision = state.workspace_revision
    state.pending_local_changes_json = []
    state.conflicts_json = []
    return _record(db, task, request.operation_id, "HANDOFF", request.model_dump())


def advance_session(db: Session, task: SddTask, submission_id: str) -> None:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return
    if (
        state.input_submission_id != submission_id
        or state.pending_submission_id != submission_id
        or state.sync_phase != "PREPARING"
    ):
        _fail("INPUT_REQUIRED", "A fixed local input is required before advancing the session")
    generation_matches = state.session_generation == task.session_generation
    initial_generation = state.session_generation == 0 and task.session_generation == 1
    if not (generation_matches or initial_generation) or task.session_revision != state.session_revision + 1:
        _fail("SESSION_CHANGED", "Unexpected task session transition")
    state.session_generation = task.session_generation
    state.session_revision = task.session_revision
    _bump(state)


def authorize_execution(
    db: Session, task: SddTask, submission_id: str, job_id: str, execution_epoch: int = 0
) -> dict | None:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return None
    _check_session(state, task)
    if not input_ready(db, task.id, submission_id):
        _fail("INPUT_REQUIRED", "Execution requires this message's complete local input")
    state.sync_phase = "RUNNING"
    state.run_id = job_id
    state.execution_epoch = execution_epoch
    state.progress_seq = 0
    state.final_progress_seq = None
    state.progress_snapshot_id = None
    state.pending_submission_id = None
    _bump(state)
    return {
        "snapshot_id": state.input_snapshot_id,
        "workspace_revision": state.workspace_revision,
        "repository_set_digest": state.repository_set_digest,
        "input_cut_seq": state.input_cut_seq,
        "binding_id": state.binding_id,
        "lease_epoch": state.lease_epoch,
        "submission_id": submission_id,
    }


def validate_execution(
    db: Session, task: SddTask, job_id: str, *, expected_run_token: str | None = None
) -> dict | None:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return None
    _check_session(state, task)
    _check_repositories(db, state, task)
    if expected_run_token is not None:
        from app.domains.ai.models.ai_job import SddAiJob

        job = db.get(SddAiJob, job_id)
        if not job or job.run_token != expected_run_token:
            _fail("EXECUTION_FENCED", "Execution ownership changed")
        state.execution_epoch = int(job.attempt_count or 0)
    if state.run_id != job_id or state.sync_phase not in {"RUNNING", "WAITING_HITL", "STOPPING"}:
        _fail("EXECUTION_FENCED", "This job is not authorized for the current collaboration input")
    return get_snapshot(db, task.id, state.input_snapshot_id)


def capture_progress(db: Session, task: SddTask, job_id: str, *, expected_run_token: str | None = None) -> dict | None:
    staged = stage_progress(db, task, job_id, expected_run_token=expected_run_token)
    if staged is None:
        return None
    return publish_progress(db, task, job_id, staged, collect_progress(staged), expected_run_token=expected_run_token)


def stage_progress(db: Session, task: SddTask, job_id: str, *, expected_run_token: str | None = None) -> dict | None:
    """Short transaction: capture immutable execution and repository identities."""
    state = _state(db, task.id)
    if not state or not state.enabled:
        return None
    validate_execution(db, task, job_id, expected_run_token=expected_run_token)
    return {
        "task_id": task.id,
        "project_path": task.project_path,
        "repositories": _check_repositories(db, state, task),
        "session_generation": state.session_generation,
        "session_revision": state.session_revision,
        "workspace_revision": state.workspace_revision,
        "repository_set_digest": state.repository_set_digest,
    }


def collect_progress(staged: dict) -> dict:
    """Filesystem work outside a database transaction; candidates are provisional."""
    repositories = _inventory(staged["task_id"], staged["project_path"], staged["repositories"], stable=False)
    return {"repositories": repositories, "content_digest": content.digest(repositories)}


def publish_progress(
    db: Session, task: SddTask, job_id: str, staged: dict, captured: dict, *, expected_run_token: str | None = None
) -> dict | None:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return None
    validate_execution(db, task, job_id, expected_run_token=expected_run_token)
    if any(
        staged[field] != getattr(state, field)
        for field in ("session_generation", "session_revision", "workspace_revision", "repository_set_digest")
    ):
        _fail("EXECUTION_FENCED", "Execution baseline changed while collecting candidate files")
    previous_id = state.progress_snapshot_id or state.input_snapshot_id
    previous_digest = (
        db.query(CollaborationSnapshot.content_digest).filter_by(id=previous_id, task_id=task.id).scalar()
        if previous_id
        else None
    )
    if previous_digest == captured["content_digest"]:
        return None
    state.progress_seq += 1
    candidate = _snapshot(db, task, state, "PROGRESS", captured["repositories"])
    state.progress_snapshot_id = candidate["snapshot_id"]
    _bump(state)
    return candidate


def finish_execution(db: Session, task: SddTask, job_id: str, *, confirmed_stopped: bool) -> dict | None:
    state = _state(db, task.id, nowait=True)
    if not state or not state.enabled:
        return None
    if state.run_id != job_id:
        return None
    if state.run_id == job_id and state.sync_phase in {"DELIVERY_PENDING", "CONFLICT_PENDING", "READY"}:
        return get_state(db, task)
    validate_execution(db, task, job_id)
    if not confirmed_stopped:
        state.sync_phase = "STOPPING"
        _bump(state)
        return get_state(db, task)
    reserved_lease = _reserve_driver_lease(state)
    state.sync_phase = "SETTLING"
    manifest = _capture(db, task, state, "AGENT_OUTPUT", stable=True)
    _renew_reserved_lease(state, reserved_lease)
    state.final_progress_seq = state.progress_seq
    manifest["final_progress_seq"] = state.final_progress_seq
    db.get(CollaborationSnapshot, manifest["snapshot_id"]).manifest_json = dict(manifest)
    _publish(state, manifest)
    state.sync_phase = "DELIVERY_PENDING"
    state.conflicts_json = []
    db.flush()
    return get_state(db, task)


def receipt(db: Session, task: SddTask, user_id: str, request: DeliveryReceipt) -> dict:
    state = _state(db, task.id)
    if not state:
        _fail("COLLABORATION_DISABLED", "Local collaboration is disabled")
    _check_driver(state, user_id, request)
    previous = _operation(db, task.id, request.operation_id, "RECEIPT", request.model_dump())
    if previous:
        return previous
    _check_fence(state, task, user_id, request)
    if state.sync_phase not in {"DELIVERY_PENDING", "CONFLICT_PENDING", "RECOVERY_REQUIRED"}:
        _fail("DELIVERY_NOT_PENDING", "There is no final delivery awaiting reconciliation")
    if state.sync_phase == "RECOVERY_REQUIRED" and state.recovery_kind != "LOCAL_DELIVERY":
        _fail("RECOVERY_REQUIRED", "Server workspace recovery must finish before local delivery can be acknowledged")
    if request.snapshot_id != state.snapshot_id:
        _fail("SNAPSHOT_CHANGED", "Receipt targets an old snapshot")
    metadata = _check_repositories(db, state, task)
    if sorted(r.task_repository_id for r in request.repository_results) != sorted(
        r["task_repository_id"] for r in metadata
    ):
        _fail("REPOSITORY_SET_CHANGED", "Every task repository must have exactly one delivery result")
    valid_ids = {r["task_repository_id"] for r in metadata}
    for entry in [*request.conflicts, *request.pending_local_changes]:
        if entry.get("task_repository_id") not in valid_ids:
            _fail("TASK_REPO_BINDING_MISMATCH", "Delivery evidence refers to an unknown repository")
        content.validate_path(entry.get("path", ""))
    state.conflicts_json = request.conflicts
    state.pending_local_changes_json = request.pending_local_changes
    if any(r.status == "FAILED" for r in request.repository_results):
        state.sync_phase = "RECOVERY_REQUIRED"
        state.recovery_kind = "LOCAL_DELIVERY"
    elif request.conflicts or any(r.status == "CONFLICTS" for r in request.repository_results):
        state.sync_phase = "CONFLICT_PENDING"
    else:
        state.sync_phase = "READY"
        state.recovery_kind = None
        state.recovery_message = None
        state.reconciled_revision = state.workspace_revision
    _bump(state)
    return _record(db, task, request.operation_id, "RECEIPT", request.model_dump())


def disable(db: Session, task: SddTask, user_id: str, request: Fence, operation_id: str) -> dict:
    state = _state(db, task.id)
    if not state:
        return get_state(db, task)
    previous = _operation(db, task.id, operation_id, "DISABLE", request.model_dump())
    if previous and state.driver_user_id == user_id:
        return previous
    _check_fence(state, task, user_id, request)
    if state.sync_phase != "READY":
        _fail("DELIVERY_REQUIRED", "Finish code delivery before disabling collaboration")
    _assert_no_writer(db, task.id)
    state.enabled = False
    state.sync_phase = "OFF"
    state.lease_expires_at = datetime.utcnow()
    state.lease_epoch += 1
    _bump(state)
    return _record(db, task, operation_id, "DISABLE", request.model_dump())


def assert_mutation_allowed(db: Session, task_id: str) -> None:
    state = _state(db, task_id)
    if state and state.enabled:
        _fail("COLLABORATION_COORDINATOR_REQUIRED", "This operation must pass through the collaboration coordinator")


def begin_restore(db: Session, task: SddTask, operation_id: str | None = None) -> bool:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return False
    if state.sync_phase != "READY":
        _fail("DELIVERY_REQUIRED", "Finish current delivery before restoring task history")
    _assert_no_writer(db, task.id)
    state.sync_phase = "SETTLING"
    state.run_id = None
    state.restore_operation_id = operation_id
    state.pending_submission_id = None
    state.input_submission_id = None
    state.progress_snapshot_id = None
    _bump(state)
    return True


def finish_restore(db: Session, task: SddTask) -> dict | None:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return None
    if state.sync_phase != "SETTLING":
        _fail("RESTORE_NOT_PENDING", "A coordinated task restore is not pending")
    state.session_generation = task.session_generation
    state.session_revision = task.session_revision
    state.run_id = None
    reserved_lease = _reserve_driver_lease(state)
    manifest = _capture(db, task, state, "RESTORE", stable=True)
    _renew_reserved_lease(state, reserved_lease)
    _publish(state, manifest)
    state.sync_phase = "DELIVERY_PENDING"
    state.conflicts_json = []
    db.flush()
    return get_state(db, task)


def mark_recovery(db: Session, task_id: str, message: str, *, expected_run_id: str | None = None) -> None:
    state = _state(db, task_id, nowait=expected_run_id is not None)
    if expected_run_id is not None and (
        state is None
        or state.run_id != expected_run_id
        or state.sync_phase not in {"RUNNING", "WAITING_HITL", "STOPPING", "SETTLING"}
    ):
        return
    if state and state.enabled:
        state.sync_phase = "RECOVERY_REQUIRED"
        state.recovery_kind = "SERVER_OUTPUT"
        state.recovery_message = message[:1000]
        _bump(state)


def abandon_input(db: Session, task_id: str, submission_id: str) -> None:
    state = _state(db, task_id)
    if not state or not state.enabled or state.pending_submission_id != submission_id:
        return
    if state.sync_phase != "PREPARING":
        return
    if state.input_submission_id != submission_id:
        for journal in content.ObjectStore(task_id).input_journals(submission_id):
            operation_id = journal.get("operation_id")
            if (
                operation_id
                and not db.query(CollaborationOperation.id)
                .filter_by(task_id=task_id, operation_id=operation_id)
                .first()
            ):
                state.sync_phase = "RECOVERY_REQUIRED"
                state.recovery_kind = "SERVER_INPUT"
                state.recovery_operation_id = operation_id
                state.recovery_message = (
                    "Input installation needs reconciliation before cancellation can release execution"
                )
                _bump(state)
                return
    state.pending_submission_id = None
    state.input_submission_id = None
    state.sync_phase = "READY"
    _bump(state)


def reset_session(db: Session, task: SddTask) -> None:
    state = _state(db, task.id)
    if not state or not state.enabled:
        return
    if state.sync_phase != "READY":
        _fail("DELIVERY_REQUIRED", "Finish code delivery before initializing a new session")
    state.session_generation = task.session_generation
    state.session_revision = task.session_revision
    state.pending_submission_id = None
    state.input_submission_id = None
    state.progress_snapshot_id = None
    state.run_id = None
    state.progress_seq = 0
    state.final_progress_seq = None
    _bump(state)


def cancel_preparation(db: Session, task: SddTask, user_id: str, request: Fence, submission_id: str) -> dict:
    state = _state(db, task.id)
    if not state:
        _fail("COLLABORATION_DISABLED", "Local collaboration is disabled")
    operation_id = getattr(request, "operation_id", None)
    if operation_id:
        _check_driver(state, user_id, request)
        previous = _operation(db, task.id, operation_id, "CANCEL_PREPARATION", request.model_dump())
        if previous:
            return previous
    _check_fence(state, task, user_id, request)
    if state.sync_phase != "PREPARING" or state.pending_submission_id != submission_id:
        _fail("PREPARATION_CHANGED", "The preparation has already changed")
    from app.domains.task.models.chat_submission import TaskChatSubmission

    submission = db.get(TaskChatSubmission, submission_id)
    if not submission or submission.ai_job_id or submission.status != "PREPARING":
        _fail("PREPARATION_CHANGED", "The message is no longer preparing")
    from app.domains.task.services.chat_submission_service import _transition

    _transition(db, submission, "FAILED", error_message="Local code preparation cancelled by the driver")
    abandon_input(db, task.id, submission_id)
    db.flush()
    return (
        _record(db, task, operation_id, "CANCEL_PREPARATION", request.model_dump())
        if operation_id
        else get_state(db, task)
    )


def recover_input(db: Session, task: SddTask, user_id: str, request: Fence, operation_id: str) -> dict:
    state = _state(db, task.id)
    if not state:
        _fail("COLLABORATION_DISABLED", "Local collaboration is disabled")
    _check_fence(state, task, user_id, request)
    if state.sync_phase != "RECOVERY_REQUIRED" or state.recovery_kind != "SERVER_INPUT":
        _fail("RECOVERY_NOT_PENDING", "No server input installation is awaiting recovery")
    _assert_no_writer(db, task.id)
    store = content.ObjectStore(task.id)
    journal = store.read_journal(operation_id)
    if not journal or not journal.get("target"):
        # A failed preflight has not changed any server files. It is safe to
        # release only when a fresh full inventory still equals the baseline.
        baseline = get_snapshot(db, task.id, state.snapshot_id)
        current = _capture(db, task, state, "PROGRESS", stable=True)
        db.delete(db.get(CollaborationSnapshot, current["snapshot_id"]))
        if content.digest(current["repositories"]) != content.digest(baseline["repositories"]):
            _fail(
                "RECOVERY_JOURNAL_MISSING",
                "Server content differs from its baseline and no input journal can repair it",
            )
        state.sync_phase = "PREPARING" if state.pending_submission_id else "READY"
        state.recovery_kind = None
        state.recovery_message = None
        state.recovery_operation_id = None
        _complete_driver_operation(state, user_id, request)
        _bump(state)
        db.flush()
        return get_state(db, task)
    target = journal["target"]
    _validate_manifest(db, task, state, target)
    baseline = get_snapshot(db, task.id, state.snapshot_id)
    content.apply_manifest(Path(task.project_path), baseline, target, store, operation_id, recover=True)
    captured = _capture(db, task, state, "HUMAN_HANDOFF", stable=True)
    if content.digest(captured["repositories"]) != journal["target_digest"]:
        _fail("RECOVERY_REQUIRED", "Recovered server files differ from the fixed input")
    _complete_driver_operation(state, user_id, request)
    _publish(state, captured)
    _record_handoff(
        db, task, state, baseline, captured, operation_id, target.get("submission_id"), target.get("handoff_origin")
    )
    state.input_snapshot_id = captured["snapshot_id"]
    state.input_submission_id = target.get("submission_id")
    state.input_cut_seq = target.get("input_cut_seq")
    state.reconciled_revision = state.workspace_revision
    if state.pending_submission_id:
        from app.domains.task.models.chat_submission import TaskChatSubmission

        submission = db.get(TaskChatSubmission, state.pending_submission_id)
        if not submission or submission.status != "PREPARING":
            state.pending_submission_id = None
    state.sync_phase = "PREPARING" if state.pending_submission_id else "READY"
    state.recovery_kind = None
    state.recovery_message = None
    state.recovery_operation_id = None
    db.flush()
    return get_state(db, task)


def claim_driver(db: Session, task: SddTask, user_id: str, request: EnableRequest) -> dict:
    state = _state(db, task.id)
    if not state or not state.enabled:
        _fail("COLLABORATION_DISABLED", "Enable local collaboration first")
    previous = _operation(db, task.id, request.operation_id, "CLAIM_DRIVER", request.model_dump())
    if previous:
        return previous
    if state.driver_user_id != user_id:
        _fail("DRIVER_REQUIRED", "Only the existing driver user may reconnect this binding")
    if state.lease_expires_at > datetime.utcnow():
        if (state.client_id, state.instance_id) == (request.client_id, request.instance_id):
            state.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)
            return _record(db, task, request.operation_id, "CLAIM_DRIVER", request.model_dump())
        _fail("DRIVER_ACTIVE", "The existing desktop still has an active lease")
    _check_session(state, task)
    _check_repositories(db, state, task)
    from .session import is_cloud_input

    if state.sync_phase == "PREPARING" and not is_cloud_input(db, task.id, state.pending_submission_id):
        from app.domains.task.models.chat_submission import TaskChatSubmission
        from app.domains.task.services.chat_submission_service import _transition

        submission = db.get(TaskChatSubmission, state.pending_submission_id) if state.pending_submission_id else None
        if submission and submission.status == "PREPARING" and not submission.ai_job_id:
            _transition(db, submission, "FAILED", error_message="Desktop driver changed before execution")
        if state.pending_submission_id:
            abandon_input(db, task.id, state.pending_submission_id)
        if state.sync_phase != "RECOVERY_REQUIRED":
            state.pending_submission_id = None
            state.input_submission_id = None
            state.sync_phase = "DELIVERY_PENDING"
    if state.sync_phase in {"READY", "CONFLICT_PENDING"}:
        state.sync_phase = "DELIVERY_PENDING"
    state.client_id = request.client_id
    state.instance_id = request.instance_id
    state.lease_epoch += 1
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=LEASE_SECONDS)
    state.reconciled_revision = 0
    state.conflicts_json = []
    state.pending_local_changes_json = []
    _bump(state)
    return _record(db, task, request.operation_id, "CLAIM_DRIVER", request.model_dump())


def recover_output(db: Session, task: SddTask, user_id: str, request: Fence) -> dict:
    state = _state(db, task.id)
    if not state:
        _fail("COLLABORATION_DISABLED", "Local collaboration is disabled")
    _check_driver(state, user_id, request)
    operation_id = getattr(request, "operation_id", None)
    if operation_id:
        previous = _operation(db, task.id, operation_id, "RECOVER_OUTPUT", request.model_dump())
        if previous:
            return previous
    if state.run_id:
        _check_fence(state, task, user_id, request)
    elif (
        request.expected_state_version,
        request.expected_workspace_revision,
        request.session_generation,
        request.session_revision,
    ) != (
        state.state_version,
        state.workspace_revision,
        state.session_generation,
        state.session_revision,
    ):
        _fail("STATE_VERSION_MISMATCH", "Restore recovery state changed")
    if state.sync_phase != "STOPPING" and not (
        state.sync_phase == "RECOVERY_REQUIRED" and state.recovery_kind == "SERVER_OUTPUT"
    ):
        _fail("RECOVERY_NOT_PENDING", "No final output capture is awaiting recovery")
    _assert_no_writer(db, task.id)
    try:
        if state.run_id:
            from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob

            job = db.query(SddAiJob).filter_by(id=state.run_id, task_id=task.id, channel=AiJobChannel.TASK_CHAT).first()
            if not job or job.status not in {
                AiJobStatus.SUCCESS,
                AiJobStatus.FAILED,
                AiJobStatus.CANCELLED,
                AiJobStatus.INTERRUPTED,
            }:
                _fail("WRITER_ACTIVE", "Server writer termination has not been confirmed")
            state.sync_phase = "RUNNING"
            result = finish_execution(db, task, state.run_id, confirmed_stopped=True)
        else:
            from app.domains.task.models.session_turn import TaskSessionOperation, TaskSessionOperationStatus

            operation = (
                db.query(TaskSessionOperation)
                .filter_by(task_id=task.id, operation_id=state.restore_operation_id)
                .first()
                if state.restore_operation_id
                else None
            )
            if not operation or operation.status != TaskSessionOperationStatus.REVERTED:
                _fail("RESTORE_NOT_VERIFIED", "The exact server history restore has not completed")
            state.sync_phase = "SETTLING"
            result = finish_restore(db, task)
        state.recovery_kind = None
        state.recovery_message = None
        db.flush()
        if operation_id:
            return _record(db, task, operation_id, "RECOVER_OUTPUT", request.model_dump())
        return get_state(db, task) if result else result
    except (ValueError, OSError) as exc:
        mark_recovery(db, task.id, str(exc))
        raise CollaborationError("RECOVERY_REQUIRED", str(exc)) from exc
