"""Model catalogue resolved against the actual execution resource."""
import asyncio
import httpx

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.errors import AgentError
from app.agents.model_selection import model_option, task_selection
from app.agents.selection import create_agent_backend_by_name, normalize_backend_name, resolve_workspace_backend
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, Workspace
from app.domains.local_resource import service as resources
from app.domains.local_resource.client import ResourceError
from app.domains.task.models.context_token import SddContextTokenSnapshot
from .deps import get_db_bind, get_task_or_404, run_route_db_txn, verify_workspace_access

router = APIRouter(prefix="/workspaces/{ws_id}", tags=["Tasks"])


def catalogue_context(db, ws_id, user_id, task_id=None, resource_id=None):
    verify_workspace_access(ws_id, user_id, db)
    task = get_task_or_404(db, task_id, ws_id) if task_id else None
    backend = (normalize_backend_name(task.agent_backend) if task else None) or resolve_workspace_backend(db, ws_id)
    ws = db.get(Workspace, ws_id)
    # OpenCode catalogues are location-scoped. Use the same workspace location
    # for creation and chat; the session supplies only the selected model.
    path = (ws.project_path if backend == "opencode" or not task else task.project_path) or ""
    config = None
    if task and resources.is_local(task):
        config = resources.runtime_profile(db, resources.binding(db, task.id))
        path = config["workspace_root"] if backend == "opencode" else (
            (resources.binding(db, task.id).receipt_json or {}).get("task_root") or config["workspace_root"])
    elif resource_id and not task:
        config = resources.profile(resources.owned(db, resource_id, user_id, ws_id))
        if config["backend"] != backend:
            raise HTTPException(409, "本地服务与工作区引擎不匹配")
        path = config["workspace_root"]
    selected = task_selection(task) if task else None
    observed = None
    if task and task.session_id:
        snapshot = db.query(SddContextTokenSnapshot).filter(
            SddContextTokenSnapshot.task_id == task.id,
            SddContextTokenSnapshot.session_id == task.session_id,
            SddContextTokenSnapshot.model.isnot(None),
        ).order_by(SddContextTokenSnapshot.created_at.desc()).first()
        observed = snapshot.model if snapshot else None
    return dict(backend=backend, config=config, path=path, selected=selected,
                observed=observed, session_id=task.session_id if task else None)


@router.get("/agent-models")
async def get_agent_models(ws_id: str, task_id: str | None = None, resource_id: str | None = None,
                           current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        context = await run_route_db_txn(db, get_db_bind(db), lambda session: catalogue_context(
            session, ws_id, str(current_user.id), task_id, resource_id))
        db.close()
        backend = await asyncio.to_thread(resources.build_provider, context["config"]) if context["config"] else create_agent_backend_by_name(context["backend"])
        error = None
        try:
            catalog = await asyncio.wait_for(backend.model_catalog(
                project_path=context["path"], session_id=context["session_id"]), timeout=12)
        except (AgentError, asyncio.TimeoutError, httpx.HTTPError, OSError, ValueError, KeyError):
            # An unavailable catalogue must not erase a persisted task model.
            catalog = {"options": []}
            error = "无法读取 Agent 模型列表，请检查引擎连接与模型配置后重试"
        finally:
            # Discovery owns only an HTTP client, never a running session/process.
            client = getattr(backend, "_client", None)
            if client:
                await client.aclose()
        selected = context["selected"] or {}
        current = (selected.get("model") if selected.get("backend") == context["backend"] else None) or context["observed"] or catalog.get("default_model")
        options = catalog["options"]
        if current and current not in {item["value"] for item in options}:
            options.insert(0, model_option(current))
        return {"backend": context["backend"], "options": options, "current_model": current, "error": error}
    except ResourceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except (AgentError, asyncio.TimeoutError, httpx.HTTPError, OSError, ValueError, KeyError) as exc:
        raise HTTPException(502, "无法读取 Agent 模型列表，请检查引擎连接与模型配置后重试") from exc
