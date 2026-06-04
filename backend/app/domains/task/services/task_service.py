"""
任务服务 — CRUD + 启动 / 取消
"""

import os
import shutil
from typing import Optional, List, Tuple
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import case, func as sqlfunc

from app.core.logging import bind_task_context, get_logger
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.log import SddExecutionLog, LogType
from app.domains.dashboard.models.metric import SddDashboardMetric
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, generate_uuid
from app.domains.asset.services import asset_discussion_service, asset_document_service
from app.domains.skill.services import skill_service
from app.domains.task.services import git_worktree_service
from app.domains.skill.services.skill import storage_service as skill_storage_service

logger = get_logger(__name__, category="task_execution")

SUPERPOWERS_DOC_SECTIONS = {"plans", "specs"}
SUPERPOWERS_DOC_ROOT_CANDIDATES = (
    ("docs", "superpowers"),
    ("superpowers", "docs", "superpowers"),
    (),
)
SUPERPOWERS_DOC_EXTENSIONS = {".md", ".markdown"}


def _build_task_project_path(base_path: str, task_id: str, task_name: str) -> str:
    base_abs = os.path.abspath(str(base_path or "").strip() or os.getcwd())
    folder_name = skill_storage_service.build_id_named_folder(
        task_id,
        task_name,
        parent_abs_path=base_abs,
    )
    project_path = os.path.join(base_abs, folder_name)
    if len(project_path) > 500:
        raise ValueError(
            "Task path exceeds database limit (500 chars); "
            "please shorten workspace project path."
        )
    if skill_storage_service.measure_path_length(project_path) > skill_storage_service.os_path_limit():
        raise ValueError(
            "Task path is too long under current workspace root; "
            "please shorten workspace project path."
        )
    return project_path


def create_task_record_for_provision(
    db: Session,
    user: User,
    workspace_id: str,
    name: str,
    description: Optional[str] = None,
    spec_doc_path: Optional[str] = None,
    requirement_duration_hours: float = 0.0,
    skill_ids: Optional[List[str]] = None,
) -> SddTask:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise ValueError("Workspace not found")

    selected_skills = skill_service.validate_task_skill_ids(
        db, workspace_id=workspace_id, skill_ids=skill_ids or []
    )

    task_id = generate_uuid()
    base_path = ws.project_path or os.getcwd()
    task_project_path = _build_task_project_path(base_path, task_id, name)

    task = SddTask(
        id=task_id,
        workspace_id=workspace_id,
        creator_id=user.id,
        name=name,
        description=description,
        project_path=task_project_path,
        git_repo_url=ws.git_repo_url,
        spec_doc_path=spec_doc_path,
        requirement_duration_hours=requirement_duration_hours,
        status=TaskStatus.PENDING,
        current_phase="PREPARING",
        error_message=None,
    )

    try:
        db.add(task)
        db.flush()

        skill_service.bind_task_skills(db, task, selected_skills)
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


def prepare_task_resources_for_provision(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
) -> SddTask:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if not task:
        raise ValueError("Task not found")

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise ValueError("Workspace not found")

    use_git_worktree = git_worktree_service.should_use_git_worktree(ws.project_path, ws.git_repo_url)
    workspace_prepared = False
    with bind_task_context(task_id=task.id, workspace_id=workspace_id, user_id=task.creator_id):
        try:
            if use_git_worktree:
                git_worktree_service.create_task_worktree(
                    repo_path=ws.project_path or "",
                    task_id=task.id,
                    task_project_path=task.project_path,
                    expected_git_repo_url=ws.git_repo_url,
                )
            else:
                if os.path.exists(task.project_path):
                    raise ValueError(f"Task project path already exists: {task.project_path}")
                os.makedirs(task.project_path, exist_ok=False)
            workspace_prepared = True

            if task.skill_links:
                skill_service.materialize_task_skills(db, task.id)

            task.status = TaskStatus.PENDING
            task.current_phase = None
            task.error_message = None
            db.commit()
            db.refresh(task)
            return task
        except Exception:
            db.rollback()
            if workspace_prepared:
                if use_git_worktree:
                    try:
                        git_worktree_service.remove_task_worktree(
                            repo_path=ws.project_path or "",
                            task_id=task.id,
                            task_project_path=task.project_path,
                            expected_git_repo_url=ws.git_repo_url,
                            missing_ok=True,
                        )
                    except Exception as cleanup_exc:
                        logger.warning(f"Failed to cleanup task worktree {task.id}: {cleanup_exc}")
                else:
                    shutil.rmtree(task.project_path, ignore_errors=True)
            raise


