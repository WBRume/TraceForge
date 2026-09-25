"""Personal profile lifecycle and task-bound resource operations."""
from __future__ import annotations
import asyncio
import hashlib
import json
import uuid
from app.domains.local_resource.client import ResourceClient, ResourceError, validate_url, encrypt_credentials, decrypt_credentials, require_enabled
from app.domains.local_resource.models import LocalResource, TaskExecutionBinding, LocalResourceOperation
from app.domains.workspace.services import workspace_service


def is_local(task):
    return getattr(task, "execution_location", "SERVER") == "LOCAL"


def require_member(db, workspace_id, user_id):
    member = workspace_service.get_workspace_member(db, workspace_id, user_id)
    if not member:
        raise ResourceError("No access to this workspace", "RESOURCE_FORBIDDEN", 403)
    return member


def require_operation(db, task, actor_id, operation="execute"):
    if not is_local(task):
        return
    member = require_member(db, task.workspace_id, actor_id)
    allowed = actor_id == task.creator_id or (operation != "generate_patch" and bool(member.is_expert))
    if not allowed:
        raise ResourceError("本地任务仅创建者或专家可操作；生成变更仅限创建者", "LOCAL_TASK_OPERATION_FORBIDDEN", 403)
    require_online(runtime_profile(db, binding(db, task.id)))


def require_online(config):
    """Check both task-bound services before accepting a local operation."""
    try:
        ResourceClient(config, timeout=3).identity()
        asyncio.run(asyncio.wait_for(probe_provider(config), timeout=3))
    except Exception as exc:
        raise ResourceError("本地资源离线或不可用，恢复连接后才能操作", "LOCAL_RESOURCE_OFFLINE", 409) from exc


def profile(row):
    return {key: getattr(row, key) for key in ("id", "workspace_id", "owner_user_id", "backend", "host_id", "profile_revision", "service_url", "resource_service_url", "encrypted_credentials", "workspace_root", "repositories_json")}


def serialize(row):
    result = profile(row)
    result.pop("encrypted_credentials")
    return {**result, "name": row.name, "has_credentials": True, "verification": row.verification_json}


def owned(db, resource_id, user_id, workspace_id=None):
    row = db.get(LocalResource, resource_id)
    if not row or row.owner_user_id != user_id or (workspace_id and row.workspace_id != workspace_id):
        raise ResourceError("Resource not found", "RESOURCE_NOT_FOUND", 404)
    require_member(db, row.workspace_id, user_id)
    return row


def save(db, workspace_id, user_id, data, resource_id=None):
    require_enabled()
    require_member(db, workspace_id, user_id)
    row = owned(db, resource_id, user_id, workspace_id) if resource_id else LocalResource(workspace_id=workspace_id, owner_user_id=user_id)
    credentials = decrypt_credentials(row.encrypted_credentials) if resource_id else {}
    for key in ("host_token", "agent_token", "agent_username"):
        value = getattr(data, key)
        if value is not None:
            credentials[key] = value
    if not credentials.get("host_token"):
        raise ResourceError("请输入同机资源服务配对凭据", "RESOURCE_CREDENTIAL_REQUIRED", 422)
    row.name, row.backend = data.name, data.backend
    row.service_url = validate_url(data.service_url)
    resource_url = validate_url(data.resource_service_url)
    if row.resource_service_url != resource_url:
        row.host_id = None
    row.resource_service_url = resource_url
    row.workspace_root = data.workspace_root
    row.repositories_json = [r.model_dump() for r in data.repositories]
    row.encrypted_credentials = encrypt_credentials(credentials)
    row.profile_revision = (row.profile_revision or 0) + 1
    row.verification_json = None
    db.add(row)
    db.commit()
    try:
        ensure_roots_granted(profile(row))
    except Exception:
        pass
    return row


def ensure_roots_granted(config, workspace_root=None, repo_roots=None):
    """Best-effort grant roots on the resource host via authenticated POST /v1/roots/grant."""
    ws = workspace_root or config.get("workspace_root")
    repos = repo_roots if repo_roots is not None else [
        r.get("local_path") for r in (config.get("repositories_json") or []) if isinstance(r, dict) and r.get("local_path")
    ]
    roots = [r for r in ([ws] + (repos or [])) if r and isinstance(r, str)]
    if not roots:
        return
    try:
        ResourceClient(config).request("POST", "/v1/roots/grant", {"roots": roots})
    except Exception:
        pass


