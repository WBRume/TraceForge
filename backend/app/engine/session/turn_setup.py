"""回合准备：任务工作目录、技能物化、运行时技能索引、env 注入与请求构建。

全部为无状态函数：DB 卸载（run_db / run_git_job）由引擎编排层驱动，
本模块只提供线程内执行的同步闭包与纯构建函数。
"""

from typing import Any, Callable, Dict, List, Optional

from app.agents import AgentAttemptContext, AgentRunRequest
from app.config import settings
from app.core.logging import get_logger
from app.database import SessionLocal
from app.domains.auth.services import auth_service
from app.domains.skill.services import skill_runtime_trace_service, skill_service
from app.domains.task.models.task import SddTask

logger = get_logger(__name__, category="task_execution")


def resolve_project_path_sync(task_id: str) -> str:
    """线程内执行：解析任务的工作目录（CLI cwd）。"""
    from app.domains.task.services import task_service

    db = SessionLocal()
    try:
        task = db.query(SddTask).filter(SddTask.id == task_id).first()
        if not task:
            return "."
        return task_service.resolve_task_cli_dir(db, task)
    finally:
        db.close()


def materialize_task_skills_sync(task_id: str) -> None:
    """线程内执行（run_git_job）：把任务装配的技能物化到工作目录。"""
    db = SessionLocal()
    try:
        skill_service.materialize_task_skills(db, task_id)
    finally:
        db.close()


def build_runtime_skill_index_sync(task_id: str) -> List[Any]:
    """线程内执行：构建技能运行时追踪索引（失败降级为空索引）。"""
    db = SessionLocal()
    try:
        task = db.query(SddTask).filter(SddTask.id == task_id).first()
        if not task:
            return []
        return skill_runtime_trace_service.build_runtime_skill_index(db, task)
    except Exception as exc:
        logger.warning(f"Build runtime skill trace index failed: {exc}")
        return []
    finally:
        db.close()


def build_env_overrides(
    *,
    ws_id: str,
    task_id: str,
    user_id: str,
    job_id: Optional[str],
    attempt: Optional[AgentAttemptContext],
) -> Dict[str, str]:
    """构建注入 agent 进程的环境变量（平台 API、mock 端点与 attempt 身份）。"""
    api_base_url = str(settings.PLATFORM_API_BASE_URL or "http://localhost:8000").strip().rstrip("/")
    if not api_base_url:
        api_base_url = "http://localhost:8000"

    access_token = auth_service.create_access_token(user_id)
    mock_base_url = f"{api_base_url}/mock/{ws_id}/{task_id}"
    env = {
        "API_BASE_URL": api_base_url,
        "ACCESS_TOKEN": access_token,
        "WORKSPACE_ID": ws_id,
        "TASK_ID": task_id,
        "USER_ID": user_id,
        "AI_JOB_ID": job_id or "",
        "MOCK_BASE_URL": mock_base_url,
        "API_MOCK_BASE_URL": mock_base_url,
        "API_MOCK_CONTEXT_URL": f"{api_base_url}/api/workspaces/{ws_id}/api-mock/projects/{task_id}/context",
    }
    if attempt is not None:
        env.update(
            {
                "TRACEFORGE_RUN_TOKEN": attempt.run_token,
                "WORKER_BOOT_ID": attempt.worker_boot_id,
            }
        )
    return env


def build_agent_run_request(
    *,
    backend: Any,
    prompt: str,
    project_path: str,
    session_id: Optional[str],
    env_overrides: Dict[str, str],
    task_id: str,
    ws_id: str,
    user_id: str,
    job_id: Optional[str],
    attempt: Optional[AgentAttemptContext],
    on_process_started: Callable[[Any, Optional[AgentAttemptContext]], Any],
) -> AgentRunRequest:
    """按全局超时配置与 backend capability 声明构建统一运行请求。"""
    return AgentRunRequest(
        run_id=f"{task_id}-{job_id or 'turn'}",
        prompt=prompt,
        project_path=project_path,
        session_id=session_id,
        env=env_overrides,
        # 显式执行类别（doc §7 数据流）：与 backend capability
        # 声明一致，不得通过"是否有本地 PID"推断。
        execution_kind=getattr(
            getattr(backend, "capabilities", None),
            "execution_kind",
            "LOCAL_PROCESS",
        ) or "LOCAL_PROCESS",
        timeout_seconds=float(
            getattr(settings, "AGENT_MAX_RUNTIME_SECONDS", 7200) or 7200
        ),
        startup_timeout_seconds=float(
            getattr(settings, "AGENT_STARTUP_TIMEOUT_SECONDS", 60) or 60
        ),
        idle_timeout_seconds=float(
            getattr(settings, "AGENT_IDLE_TIMEOUT_SECONDS", 600) or 600
        ),
        # Supervisor-side attach timeout (real DB attach); the
        # engine watchdog stays a secondary outer guard only.
        process_attach_timeout_seconds=float(
            getattr(settings, "AGENT_PROCESS_ATTACH_TIMEOUT_SECONDS", 45) or 0
        ) or None,
        metadata={
            "task_id": task_id,
            "workspace_id": ws_id,
            "user_id": user_id,
            "ai_job_id": job_id or "",
            "run_token": attempt.run_token if attempt else None,
            "worker_id": attempt.worker_id if attempt else None,
            "worker_boot_id": attempt.worker_boot_id if attempt else None,
            "attempt_count": attempt.attempt_count if attempt else None,
        },
        on_process_started=on_process_started,
    )