def mark_task_prepare_failed(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    error_message: str,
) -> None:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if not task:
        return
    task.status = TaskStatus.FAILED
    task.current_phase = "PREPARE_FAILED"
    task.error_message = str(error_message or "Task preparation failed")
    db.commit()


def create_task(
    db: Session,
    user: User,
    workspace_id: str,
    name: str,
    description: Optional[str] = None,
    spec_doc_path: Optional[str] = None,
    requirement_duration_hours: float = 0.0,
    skill_ids: Optional[List[str]] = None,
) -> SddTask:
    # 从工作区获取默认路径
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise ValueError("Workspace not found")

    selected_skills = skill_service.validate_task_skill_ids(
        db, workspace_id=workspace_id, skill_ids=skill_ids or []
    )

    # 核心：显式生成 ID 以防 SQLAlchemy 延迟加载导致 os.path.join 失败
    task_id = generate_uuid()

    # 获取基础路径，如果工作区没配置则回退到当前目录
    base_path = ws.project_path or os.getcwd()
    task_project_path = _build_task_project_path(base_path, task_id, name)
    use_git_worktree = git_worktree_service.should_use_git_worktree(ws.project_path, ws.git_repo_url)

    task = SddTask(
        id=task_id,
        workspace_id=workspace_id,
        creator_id=user.id,
        name=name,
        description=description,
        project_path=task_project_path,
        git_repo_url=ws.git_repo_url,
        spec_doc_path=spec_doc_path,
        requirement_duration_hours=requirement_duration_hours,
    )

    workspace_prepared = False
    with bind_task_context(task_id=task_id, workspace_id=workspace_id, user_id=user.id):
        try:
            if use_git_worktree:
                git_worktree_service.create_task_worktree(
                    repo_path=ws.project_path or "",
                    task_id=task_id,
                    task_project_path=task.project_path,
                    expected_git_repo_url=ws.git_repo_url,
                )
            else:
                if os.path.exists(task.project_path):
                    raise ValueError(f"Task project path already exists: {task.project_path}")
                os.makedirs(task.project_path, exist_ok=False)
            workspace_prepared = True

            db.add(task)
            db.flush()

            # Bind selected skills to task
            skill_service.bind_task_skills(db, task, selected_skills)
            db.flush()

            # Materialize selected skills immediately after task creation so they exist
            # before any engine/CLI startup.
            if selected_skills:
                try:
                    skill_service.materialize_task_skills(db, task_id)
                except Exception as e:
                    logger.exception(f"Failed to materialize skills for task {task_id}: {e}")
                    raise ValueError("Failed to prepare selected skills for task")

            # 记录需求预估时间指标，用于持久化统计
            task.dashboard_metrics.append(SddDashboardMetric(
                workspace_id=workspace_id,
                metric_type="REQUIREMENT_DURATION",
                metric_value=float(requirement_duration_hours)
            ))

            db.commit()
            db.refresh(task)
            return task
        except Exception:
            db.rollback()
            if workspace_prepared:
                if use_git_worktree:
                    try:
                        git_worktree_service.remove_task_worktree(
                            repo_path=ws.project_path or "",
                            task_id=task_id,
                            task_project_path=task.project_path,
                            expected_git_repo_url=ws.git_repo_url,
                            missing_ok=True,
                        )
                    except Exception as cleanup_exc:
                        logger.warning(f"Failed to cleanup task worktree {task_id}: {cleanup_exc}")
                else:
                    shutil.rmtree(task.project_path, ignore_errors=True)
            raise