def build_provider(config):
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter
    credentials = decrypt_credentials(config["encrypted_credentials"])
    url = validate_url(config["service_url"])
    if config["backend"] == "opencode":
        return OpenCodeAdapter(url, username=credentials.get("agent_username", "opencode"), password=credentials.get("agent_token", ""))
    if config["backend"] == "dsh":
        return DshServerAdapter(url, browser_token=credentials.get("agent_token", ""), browser_cookie="")
    raise ResourceError("Claude Code CLI 暂不支持本地资源", "LOCAL_BACKEND_UNSUPPORTED", 422)


async def probe_provider(config):
    backend = build_provider(config)
    try:
        return await backend.probe()
    finally:
        client = getattr(backend, "_client", None)
        if client:
            await client.aclose()


def check_connection(db, workspace_id, user_id, data):
    require_enabled()
    require_member(db, workspace_id, user_id)
    credentials = {}
    if data.resource_id:
        row = owned(db, data.resource_id, user_id, workspace_id)
        credentials = decrypt_credentials(row.encrypted_credentials)
    for key in ("host_token", "agent_token", "agent_username"):
        value = getattr(data, key)
        if value is not None:
            credentials[key] = value
    if not credentials.get("host_token"):
        raise ResourceError("请输入同机资源服务配对凭据", "RESOURCE_CREDENTIAL_REQUIRED", 422)
    return verify_connection({
        "backend": data.backend,
        "service_url": validate_url(data.service_url),
        "resource_service_url": validate_url(data.resource_service_url),
        "encrypted_credentials": encrypt_credentials(credentials),
    })


def verify_connection(config):
    from urllib.parse import urlsplit
    if urlsplit(config["service_url"]).hostname != urlsplit(config["resource_service_url"]).hostname:
        raise ResourceError("Agent 和同机资源服务请使用相同的主机地址，不同端口", "RESOURCE_HOST_MISMATCH", 422)
    client = ResourceClient(config)
    identity = client.identity()
    try:
        asyncio.run(probe_provider(config))
    except Exception as exc:
        raise ResourceError("Agent 协议或认证检测失败", "AGENT_UNAVAILABLE") from exc
    return {"ready": True, "host_id": identity["host_id"]}


def verify(config):
    connection = verify_connection(config)
    ensure_roots_granted(config)
    inspection = ResourceClient(config).request("POST", "/v1/repositories/inspect", {"workspace_root": config["workspace_root"], "repositories": config["repositories_json"]})
    return {**connection, **inspection}


def bind_task(db, task, execution):
    require_enabled()
    row = owned(db, execution.resource_id, task.creator_id, task.workspace_id)
    from app.agents.selection import resolve_workspace_backend
    if row.backend != resolve_workspace_backend(db, task.workspace_id):
        raise ResourceError("本地服务与工作区引擎不匹配", "LOCAL_BACKEND_MISMATCH")
    if row.profile_revision != execution.profile_revision:
        raise ResourceError("本地配置已修改，请重新选择", "PROFILE_CHANGED")
    config = profile(row)
    selected = {r.repository_id for r in task.repo_bindings}
    config["repositories_json"] = [r for r in config["repositories_json"] if r["repository_id"] in selected]
    if selected != {r["repository_id"] for r in config["repositories_json"]}:
        raise ResourceError("所选仓库缺少本地映射", "REPOSITORY_MAPPING_REQUIRED")
    # Network and repository checks belong to the background provisioning job.
    # Keep this transaction limited to binding the selected immutable profile.
    task.execution_location, task.local_resource_id = "LOCAL", row.id
    task.agent_backend = row.backend
    task.project_path = None
    db.add(TaskExecutionBinding(task_id=task.id, resource_id=row.id, profile_json=config))


def binding(db, task_id):
    row = db.get(TaskExecutionBinding, task_id)
    if not row:
        raise ResourceError("本地任务缺少执行绑定", "RESOURCE_BINDING_MISSING")
    return row


def runtime_profile(db, binding_row):
    config = dict(binding_row.profile_json)
    require_member(db, config["workspace_id"], config["owner_user_id"])
    current = db.get(LocalResource, binding_row.resource_id)
    if current and current.host_id == config.get("host_id") and current.service_url == config["service_url"] and current.resource_service_url == config["resource_service_url"]:
        # Credentials may rotate on the same host; endpoint/path/provider binding never moves.
        config["encrypted_credentials"] = current.encrypted_credentials
    return config


