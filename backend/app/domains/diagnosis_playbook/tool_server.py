"""Run-scoped Streamable HTTP MCP tools, authorized by revocable dispatch tickets.

The token grants proposal submission to exactly one active scope, not task/user
API access. Calls cannot submit receipts, choose executables, or change gates.
"""
from copy import deepcopy
import hashlib
import hmac
import time
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from app.core.offload import run_db_txn
from .models import PlaybookRun
from .contracts import PlaybookError, digest
from . import service

router = APIRouter(prefix="/playbook-tools", tags=["Playbook scoped tools"])

HYPOTHESIS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["hypotheses"], "properties": {
    "hypotheses": {"type": "array", "minItems": 2, "maxItems": 3, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "claim", "predictions", "falsifiers", "discriminator_script"],
        "properties": {"id": {"type": "string", "pattern": "^[a-z0-9_]+$"}, "claim": {"type": "string", "minLength": 1},
                       "predictions": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                       "falsifiers": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                       "discriminator_script": {"type": "string", "minLength": 1}}}}}}

TOOLS = [{"name": "propose_hypotheses", "description": "提交二至三个可证伪假说与候选判别脚本。此工具不会标记验证通过。", "inputSchema": HYPOTHESIS_SCHEMA},
         {"name": "propose_experiment", "description": "提交候选实验文件；由平台校验、冻结并执行。", "inputSchema": {
             "type": "object", "additionalProperties": False, "required": ["files"], "properties": {
                 "files": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "string"}}}}}]
TOOLS.extend([
    {"name": "propose_patch", "description": "提交补丁候选文件，平台在回合静止后物化到独立补丁快照。", "inputSchema": TOOLS[1]["inputSchema"]},
    {"name": "read_source", "description": "读取绑定源码快照内的文件或列出目录；不允许读取凭据和证据存储。", "inputSchema": {
        "type": "object", "additionalProperties": False, "required": ["path"], "properties": {"path": {"type": "string"}}}},
])


class RpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str = Field(max_length=100)
    params: dict = Field(default_factory=dict)


def authorize(db, run_id, authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Dispatch ticket required")
    token = authorization[7:]
    run = db.get(PlaybookRun, run_id)
    scope = (run.data_json.get("active_scope") or {}) if run else {}
    supplied = hashlib.sha256(token.encode()).hexdigest()
    if not run or not hmac.compare_digest(str(scope.get("ticket_hash", "")), supplied):
        raise HTTPException(401, "Invalid dispatch ticket")
    if scope.get("expires_at", 0) <= time.time() or scope.get("run_epoch") != run.epoch or run.state != "AGENT_RUNNING" or run.data_json["cancel_requested"]:
        raise HTTPException(409, "Dispatch ticket revoked")
    from app.domains.task.models.task import SddTask
    task = db.get(SddTask, run.task_id)
    if task.session_generation != run.data_json["session_generation"] or task.session_revision != run.data_json["session_revision"]:
        raise HTTPException(409, "Task session changed")
    return run, scope


def invoke(db, run_id, authorization, request):
    run, scope = authorize(db, run_id, authorization)
    if request.method == "initialize":
        return {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "traceforge-playbook", "version": "1"}}
    if request.method == "ping":
        return {}
    if request.method == "tools/list":
        return {"tools": [t for t in TOOLS if (t["name"] != "propose_hypotheses" or (run.phase == "HYPOTHESIZE" and not scope.get("hypothesis_id"))) and (t["name"] != "propose_patch" or run.phase == "PATCH")]}
    if request.method != "tools/call":
        raise PlaybookError("MCP_METHOD_UNSUPPORTED")
    name, arguments = request.params.get("name"), request.params.get("arguments", {})
    if name == "read_source":
        from pathlib import Path
        from .compiler import require, safe_relative
        require(isinstance(arguments, dict) and set(arguments) == {"path"}, "INVALID_SOURCE_PATH")
        relative = arguments["path"]
        require(isinstance(relative, str) and (relative == "." or safe_relative(relative)), "INVALID_SOURCE_PATH")
        def secret_path(parts):
            return any(p.lower().startswith(".env") or p.lower() in {".git", ".ssh", ".aws", "credentials"} for p in parts)
        require(not secret_path(Path(relative).parts), "SOURCE_SECRET_PATH_DENIED")
        binding = "patch" if run.phase == "PATCH" else "source"
        root = Path(run.data_json["environment"]["bindings"][binding]).resolve(strict=True)
        try:
            path = (root / relative).resolve(strict=True)
        except OSError as exc:
            raise PlaybookError("SOURCE_FILE_UNAVAILABLE") from exc
        require(path.is_relative_to(root), "SOURCE_PATH_ESCAPE")
        require(not secret_path(path.relative_to(root).parts), "SOURCE_SECRET_PATH_DENIED")
        if path.is_dir():
            text = "\n".join(sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir() if not p.name.startswith("."))[:200])
        else:
            require(path.stat().st_size <= 128_000, "SOURCE_FILE_TOO_LARGE")
            text = path.read_text(encoding="utf-8", errors="replace")
        return {"content": [{"type": "text", "text": text}], "isError": False}
    return submit_proposal(db, run, scope, name, arguments, str(request.id))