def replace_task_skills_for_initialize(
    db: Session,
    task: SddTask,
    *,
    workspace_id: str,
    skill_ids: List[str],
    keep_deleted_runtime_skills: bool = True,
) -> List[str]:
    selected_skills = skill_service.validate_task_skill_ids(
        db,
        workspace_id=workspace_id,
        skill_ids=skill_ids,
    )
    try:
        task.skill_links.clear()
        db.flush()
        skill_service.bind_task_skills(db, task, selected_skills)
        db.flush()
        skill_service.materialize_task_skills(
            db,
            task.id,
            preserve_deleted_runtime_skills=keep_deleted_runtime_skills,
        )
        db.commit()
        db.refresh(task)
        return [skill.id for skill in selected_skills]
    except Exception as exc:
        db.rollback()
        raise ValueError(f"Failed to update task skills: {exc}")


def upload_task_spec(
    db: Session,
    task_id: str,
    file_name: str,
    file_content: bytes,
) -> Tuple[str, str, str]:
    """
    直接将上传的文件写入项目生成目录下的 .sdd 隔离文件夹中
    """
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise ValueError("Task not found")

    # 使用任务关联的 project_path 作为基准
    base_dir = task.project_path
    target_dir = os.path.join(base_dir, ".sdd", "spec")
    
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
    
    file_path = os.path.join(target_dir, file_name)
    
    # 写入文件
    with open(file_path, "wb") as f:
        f.write(file_content)
    
    # 更新数据库中的绝对路径
    task.spec_doc_path = os.path.abspath(file_path)
    asset, version = asset_document_service.create_asset_version_from_upload(
        db,
        task,
        creator_id=task.creator_id,
        file_name=file_name,
        file_content=file_content,
        change_note="Uploaded task specification",
    )
    asset_discussion_service.sync_docx_comments_to_threads(
        db,
        asset=asset,
        version=version,
        actor_user_id=task.creator_id,
    )

    db.commit()
    db.refresh(task)
    db.refresh(asset)
    db.refresh(version)

    return task.spec_doc_path, asset.id, version.id


def _normalize_superpowers_doc_section(section: str) -> str:
    normalized = str(section or "").strip().lower()
    if normalized not in SUPERPOWERS_DOC_SECTIONS:
        raise ValueError("Invalid section. Expected 'plans' or 'specs'")
    return normalized


def _normalize_superpowers_doc_section_path(*, name: Optional[str] = None, path: Optional[str] = None) -> str:
    raw = str(path or "").strip() or str(name or "").strip()
    if not raw:
        raise ValueError("Document path is required")

    normalized = raw.replace("\\", "/").strip("/")
    if not normalized:
        raise ValueError("Document path is invalid")

    segments = normalized.split("/")
    for segment in segments:
        if not segment or segment in {".", ".."}:
            raise ValueError("Document path is invalid")
        if "\x00" in segment:
            raise ValueError("Document path is invalid")

    if Path(segments[-1]).suffix.lower() not in SUPERPOWERS_DOC_EXTENSIONS:
        raise ValueError("Only markdown files (.md/.markdown) are supported")
    return "/".join(segments)


def _task_project_root(task: SddTask) -> Path:
    project_path = str(task.project_path or "").strip()
    if not project_path:
        raise ValueError("Task project path is missing")
    return Path(project_path).resolve()