def task_profile(task_id):
    from app.database import SessionLocal
    with SessionLocal() as db:
        row = db.get(TaskExecutionBinding, task_id)
        if not row:
            from app.domains.task.models.task import SddTask
            task = db.get(SddTask, task_id)
            if task and is_local(task):
                raise ResourceError("本地执行绑定缺失，不能退回服务器执行", "RESOURCE_BINDING_MISSING")
        if not row:
            return None
        return runtime_profile(db, row)


def provider_for_task(task_id):
    config = task_profile(task_id)
    return build_provider(config) if config else None


def execute(db, task, kind, payload, operation_id=None):
    row = binding(db, task.id)
    return ResourceClient(runtime_profile(db, row)).operation(task.id, kind, payload, operation_id)


def provision_task(db, task):
    row = binding(db, task.id)
    config = runtime_profile(db, row)
    verification = verify_connection(config)
    ensure_roots_granted(config)
    row.profile_json = {**row.profile_json, "host_id": verification["host_id"]}
    db.flush()
    # provision validates every repository before fetching/creating its worktree;
    # avoid a duplicate repositories/inspect pass on the request path.
    mappings = {r["repository_id"]: r for r in row.profile_json["repositories_json"]}
    repos = [{**mappings[r.repository_id], "repo_url": r.repo_url, "repo_name": r.repo_name,
              "rel_path": r.rel_path, "branch_name": r.branch_name} for r in task.repo_bindings]
    receipt = execute(db, task, "provision", {"workspace_root": row.profile_json["workspace_root"], "repositories": repos}, "provision-" + task.id)
    row.receipt_json = receipt
    from app.domains.task.models.task_repository import TaskRepositoryState
    for repo in task.repo_bindings:
        actual = next(r for r in receipt["repositories"] if r["repository_id"] == repo.repository_id)
        repo.base_commit_sha, repo.state = actual["base_commit_sha"], TaskRepositoryState.READY
    db.flush()
    return receipt


def local_path(db, task):
    receipt = binding(db, task.id).receipt_json or {}
    if not receipt.get("task_root"):
        raise ResourceError("本地目录尚未准备完成", "RESOURCE_NOT_PROVISIONED")
    return receipt["task_root"]


def remote_patches(db, task):
    from app.domains.task.services.git_patch_service import RepoPatchSnapshot, PatchFileChange
    result = execute(db, task, "generate_patch", {})
    snapshots = []
    for item in result["repositories"]:
        digest = item.pop("sha256")
        if hashlib.sha256(item["patch_text"].encode()).hexdigest() != digest:
            raise ResourceError("补丁上传摘要不一致", "PATCH_HASH_MISMATCH")
        item["files"] = [PatchFileChange(**file) for file in item["files"]]
        snapshots.append(RepoPatchSnapshot(**item))
    return snapshots


def task_operation(task_id, kind, payload):
    config = task_profile(task_id)
    if not config:
        raise ResourceError("本地执行绑定不存在", "RESOURCE_BINDING_MISSING")
    return ResourceClient(config).operation(task_id, kind, payload)


def materialize_file(task, relative, content):
    import base64
    from sqlalchemy.orm import object_session
    db = object_session(task)
    payload = {"files": [{"path": relative, "content": base64.b64encode(content).decode(), "sha256": hashlib.sha256(content).hexdigest()}]}
    result = execute(db, task, "materialize", payload) if db is not None else task_operation(task.id, "materialize", payload)
    return result["paths"][0]


def release_or_defer(db, task):
    config = dict(binding(db, task.id).profile_json)
    operation_id = "release-" + task.id
    operation = db.get(LocalResourceOperation, operation_id)
    if not operation:
        operation = LocalResourceOperation(id=operation_id, task_id=task.id, kind="release",
            payload_hash=hashlib.sha256(b"{}").hexdigest(), binding_json=config, state="PENDING")
        db.add(operation)
    try:
        operation.result_json = ResourceClient(config).operation(task.id, "release", {}, operation_id)
        operation.state = "SUCCEEDED"
    except ResourceError as exc:
        operation.state = "PENDING"
        operation.result_json = {"code": exc.code, "message": str(exc)}
    # Caller deletes the task and commits this cleanup tombstone atomically.


def reconcile_cleanup(db, resource):
    rows = db.query(LocalResourceOperation).filter_by(kind="release", state="PENDING").all()
    for operation in rows:
        config = operation.binding_json or {}
        if config.get("id") != resource.id:
            continue
        try:
            operation.result_json = ResourceClient(config).operation(operation.task_id, "release", {}, operation.id)
            operation.state = "SUCCEEDED"
        except ResourceError as exc:
            operation.result_json = {"code": exc.code, "message": str(exc)}
    db.commit()
