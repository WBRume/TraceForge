"""Validate a provisioning request and persist the pending task with its bindings."""

import os
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.auth.models.user import User, Workspace, generate_uuid
from app.domains.dashboard.models.metric import SddDashboardMetric
from app.domains.skill.services.packages import storage as skill_storage_service
from app.domains.skill.services.runtime import bindings as skill_runtime_bindings
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services.task_workspace import repositories as task_task_workspace_repositories
from app.domains.workspace_asset.models.workspace_asset import SddRequirement, SddTaskRequirement

logger = get_logger(__name__, category="task_execution")


def _build_task_project_path(base_path: str, task_id: str, task_name: str) -> str:
    base_abs = os.path.abspath(str(base_path or "").strip() or os.getcwd())
    folder_name = skill_storage_service.build_id_named_folder(
        task_id,
        task_name,
        parent_abs_path=base_abs,
    )
    project_path = os.path.join(base_abs, folder_name)
    if len(project_path) > 500:
        raise ValueError("Task path exceeds database limit (500 chars); please shorten workspace project path.")
    if skill_storage_service.measure_path_length(project_path) > skill_storage_service.os_path_limit():
        raise ValueError("Task path is too long under current workspace root; please shorten workspace project path.")
    return project_path


def _diagnosis_task_metadata(phenomenon, priority, sop_auto_run, description):
    phenomenon_text = str(phenomenon or "").strip()
    if not phenomenon_text:
        raise ValueError("phenomenon is required for DIAGNOSIS task")
    task_meta = {}
    task_meta["phenomenon"] = phenomenon_text
    priority_text = str(priority or "").strip().upper()
    if priority_text in {"P0", "P1", "P2", "P3"}:
        task_meta["priority"] = priority_text
    # 主开关：自动执行全流程（SOP 会话以此初始化 auto_run）
    if sop_auto_run:
        task_meta["sop_auto_run"] = True
    # 诊断任务：现象即初始化描述，避免描述为空（前端不再单独填写描述）
    if not str(description or "").strip() and phenomenon_text:
        description = phenomenon_text
    return task_meta, description


def create_task_record_for_provision(
    db: Session,
    user: User,
    workspace_id: str,
    name: str,
    description: str | None = None,
    spec_doc_path: str | None = None,
    requirement_duration_hours: float = 0.0,
    skill_ids: list[str] | None = None,
    task_type: str = "DEVELOPMENT",
    phenomenon: str | None = None,
    priority: str | None = None,
    sop_auto_run: bool = False,
    repository_branches: list[dict[str, str]] | None = None,
    repository_ids: list[str] | None = None,
    diagnosis_playbook_spec_id: str | None = None,
    execution=None,
    agent_model=None,
    requirement_id: str | None = None,
) -> SddTask:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise ValueError("Workspace not found")

    requirement = None
    if requirement_id:
        if task_type == "DIAGNOSIS":
            raise ValueError("Diagnosis tasks may link a Requirement when completed, not during creation")
        requirement = (
            db.query(SddRequirement)
            .filter(
                SddRequirement.id == requirement_id,
                SddRequirement.workspace_id == workspace_id,
            )
            .first()
        )
        if not requirement:
            raise ValueError("Requirement not found in this workspace")
        if db.query(SddRequirement.id).filter(SddRequirement.parent_requirement_id == requirement.id).first():
            raise ValueError("Parent Requirement has child Requirements; create Task for a child Requirement")

    selected_skills = skill_runtime_bindings.validate_task_skill_ids(
        db, workspace_id=workspace_id, skill_ids=skill_ids or []
    )

    task_id = generate_uuid()
    base_path = ws.project_path or os.getcwd()
    task_project_path = _build_task_project_path(base_path, task_id, name)

    task_meta = None
    if task_type == "DIAGNOSIS":
        task_meta, description = _diagnosis_task_metadata(phenomenon, priority, sop_auto_run, description)

    if diagnosis_playbook_spec_id:
        # 诊断规程仅问题定位任务可选，研发态任务不允许绑定
        if task_type != "DIAGNOSIS":
            raise ValueError("diagnosis playbook selection requires a DIAGNOSIS task")
        from app.domains.diagnosis_playbook.analysis_guide import task_binding

        task_meta = {
            **(task_meta or {}),
            "diagnosis_playbook_guide": task_binding(db, workspace_id, diagnosis_playbook_spec_id),
        }

    task = SddTask(
        id=task_id,
        workspace_id=workspace_id,
        creator_id=user.id,
        task_type=task_type,
        task_meta_json=task_meta,
        name=name,
        description=description,
        project_path=task_project_path,
        git_repo_url=ws.git_repo_url,
        spec_doc_path=spec_doc_path,
        requirement_duration_hours=requirement_duration_hours,
        # 创建即进入准备态：git worktree/clone 未完成前禁止启动任务会话
        status=TaskStatus.PROVISIONING,
        current_phase="PREPARING",
        error_message=None,
    )

    try:
        if agent_model is not None:
            from app.agents.model_selection import apply_task_selection

            apply_task_selection(db, task, agent_model)
        db.add(task)
        db.flush()

        if requirement:
            from app.domains.workspace_asset.models.workspace_asset import RequirementAuditAction
            from app.domains.workspace_asset.services.requirements.presenters import add_requirement_audit

            db.add(
                SddTaskRequirement(
                    workspace_id=workspace_id,
                    requirement_id=requirement.id,
                    task_id=task.id,
                    created_by_id=user.id,
                )
            )
            requirement.updated_at = datetime.utcnow()
            add_requirement_audit(
                db,
                workspace_id=workspace_id,
                requirement_id=requirement.id,
                task_id=task.id,
                actor_id=user.id,
                action=RequirementAuditAction.LINKED_TASK,
                after={"task_id": task.id, "relation_type": "RELATES_TO"},
                source_metadata={"created_from": "task_create"},
            )

        # Multi-repository workspace: snapshot the workspace repo set onto the task.
        branch_overrides = {
            str(item.get("repository_id") or "").strip(): str(item.get("branch_name") or "").strip()
            for item in (repository_branches or [])
            if isinstance(item, dict) and str(item.get("repository_id") or "").strip()
        }
        selected_repo_ids = (
            [str(repo_id or "").strip() for repo_id in repository_ids if str(repo_id or "").strip()]
            if repository_ids is not None
            else None
        )
        task_task_workspace_repositories.snapshot_workspace_repositories_into_task(
            db,
            ws,
            task,
            branch_overrides=branch_overrides,
            selected_ids=selected_repo_ids,
        )
        db.flush()

        if execution and execution.location == "LOCAL":
            from app.domains.local_resource.service import bind_task

            bind_task(db, task, execution)

        skill_runtime_bindings.bind_task_skills(db, task, selected_skills)
        db.flush()

        task.dashboard_metrics.append(
            SddDashboardMetric(
                workspace_id=workspace_id,
                metric_type="REQUIREMENT_DURATION",
                metric_value=float(requirement_duration_hours),
            )
        )

        db.commit()
        db.refresh(task)
        return task
    except Exception:
        db.rollback()
        raise