def _superpowers_docs_root_candidates(task: SddTask) -> List[Path]:
    project_root = _task_project_root(task)
    seen: set[str] = set()
    roots: List[Path] = []
    for rel_parts in SUPERPOWERS_DOC_ROOT_CANDIDATES:
        root = (project_root.joinpath(*rel_parts)).resolve()
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _is_path_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _resolve_superpowers_doc_path(
    task: SddTask,
    section: str,
    *,
    name: Optional[str] = None,
    path: Optional[str] = None,
    for_write: bool = False,
) -> Tuple[Path, str]:
    normalized_section = _normalize_superpowers_doc_section(section)
    normalized_section_path = _normalize_superpowers_doc_section_path(name=name, path=path)
    project_root = _task_project_root(task)

    fallback_candidate: Optional[Path] = None
    existing_parent_candidate: Optional[Path] = None
    existing_section_candidate: Optional[Path] = None

    for root in _superpowers_docs_root_candidates(task):
        section_dir = (root / normalized_section).resolve()
        file_path = (section_dir / normalized_section_path).resolve()
        if not _is_path_within(section_dir, file_path):
            continue
        if not _is_path_within(project_root, file_path):
            continue
        if fallback_candidate is None:
            fallback_candidate = file_path
        if file_path.exists() and file_path.is_file():
            return file_path, normalized_section_path
        if section_dir.exists() and section_dir.is_dir():
            if file_path.parent.exists() and file_path.parent.is_dir() and existing_parent_candidate is None:
                existing_parent_candidate = file_path
            if existing_section_candidate is None:
                existing_section_candidate = file_path

    if for_write:
        if existing_parent_candidate is not None:
            return existing_parent_candidate, normalized_section_path
        if existing_section_candidate is not None:
            return existing_section_candidate, normalized_section_path
        if fallback_candidate is not None:
            return fallback_candidate, normalized_section_path
        raise ValueError("Cannot resolve target path for superpowers document")

    raise FileNotFoundError(f"Superpowers document not found: {normalized_section}/{normalized_section_path}")


def _serialize_superpowers_doc_entry(
    project_root: Path,
    section: str,
    section_root: Path,
    file_path: Path,
) -> dict:
    stat = file_path.stat()
    resolved = file_path.resolve()
    return {
        "section": section,
        "name": resolved.name,
        "section_path": resolved.relative_to(section_root.resolve()).as_posix(),
        "relative_path": resolved.relative_to(project_root).as_posix(),
        "size": int(stat.st_size),
        "updated_at": datetime.fromtimestamp(stat.st_mtime),
    }