def submit_proposal(db, run, scope, name, arguments, call_key):
    """Shared validation for authenticated MCP and internal advisory results."""
    fingerprint = digest({"name": name, "arguments": arguments})
    calls = scope.get("tool_calls", {})
    if call_key in calls:
        if calls[call_key] != fingerprint:
            raise PlaybookError("TOOL_CALL_ID_CONFLICT", status=409)
        return {"content": [{"type": "text", "text": "Proposal already recorded"}], "isError": False}
    if name == "propose_hypotheses":
        if scope.get("hypothesis_id"):
            raise PlaybookError("BRANCH_CANNOT_REPLACE_HYPOTHESES")
        if not isinstance(arguments, dict) or set(arguments) != {"hypotheses"}:
            raise PlaybookError("INVALID_HYPOTHESES")
        service.propose_hypotheses(db, run, arguments["hypotheses"], run.state_version)
    elif name in {"propose_experiment", "propose_patch"}:
        from .compiler import safe_relative, require
        require(isinstance(arguments, dict) and set(arguments) == {"files"}, "INVALID_EXPERIMENT")
        files = arguments["files"]
        require(isinstance(files, dict) and 0 < len(files) <= 32 and all(isinstance(k, str) and safe_relative(k) and isinstance(v, str) for k, v in files.items()), "INVALID_EXPERIMENT_FILES")
        require(sum(len(v.encode()) for v in files.values()) <= 1_000_000, "EXPERIMENT_TOO_LARGE")
        require(name != "propose_patch" or run.phase == "PATCH", "PATCH_STAGE_REQUIRED")
        data = deepcopy(run.data_json)
        candidate = {"files": files, "candidate_digest": digest(files), "run_epoch": run.epoch, "step_id": run.active_step}
        if scope.get("hypothesis_id"):
            data.setdefault("branch_experiments", {})[scope["hypothesis_id"]] = candidate
        else:
            data["patch_candidate" if name == "propose_patch" else "experiment_candidate"] = candidate
        service.transition(db, run, data)
    else:
        raise PlaybookError("TOOL_NOT_ALLOWED")
    data = deepcopy(run.data_json)
    data["active_scope"]["tool_calls"] = {**calls, call_key: fingerprint}
    service.transition(db, run, data)
    return {"content": [{"type": "text", "text": "Proposal recorded; physical verification is still required"}], "isError": False}


@router.post("/{run_id}")
async def mcp(run_id: str, body: RpcRequest, authorization: str | None = Header(default=None)):
    if body.jsonrpc != "2.0":
        raise HTTPException(400, "JSON-RPC 2.0 required")
    if body.id is None:
        await run_db_txn(lambda db: authorize(db, run_id, authorization))
        return Response(status_code=202)
    try:
        result = await run_db_txn(lambda db: invoke(db, run_id, authorization, body))
        return {"jsonrpc": "2.0", "id": body.id, "result": result}
    except PlaybookError as exc:
        return {"jsonrpc": "2.0", "id": body.id, "result": {"isError": True, "content": [{"type": "text", "text": str(exc)}]}}