def _list_superpowers_docs_in_section(task: SddTask, section: str) -> List[dict]:
    normalized_section = _normalize_superpowers_doc_section(section)
    project_root = _task_project_root(task)
    seen_paths: set[str] = set()
    entries: List[dict] = []
    for root in _superpowers_docs_root_candidates(task):
        section_dir = (root / normalized_section).resolve()
        if not section_dir.exists() or not section_dir.is_dir():
            continue
        if not _is_path_within(project_root, section_dir):
            continue
        for child in sorted(section_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
            if not child.is_file():
                continue
            if child.suffix.lower() not in SUPERPOWERS_DOC_EXTENSIONS:
                continue
            resolved_child = child.resolve()
            if not _is_path_within(project_root, resolved_child):
                continue
            rel = resolved_child.relative_to(project_root).as_posix()
            rel_key = rel.lower()
            if rel_key in seen_paths:
                continue
            seen_paths.add(rel_key)
            entries.append(_serialize_superpowers_doc_entry(
                project_root,
                normalized_section,
                section_dir,
                resolved_child,
            ))

    entries.sort(key=lambda item: item["section_path"].lower())
    return entries


def list_superpowers_docs(task: SddTask) -> dict:
    return {
        "task_id": task.id,
        "root_relative_path": "docs/superpowers",
        "plans": _list_superpowers_docs_in_section(task, "plans"),
        "specs": _list_superpowers_docs_in_section(task, "specs"),
    }


def read_superpowers_doc(
    task: SddTask,
    section: str,
    name: Optional[str] = None,
    path: Optional[str] = None,
) -> dict:
    file_path, section_path = _resolve_superpowers_doc_path(
        task,
        section,
        name=name,
        path=path,
        for_write=False,
    )
    project_root = _task_project_root(task)
    content = file_path.read_text(encoding="utf-8")
    return {
        "task_id": task.id,
        "section": _normalize_superpowers_doc_section(section),
        "name": file_path.name,
        "section_path": section_path,
        "relative_path": file_path.resolve().relative_to(project_root).as_posix(),
        "content": content,
        "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime),
    }


def save_superpowers_doc(
    task: SddTask,
    section: str,
    content: str,
    name: Optional[str] = None,
    path: Optional[str] = None,
) -> dict:
    file_path, section_path = _resolve_superpowers_doc_path(
        task,
        section,
        name=name,
        path=path,
        for_write=True,
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(str(content or ""), encoding="utf-8")
    project_root = _task_project_root(task)

    return {
        "task_id": task.id,
        "section": _normalize_superpowers_doc_section(section),
        "name": file_path.name,
        "section_path": section_path,
        "relative_path": file_path.resolve().relative_to(project_root).as_posix(),
        "content": str(content or ""),
        "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime),
    }


def list_tasks(
    db: Session,
    workspace_id: str,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddTask], int]:
    query = db.query(SddTask).options(joinedload(SddTask.creator)).filter(SddTask.workspace_id == workspace_id)

    if status_filter:
        query = query.filter(SddTask.status == status_filter)

    total = query.count()
    items = (
        query.order_by(SddTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_task(db: Session, task_id: str, workspace_id: str) -> Optional[SddTask]:
    return (
        db.query(SddTask)
        .options(joinedload(SddTask.creator))
        .filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id)
        .first()
    )


def update_task_status(
    db: Session, task: SddTask, status: TaskStatus, error_message: Optional[str] = None
) -> SddTask:
    task.status = status
    if error_message:
        task.error_message = error_message
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task_id: str, workspace_id: str) -> bool:
    task = db.query(SddTask).filter(
        SddTask.id == task_id, SddTask.workspace_id == workspace_id
    ).first()
    if not task:
        return False

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    workspace_project_path = (
        str(workspace.project_path or "").strip()
        if workspace
        else os.path.dirname(os.path.abspath(task.project_path))
    )
    task_remote = str(task.git_repo_url or "").strip()
    if git_worktree_service.should_use_git_worktree(workspace_project_path, task_remote):
        git_worktree_service.remove_task_worktree(
            repo_path=workspace_project_path,
            task_id=task.id,
            task_project_path=task.project_path,
            expected_git_repo_url=task_remote,
            missing_ok=True,
        )

    db.delete(task)
    db.commit()
    return True


def export_task_session(db: Session, task_id: str, workspace_id: str) -> Optional[dict]:
    task = db.query(SddTask).filter(
        SddTask.id == task_id, SddTask.workspace_id == workspace_id
    ).first()
    if not task:
        return None
    
    return {
        "task_name": task.name,
        "description": task.description,
        "status": task.status,
        "project_path": task.project_path,
        "created_at": task.created_at.isoformat(),
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "message_type": msg.message_type,
                "created_at": msg.created_at.isoformat()
            } for msg in task.messages
        ],
        "logs": [
            {
                "log_type": log.log_type,
                "content": log.content,
                "created_at": log.created_at.isoformat()
            } for log in task.execution_logs
        ]
    }


def save_chat_message(
    db: Session,
    task_id: str,
    workspace_id: str,
    creator_id: str,
    role: str,
    content: str,
    message_type: str = "text",
    metadata_json: Optional[dict] = None,
) -> ChatMessage:
    msg = ChatMessage(
        task_id=task_id,
        workspace_id=workspace_id,
        creator_id=creator_id,
        role=role,
        content=content,
        message_type=message_type,
        metadata_json=metadata_json if isinstance(metadata_json, dict) else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_task_history(db: Session, task_id: str, workspace_id: str,
                     page: int = 1, page_size: int = 50) -> dict:
    task = db.query(SddTask).filter(
        SddTask.id == task_id,
        SddTask.workspace_id == workspace_id
    ).first()

    if not task:
        return {"messages": [], "logs": [], "page": page, "page_size": page_size, "total": 0, "has_more": False}

    # 使用数据库查询分页，按 created_at 降序（最新在前）
    from app.domains.task.models.chat import ChatMessage

    total = db.query(ChatMessage).filter(ChatMessage.task_id == task_id).count()

    init_reason_rank = case(
        (ChatMessage.message_type == MessageType.INIT_REASON.value, 0),
        else_=1,
    )

    msg_query = db.query(ChatMessage).filter(
        ChatMessage.task_id == task_id
    ).order_by(
        ChatMessage.created_at.desc(),
        init_reason_rank.desc(),
        ChatMessage.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()

    # 反转回正序（前端渲染需要正序）
    msg_query = list(reversed(msg_query))
    creator_ids = sorted({str(msg.creator_id or "") for msg in msg_query if str(msg.creator_id or "").strip()})
    message_ids = [msg.id for msg in msg_query]
    creators_by_id = {
        user.id: user
        for user in db.query(User).filter(User.id.in_(creator_ids)).all()
    } if creator_ids else {}
    expert_user_ids = {
        member.user_id
        for member in db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id.in_(creator_ids),
            WorkspaceMember.is_expert.is_(True),
        ).all()
    } if creator_ids else set()
    from app.domains.workspace_asset.models.workspace_asset import SddDecision

    decisions_by_message_id = {
        decision.source_chat_message_id: decision.id
        for decision in db.query(SddDecision).filter(
            SddDecision.workspace_id == workspace_id,
            SddDecision.task_id == task_id,
            SddDecision.source_chat_message_id.in_(message_ids),
        ).all()
    } if message_ids else {}

    messages = []
    for msg in msg_query:
        metadata = msg.metadata_json if isinstance(msg.metadata_json, dict) else {}
        messages.append({
            "id": msg.id,
            "role": msg.role.value if hasattr(msg.role, 'value') else msg.role,
            "content": msg.content,
            "type": msg.message_type.value if hasattr(msg.message_type, 'value') else msg.message_type,
            "created_at": msg.created_at.isoformat(),
            "creator_id": msg.creator_id,
            "creator_display_name": creators_by_id[msg.creator_id].display_name if msg.creator_id in creators_by_id else None,
            "creator_is_workspace_expert": msg.creator_id in expert_user_ids,
            "client_message_id": metadata.get("client_message_id"),
            "decision_id": decisions_by_message_id.get(msg.id),
        })

    has_more = (page * page_size) < total

    # logs 保持全量返回（日志量通常不大，且只用于终端面板）
    logs = [
        {
            "id": log.id,
            "type": log.log_type.value if hasattr(log.log_type, 'value') else log.log_type,
            "content": log.content,
            "created_at": log.created_at.isoformat()
        } for log in sorted(task.execution_logs, key=lambda x: x.created_at)
    ]

    return {
        "messages": messages,
        "logs": logs,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": has_more
    }


def clear_task_history(db: Session, task_id: str, workspace_id: str) -> dict:
    """
    Clear chat history and execution logs for a task.
    Old-data compatibility is intentionally not required.
    """
    task = db.query(SddTask).filter(
        SddTask.id == task_id,
        SddTask.workspace_id == workspace_id,
    ).first()
    if not task:
        raise ValueError("Task not found")

    deleted_messages = db.query(ChatMessage).filter(
        ChatMessage.task_id == task_id,
        ChatMessage.workspace_id == workspace_id,
    ).delete(synchronize_session=False)

    deleted_logs = db.query(SddExecutionLog).filter(
        SddExecutionLog.task_id == task_id,
        SddExecutionLog.workspace_id == workspace_id,
    ).delete(synchronize_session=False)

    db.commit()
    return {
        "deleted_chat_messages": int(deleted_messages),
        "deleted_execution_logs": int(deleted_logs),
        "deleted_total": int(deleted_messages + deleted_logs),
    }
