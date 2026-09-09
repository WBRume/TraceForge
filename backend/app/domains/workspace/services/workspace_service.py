"""
Workspace service.
"""

import json
import os
import re
import secrets
import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspacePermission,
    WorkspaceRole,
)
from app.domains.management.models.management import (
    SddManagementProject,
    SddManagementProjectProduct,
)
from app.domains.task.services import git_worktree_service


PERMISSION_FIELD_MAP: Dict[WorkspacePermission, str] = {
    WorkspacePermission.CREATE_TASK: "create_task",
    WorkspacePermission.START_TASK: "start_task",
    WorkspacePermission.MANAGE_TASK_STATUS: "manage_task_status",
    WorkspacePermission.DELETE_TASK: "delete_task",
    WorkspacePermission.UPLOAD_TASK_SPEC: "upload_task_spec",
    WorkspacePermission.MANAGE_SKILLS: "manage_skills",
    WorkspacePermission.MANAGE_MEMBERS: "manage_members",
    WorkspacePermission.VIEW_DASHBOARD: "view_dashboard",
    WorkspacePermission.VIEW_ASSETS: "view_assets",
    WorkspacePermission.MANAGE_REQUIREMENTS: "manage_requirements",
    WorkspacePermission.EXPORT_TASK: "export_task",
    WorkspacePermission.VIEW_API_MOCK: "view_api_mock",
    WorkspacePermission.MANAGE_API_MOCK: "manage_api_mock",
    WorkspacePermission.PUBLISH_API_MOCK: "publish_api_mock",
}

ALL_PERMISSIONS: Set[WorkspacePermission] = set(PERMISSION_FIELD_MAP.keys())

DEFAULT_ROLE_PERMISSIONS: Dict[WorkspaceRole, Set[WorkspacePermission]] = {
    WorkspaceRole.OWNER: ALL_PERMISSIONS,
    WorkspaceRole.DEVELOPER: {
        WorkspacePermission.CREATE_TASK,
        WorkspacePermission.START_TASK,
        WorkspacePermission.MANAGE_TASK_STATUS,
        WorkspacePermission.DELETE_TASK,
        WorkspacePermission.UPLOAD_TASK_SPEC,
        WorkspacePermission.MANAGE_SKILLS,
        WorkspacePermission.VIEW_DASHBOARD,
        WorkspacePermission.VIEW_ASSETS,
        WorkspacePermission.EXPORT_TASK,
        WorkspacePermission.VIEW_API_MOCK,
        WorkspacePermission.MANAGE_API_MOCK,
    },
    WorkspaceRole.VIEWER: {
        WorkspacePermission.VIEW_DASHBOARD,
        WorkspacePermission.VIEW_ASSETS,
        WorkspacePermission.VIEW_API_MOCK,
    },
}


def _normalize_role(role: WorkspaceRole | str) -> WorkspaceRole:
    if isinstance(role, WorkspaceRole):
        return role
    return WorkspaceRole(role)


def _permission_set_to_json(permissions: Set[WorkspacePermission]) -> str:
    values = sorted(p.value for p in permissions)
    return json.dumps(values, ensure_ascii=True)


def _permission_set_from_json(raw: Optional[str], role: WorkspaceRole) -> Set[WorkspacePermission]:
    if role == WorkspaceRole.OWNER:
        return set(ALL_PERMISSIONS)

    if not raw:
        return set(DEFAULT_ROLE_PERMISSIONS[role])

    try:
        values = json.loads(raw)
    except Exception:
        return set(DEFAULT_ROLE_PERMISSIONS[role])

    if not isinstance(values, list):
        return set(DEFAULT_ROLE_PERMISSIONS[role])

    parsed: Set[WorkspacePermission] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            parsed.add(WorkspacePermission(value))
        except ValueError:
            continue

    if not parsed:
        return set(DEFAULT_ROLE_PERMISSIONS[role])

    return parsed


def _flags_to_permission_set(flags: Dict[str, bool], role: WorkspaceRole) -> Set[WorkspacePermission]:
    if role == WorkspaceRole.OWNER:
        return set(ALL_PERMISSIONS)

    permissions: Set[WorkspacePermission] = set()
    for permission, field in PERMISSION_FIELD_MAP.items():
        if bool(flags.get(field, False)):
            permissions.add(permission)
    return permissions


def default_permissions_for_role(role: WorkspaceRole | str) -> Set[WorkspacePermission]:
    normalized = _normalize_role(role)
    return set(DEFAULT_ROLE_PERMISSIONS[normalized])


def permissions_to_flags(permissions: Set[WorkspacePermission]) -> Dict[str, bool]:
    return {
        field: permission in permissions
        for permission, field in PERMISSION_FIELD_MAP.items()
    }


def get_workspace_member(db: Session, workspace_id: str, user_id: str) -> Optional[WorkspaceMember]:
    return (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )


def is_workspace_expert(db: Session, workspace_id: str, user_id: str) -> bool:
    member = get_workspace_member(db, workspace_id, user_id)
    if not member:
        return False
    return bool(member.is_expert)


def list_user_expert_workspace_ids(db: Session, user_id: str) -> List[str]:
    rows = (
        db.query(WorkspaceMember.workspace_id)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.is_expert.is_(True),
        )
        .all()
    )
    return [row[0] for row in rows]


def is_user_expert_in_any_workspace(db: Session, user_id: str) -> bool:
    return len(list_user_expert_workspace_ids(db, user_id)) > 0


def get_workspace_and_member(db: Session, workspace_id: str, user_id: str) -> Optional[Tuple[Workspace, WorkspaceMember]]:
    member = get_workspace_member(db, workspace_id, user_id)
    if not member:
        return None

    workspace = (
        db.query(Workspace)
        .options(
            joinedload(Workspace.owner),
            joinedload(Workspace.project)
            .joinedload(SddManagementProject.products)
            .joinedload(SddManagementProjectProduct.product),
            joinedload(Workspace.repositories),
        )
        .filter(Workspace.id == workspace_id)
        .first()
    )
    if not workspace:
        return None

    return workspace, member


def get_user_role(db: Session, workspace_id: str, user_id: str) -> Optional[WorkspaceRole]:
    member = get_workspace_member(db, workspace_id, user_id)
    return member.role if member else None


def get_user_permissions(db: Session, workspace_id: str, user_id: str) -> Set[WorkspacePermission]:
    member = get_workspace_member(db, workspace_id, user_id)
    if not member:
        return set()
    return _permission_set_from_json(member.permissions_json, member.role)


def user_has_permission(
    db: Session,
    workspace_id: str,
    user_id: str,
    permission: WorkspacePermission | str,
) -> bool:
    normalized = permission if isinstance(permission, WorkspacePermission) else WorkspacePermission(permission)
    return normalized in get_user_permissions(db, workspace_id, user_id)


def can_delete_workspace(db: Session, workspace_id: str, user_id: str) -> bool:
    role = get_user_role(db, workspace_id, user_id)
    return role == WorkspaceRole.OWNER


def serialize_workspace_repository(row) -> Dict[str, object]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "repository_id": row.repository_id,
        "repo_url": row.repo_url,
        "repo_name": row.repo_name,
        "repo_slug": row.repo_slug,
        "branch_name": row.branch_name,
        "ref_type": row.ref_type,
        "base_dir": row.base_dir,
        "state": row.state.value if hasattr(row.state, "value") else str(row.state),
        "base_commit_sha": row.base_commit_sha,
        "error_message": row.error_message,
        "created_at": row.created_at,
    }


def serialize_workspace_owner(owner) -> Optional[Dict[str, object]]:
    if owner is None:
        return None
    return {
        "id": owner.id,
        "display_name": owner.display_name,
        "email": owner.email,
        "avatar_svg": owner.avatar_svg,
        "avatar_url": owner.avatar_url,
    }


def serialize_workspace_project(project) -> Optional[Dict[str, object]]:
    if project is None:
        return None
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
    }


def serialize_workspace_products(project) -> List[Dict[str, object]]:
    if project is None:
        return []
    products = []
    for link in project.products or []:
        product = link.product
        if product is None:
            continue
        products.append(
            {
                "id": product.id,
                "name": product.name,
                "code": product.code,
                "version_no": product.version_no,
            }
        )
    return products


def serialize_workspace(workspace: Workspace, member: WorkspaceMember) -> Dict[str, object]:
    repositories = [serialize_workspace_repository(row) for row in workspace.repositories]
    project = workspace.project
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "project_path": workspace.project_path,
        "git_repo_url": workspace.git_repo_url,
        "project_id": workspace.project_id,
        "owner_id": workspace.owner_id,
        "agent_backend": workspace.agent_backend,
        "custom_project_name": workspace.custom_project_name,
        "custom_product_name": workspace.custom_product_name,
        "created_at": workspace.created_at,
        "my_role": member.role.value if hasattr(member.role, "value") else str(member.role),
        "my_is_expert": bool(member.is_expert),
        "can_delete_workspace": member.role == WorkspaceRole.OWNER,
        "project": serialize_workspace_project(project),
        "products": serialize_workspace_products(project),
        "owner": serialize_workspace_owner(workspace.owner),
        "repositories": repositories,
    }


def _normalize_optional(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def slugify_workspace_dir_name(name: str) -> str:
    """将工作区名称转换为文件系统安全的目录名；无法转换时回退为 workspace。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "-", str(name or "")).strip()
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-. ")
    return cleaned or "workspace"


def _is_path_within(path: str, base: str) -> bool:
    """判断 path 是否位于 base 之内（允许等于 base）。

    使用 normcase 兼容 Windows 大小写不敏感的路径比较；
    跨盘符等无法求公共前缀的情形一律视为不在 base 内。
    """
    try:
        path_abs = os.path.normcase(os.path.abspath(os.path.expanduser(str(path or ""))))
        base_abs = os.path.normcase(os.path.abspath(os.path.expanduser(str(base or ""))))
        if not base_abs:
            return True
        return os.path.commonpath([path_abs, base_abs]) == base_abs
    except ValueError:
        return False


def apply_workspace_root_dir_policy(
    db: Session,
    name: str,
    project_path: Optional[str],
) -> Optional[str]:
    """应用“工作区根目录”系统配置项。

    - 配置为空：保持原有逻辑，直接返回调用方传入的路径；
    - 配置非空：路径默认回退为 根目录/workspace/工作区名称，
      且传入路径仅允许位于 根目录/workspace 之内。
    """
    from app.domains.system_config.services import system_config_service

    root_dir = system_config_service.get_config_str(
        db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR
    )
    if not root_dir:
        return project_path
    workspace_base = os.path.join(root_dir, system_config_service.WORKSPACE_BASE_SEGMENT)
    if not project_path:
        return os.path.join(workspace_base, slugify_workspace_dir_name(name))
    if not _is_path_within(project_path, workspace_base):
        raise git_worktree_service.GitWorktreeError(
            f"project_path must be located under the workspace base directory: {workspace_base}",
            status_code=400,
        )
    return project_path


def preflight_workspace_conflicts(
    db: Session,
    name: Optional[str] = None,
    project_path: Optional[str] = None,
) -> Dict[str, Any]:
    """创建工作区前的冲突预检（仅供参考，不阻断创建）。

    - 工作区重名：已存在同名工作区；
    - 目录被引用：目标目录与已有工作区目录重叠（相同或互为父子目录）。
    """
    normalized_name = str(name or "").strip()
    normalized_path = _normalize_optional(project_path)

    name_rows: List[Workspace] = []
    if normalized_name:
        # 全局校验（不限当前用户）：防止用户 B 创建与用户 A 已建工作区同名的场景；
        # 名称按大小写不敏感比较，保证 MySQL（ci 排序规则）与 SQLite 行为一致。
        name_rows = (
            db.query(Workspace)
            .filter(func.lower(Workspace.name) == normalized_name.lower())
            .all()
        )

    path_rows: List[Workspace] = []
    if normalized_path:
        candidates = (
            db.query(Workspace)
            .options(joinedload(Workspace.owner))
            .filter(Workspace.project_path.isnot(None))
            .all()
        )
        for row in candidates:
            other = str(row.project_path or "").strip()
            if not other:
                continue
            if _is_path_within(normalized_path, other) or _is_path_within(other, normalized_path):
                path_rows.append(row)

    def _brief(row: Workspace, with_path: bool = False) -> Dict[str, str]:
        owner = row.owner
        owner_name = ""
        if owner is not None:
            owner_name = str(
                getattr(owner, "display_name", "") or getattr(owner, "email", "") or ""
            )
        info: Dict[str, str] = {
            "id": row.id,
            "name": row.name,
            "owner_name": owner_name,
        }
        if with_path:
            info["project_path"] = str(row.project_path or "")
        return info

    return {
        "name_conflict": bool(name_rows),
        "name_conflict_workspaces": [_brief(row) for row in name_rows],
        "path_conflict": bool(path_rows),
        "path_conflict_workspaces": [_brief(row, with_path=True) for row in path_rows],
    }


def create_workspace(
    db: Session,
    user: User,
    name: str,
    description: Optional[str] = None,
    project_path: Optional[str] = None,
    git_repo_url: Optional[str] = None,
    project_id: Optional[str] = None,
    product_ids: Optional[List[str]] = None,
    repositories: Optional[List[Dict[str, str]]] = None,
    project_name: Optional[str] = None,
    product_name: Optional[str] = None,
) -> Workspace:
    if product_ids and len(product_ids) > 1:
        raise ValueError("workspace can only select one product")
    from app.domains.management.services import project_service
    from app.domains.management.services import repository_service as mgmt_repository_service
    from app.domains.management.models.management import SddManagementRepository
    from app.domains.workspace.models.workspace_repository import (
        SddWorkspaceRepository,
        WorkspaceRepositoryState,
    )

    normalized_project_path = _normalize_optional(project_path)
    normalized_git_repo_url = _normalize_optional(git_repo_url)
    normalized_project_name = _normalize_optional(project_name)
    normalized_product_name = _normalize_optional(product_name)

    # 工作区根目录配置项：为空保持原有逻辑；非空时填充默认路径并限制在 根目录/workspace 之内
    normalized_project_path = apply_workspace_root_dir_policy(
        db, name, normalized_project_path
    )

    def _slugify_unique(slug: str, seen: set) -> str:
        candidate = slug
        sequence = 1
        while candidate in seen:
            candidate = f"{slug}-{sequence}"
            sequence += 1
        seen.add(candidate)
        return candidate

    if not project_id and repositories:
        # 独立多仓库模式：未关联管理项目，手动指定项目/产品名称，并逐仓选择分支。
        if not normalized_project_path:
            raise git_worktree_service.GitWorktreeError(
                "project_path is required when repositories are provided",
                status_code=400,
            )
        if not normalized_project_name or not normalized_product_name:
            raise git_worktree_service.GitWorktreeError(
                "project_name and product_name are required when repositories are provided",
                status_code=400,
            )

        repo_rows = (
            db.query(SddManagementRepository)
            .filter(
                SddManagementRepository.id.in_(
                    [str(item.get("repository_id") or "").strip() for item in repositories]
                )
            )
            .all()
        )
        repos_by_id = {row.id: row for row in repo_rows}
        seen_slugs: set = set()
        workspace = Workspace(
            name=name,
            description=description,
            project_path=normalized_project_path,
            git_repo_url=None,
            project_id=None,
            custom_project_name=normalized_project_name,
            custom_product_name=normalized_product_name,
            owner_id=user.id,
        )
        db.add(workspace)
        db.flush()
        for item in repositories:
            repo_id = str(item.get("repository_id") or "").strip()
            repo_row = repos_by_id.get(repo_id)
            if repo_row is None:
                raise ValueError(f"Repository not found: {repo_id}")
            branch_name = str(item.get("branch_name") or "").strip() or str(
                repo_row.default_branch or "main"
            ).strip()
            slug = mgmt_repository_service.build_repo_slug(repo_row.name)
            candidate = _slugify_unique(slug, seen_slugs)
            base_dir = os.path.join(normalized_project_path or "", candidate)
            db.add(
                SddWorkspaceRepository(
                    workspace_id=workspace.id,
                    repository_id=repo_row.id,
                    repo_url=repo_row.git_url,
                    repo_name=repo_row.name,
                    repo_slug=candidate,
                    branch_name=branch_name,
                    ref_type="BRANCH",
                    base_dir=base_dir,
                    state=WorkspaceRepositoryState.PENDING,
                )
            )
    elif project_id:
        # Multi-repository layout: the workspace references a management project
        # and its repository set is materialized by the provision job.
        project = (
            db.query(SddManagementProject)
            .filter(SddManagementProject.id == project_id)
            .first()
            )
        if not project:
            raise ValueError("Project not found")
        if not normalized_project_path:
            raise git_worktree_service.GitWorktreeError(
                "project_path is required when project_id is provided",
                status_code=400,
            )

        workspace = Workspace(
            name=name,
            description=description,
            project_path=normalized_project_path,
            git_repo_url=None,
            project_id=project.id,
            owner_id=user.id,
        )
        db.add(workspace)
        db.flush()

        repo_set = project_service.resolve_project_repo_set(
            db, project, product_ids=product_ids or None
        )
        if repositories is not None:
            selected_ids = {
                str(item.get("repository_id") or "").strip()
                for item in repositories
                if str(item.get("repository_id") or "").strip()
            }
            available_ids = {
                str(item["repository_id"]) for item in repo_set
            }
            unknown = selected_ids - available_ids
            if unknown:
                raise ValueError(
                    "Selected repositories are not part of the project repository set: "
                    + ", ".join(sorted(unknown))
                )
            repo_set = [
                item for item in repo_set
                if str(item["repository_id"]) in selected_ids
            ]
        seen_slugs: set = set()
        for item in repo_set:
            slug = mgmt_repository_service.build_repo_slug(item["repository_name"])
            candidate = slug
            sequence = 1
            while candidate in seen_slugs:
                candidate = f"{slug}-{sequence}"
                sequence += 1
            seen_slugs.add(candidate)
            base_dir = os.path.join(normalized_project_path or "", candidate)
            db.add(
                SddWorkspaceRepository(
                    workspace_id=workspace.id,
                    repository_id=item["repository_id"],
                    repo_url=item["git_url"],
                    repo_name=item["repository_name"],
                    repo_slug=candidate,
                    branch_name=str(item.get("branch_name") or item.get("ref_name") or "").strip(),
                    ref_type=str(item.get("ref_type") or "BRANCH").strip().upper(),
                    base_dir=base_dir,
                    state=WorkspaceRepositoryState.PENDING,
                )
            )
    else:
        if normalized_git_repo_url and not normalized_project_path:
            raise git_worktree_service.GitWorktreeError(
                "project_path is required when git_repo_url is provided",
                status_code=400,
            )

        if git_worktree_service.should_use_git_worktree(normalized_project_path, normalized_git_repo_url):
            git_worktree_service.clone_workspace_repository(
                normalized_project_path or "",
                normalized_git_repo_url or "",
            )
        elif normalized_project_path and not normalized_git_repo_url:
            try:
                git_worktree_service.init_git_repository(normalized_project_path)
            except git_worktree_service.GitWorktreeError as exc:
                raise git_worktree_service.GitWorktreeError(
                    f"Failed to initialize git repository in {normalized_project_path}: {exc}",
                    status_code=exc.status_code,
                ) from exc

        workspace = Workspace(
            name=name,
            description=description,
            project_path=normalized_project_path,
            git_repo_url=normalized_git_repo_url,
            custom_project_name=normalized_project_name,
            custom_product_name=normalized_product_name,
            owner_id=user.id,
        )
        db.add(workspace)
        db.flush()

    owner_permissions = default_permissions_for_role(WorkspaceRole.OWNER)
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
        permissions_json=_permission_set_to_json(owner_permissions),
        is_expert=True,
    )
    db.add(member)
    try:
        db.commit()
        db.refresh(workspace)
    except Exception:
        db.rollback()
        raise
    return workspace


def list_user_workspaces(db: Session, user: User) -> List[Workspace]:
    member_rows = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    ws_ids = [m.workspace_id for m in member_rows]
    if not ws_ids:
        return []
    return db.query(Workspace).filter(Workspace.id.in_(ws_ids)).all()


def list_user_workspace_summaries(db: Session, user: User) -> List[Dict[str, object]]:
    member_rows = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id)
        .all()
    )
    if not member_rows:
        return []

    by_workspace = {m.workspace_id: m for m in member_rows}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.id.in_(list(by_workspace.keys())))
        .options(
            joinedload(Workspace.owner),
            joinedload(Workspace.project)
            .joinedload(SddManagementProject.products)
            .joinedload(SddManagementProjectProduct.product),
            joinedload(Workspace.repositories),
        )
        .order_by(Workspace.created_at.desc())
        .all()
    )

    return [serialize_workspace(workspace, by_workspace[workspace.id]) for workspace in workspaces]


def get_workspace(db: Session, workspace_id: str, user: User) -> Optional[Workspace]:
    member = get_workspace_member(db, workspace_id, user.id)
    if not member:
        return None
    return db.query(Workspace).filter(Workspace.id == workspace_id).first()


def get_workspace_summary(db: Session, workspace_id: str, user: User) -> Optional[Dict[str, object]]:
    pair = get_workspace_and_member(db, workspace_id, user.id)
    if not pair:
        return None
    workspace, member = pair
    return serialize_workspace(workspace, member)


def add_member(
    db: Session,
    workspace_id: str,
    user_email: str,
    role: str,
    permissions_flags: Optional[Dict[str, bool]] = None,
    is_expert: bool = False,
) -> WorkspaceMember:
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise ValueError("User not found")

    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    if existing:
        raise ValueError("User is already a workspace member")

    normalized_role = _normalize_role(role)
    if normalized_role == WorkspaceRole.OWNER:
        raise ValueError("Cannot add another owner")

    if permissions_flags is None:
        permissions = default_permissions_for_role(normalized_role)
    else:
        permissions = _flags_to_permission_set(permissions_flags, normalized_role)

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=user.id,
        role=normalized_role,
        permissions_json=_permission_set_to_json(permissions),
        is_expert=bool(is_expert),
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def list_workspace_members(db: Session, workspace_id: str) -> List[WorkspaceMember]:
    return (
        db.query(WorkspaceMember)
        .options(joinedload(WorkspaceMember.user))
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.joined_at.asc())
        .all()
    )


def list_workspace_members_paginated(
    db: Session,
    workspace_id: str,
    page: int,
    page_size: int,
    keyword: Optional[str] = None,
) -> Tuple[Optional[WorkspaceMember], List[WorkspaceMember], int]:
    owner_member = (
        db.query(WorkspaceMember)
        .options(joinedload(WorkspaceMember.user))
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
        .order_by(WorkspaceMember.joined_at.asc())
        .first()
    )

    query = (
        db.query(WorkspaceMember)
        .options(joinedload(WorkspaceMember.user))
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role != WorkspaceRole.OWNER,
        )
    )

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        fuzzy_pattern = f"%{normalized_keyword}%"
        query = (
            query
            .join(User, WorkspaceMember.user_id == User.id)
            .filter(
                or_(
                    User.display_name.ilike(fuzzy_pattern),
                    User.email.ilike(fuzzy_pattern),
                )
            )
        )

    total = query.count()
    offset = max(page - 1, 0) * page_size
    items = (
        query
        .order_by(WorkspaceMember.joined_at.asc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return owner_member, items, total


def get_workspace_member_by_id(db: Session, workspace_id: str, member_id: str) -> Optional[WorkspaceMember]:
    return (
        db.query(WorkspaceMember)
        .options(joinedload(WorkspaceMember.user))
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.id == member_id,
        )
        .first()
    )


def update_member(
    db: Session,
    workspace_id: str,
    member_id: str,
    role: Optional[str] = None,
    permissions_flags: Optional[Dict[str, bool]] = None,
    is_expert: Optional[bool] = None,
) -> WorkspaceMember:
    member = get_workspace_member_by_id(db, workspace_id, member_id)
    if not member:
        raise ValueError("Member not found")

    if member.role == WorkspaceRole.OWNER and (role is not None or permissions_flags is not None):
        raise PermissionError("Owner membership cannot be modified")

    role_changed = False
    if role is not None:
        normalized_role = _normalize_role(role)
        if normalized_role == WorkspaceRole.OWNER:
            raise ValueError("Cannot promote to owner")
        if member.role != normalized_role:
            member.role = normalized_role
            role_changed = True

    if permissions_flags is not None:
        permissions = _flags_to_permission_set(permissions_flags, member.role)
        member.permissions_json = _permission_set_to_json(permissions)
    elif role_changed:
        member.permissions_json = _permission_set_to_json(default_permissions_for_role(member.role))

    if is_expert is not None:
        member.is_expert = bool(is_expert)

    db.commit()
    db.refresh(member)
    return member


def remove_member(db: Session, workspace_id: str, member_id: str, operator_user_id: str) -> None:
    member = get_workspace_member_by_id(db, workspace_id, member_id)
    if not member:
        raise ValueError("Member not found")

    if member.role == WorkspaceRole.OWNER:
        raise PermissionError("Owner cannot be removed")

    if member.user_id == operator_user_id:
        raise PermissionError("You cannot remove yourself")

    db.delete(member)
    db.commit()


def member_to_response(member: WorkspaceMember) -> Dict[str, object]:
    permissions = _permission_set_from_json(member.permissions_json, member.role)
    return {
        "id": member.id,
        "workspace_id": member.workspace_id,
        "user_id": member.user_id,
        "email": member.user.email if member.user else "",
        "display_name": member.user.display_name if member.user else "",
        "avatar_url": member.user.avatar_url if member.user else None,
        "avatar_svg": member.user.avatar_svg if member.user else None,
        "role": member.role.value if hasattr(member.role, "value") else str(member.role),
        "joined_at": member.joined_at,
        "permissions": permissions_to_flags(permissions),
        "is_owner": member.role == WorkspaceRole.OWNER,
        "is_expert": bool(member.is_expert),
    }


def get_user_permission_payload(db: Session, workspace_id: str, user_id: str) -> Optional[Dict[str, object]]:
    member = get_workspace_member(db, workspace_id, user_id)
    if not member:
        return None

    permissions = _permission_set_from_json(member.permissions_json, member.role)
    return {
        "workspace_id": workspace_id,
        "role": member.role.value if hasattr(member.role, "value") else str(member.role),
        "permissions": permissions_to_flags(permissions),
        "is_expert": bool(member.is_expert),
        "can_delete_workspace": member.role == WorkspaceRole.OWNER,
    }


def delete_workspace(db: Session, workspace_id: str) -> bool:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        return False

    original_project_path = str(ws.project_path or "").strip()
    configured_remote = str(ws.git_repo_url or "").strip()
    archived_path: Optional[str] = None

    if git_worktree_service.should_use_git_worktree(original_project_path, configured_remote):
        archived_path = git_worktree_service.archive_workspace_repository(
            workspace_id=workspace_id,
            project_path=original_project_path,
            expected_git_repo_url=configured_remote,
        )

    try:
        db.delete(ws)
        db.commit()
    except Exception as exc:
        db.rollback()
        if archived_path and original_project_path:
            try:
                git_worktree_service.restore_archived_workspace(
                    archive_path=archived_path,
                    original_project_path=original_project_path,
                )
            except Exception as rollback_exc:
                raise RuntimeError(
                    "Workspace archived but database deletion failed and rollback failed. "
                    f"archive_path={archived_path}"
                ) from rollback_exc
        raise RuntimeError("Workspace deletion failed after archive migration") from exc
    return True


# ---------------------------------------------------------------------------
# 链接邀请（Invite Links）
# ---------------------------------------------------------------------------

INVITE_LINK_TOKEN_BYTES = 24
DEFAULT_INVITE_VALID_DAYS = 7

INVITE_STATUS_ACTIVE = "ACTIVE"
INVITE_STATUS_EXPIRED = "EXPIRED"
INVITE_STATUS_REVOKED = "REVOKED"
INVITE_STATUS_EXHAUSTED = "EXHAUSTED"


def _utcnow() -> datetime.datetime:
    """DateTime 列存 naive UTC（与 server_default=now() 的 UTC 语义保持一致）。"""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def create_invite_link(
    db: Session,
    workspace_id: str,
    creator_user_id: str,
    role: str,
    permissions_flags: Optional[Dict[str, bool]] = None,
    is_expert: bool = False,
    valid_days: Optional[int] = None,
    max_uses: Optional[int] = None,
) -> "WorkspaceInviteLink":
    from app.domains.workspace.models.invite_link import TOKEN_LENGTH, WorkspaceInviteLink

    normalized_role = _normalize_role(role)
    if normalized_role == WorkspaceRole.OWNER:
        raise ValueError("Invite links cannot grant the owner role")
    if valid_days is not None and valid_days <= 0:
        raise ValueError("valid_days must be positive")
    if max_uses is not None and max_uses <= 0:
        raise ValueError("max_uses must be positive")

    if permissions_flags is None:
        permissions = default_permissions_for_role(normalized_role)
    else:
        permissions = _flags_to_permission_set(permissions_flags, normalized_role)

    expires_at = None
    if valid_days is not None:
        expires_at = _utcnow() + datetime.timedelta(days=valid_days)

    link = WorkspaceInviteLink(
        workspace_id=workspace_id,
        token=secrets.token_hex(TOKEN_LENGTH // 2),
        role=normalized_role,
        permissions_json=_permission_set_to_json(permissions),
        is_expert=bool(is_expert),
        max_uses=max_uses,
        expires_at=expires_at,
        created_by=creator_user_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def get_invite_link(db: Session, workspace_id: str, link_id: str) -> Optional["WorkspaceInviteLink"]:
    from app.domains.workspace.models.invite_link import WorkspaceInviteLink

    return (
        db.query(WorkspaceInviteLink)
        .filter(
            WorkspaceInviteLink.id == link_id,
            WorkspaceInviteLink.workspace_id == workspace_id,
        )
        .first()
    )


def list_invite_links(db: Session, workspace_id: str) -> List["WorkspaceInviteLink"]:
    from app.domains.workspace.models.invite_link import WorkspaceInviteLink

    return (
        db.query(WorkspaceInviteLink)
        .filter(WorkspaceInviteLink.workspace_id == workspace_id)
        .order_by(WorkspaceInviteLink.created_at.desc(), WorkspaceInviteLink.id.desc())
        .all()
    )


def revoke_invite_link(db: Session, workspace_id: str, link_id: str) -> Optional["WorkspaceInviteLink"]:
    link = get_invite_link(db, workspace_id, link_id)
    if not link:
        return None
    if not link.revoked_at:
        link.revoked_at = _utcnow()
        db.commit()
        db.refresh(link)
    return link


def invite_link_status(link: "WorkspaceInviteLink", now: Optional[datetime.datetime] = None) -> str:
    current = now or _utcnow()
    if link.revoked_at:
        return INVITE_STATUS_REVOKED
    if link.expires_at is not None and link.expires_at <= current:
        return INVITE_STATUS_EXPIRED
    if link.max_uses is not None and link.used_count >= link.max_uses:
        return INVITE_STATUS_EXHAUSTED
    return INVITE_STATUS_ACTIVE


def serialize_invite_link(link: "WorkspaceInviteLink") -> Dict[str, object]:
    status = invite_link_status(link)
    remaining_uses = None
    if link.max_uses is not None:
        remaining_uses = max(0, link.max_uses - link.used_count)
    permissions = _permission_set_from_json(link.permissions_json, link.role)
    creator_name = link.creator.display_name if link.creator else ""
    return {
        "id": link.id,
        "workspace_id": link.workspace_id,
        "token": link.token,
        "role": link.role.value if hasattr(link.role, "value") else str(link.role),
        "permissions": permissions_to_flags(permissions),
        "is_expert": bool(link.is_expert),
        "max_uses": link.max_uses,
        "used_count": int(link.used_count or 0),
        "remaining_uses": remaining_uses,
        "expires_at": link.expires_at,
        "created_at": link.created_at,
        "status": status,
        "created_by_name": creator_name,
    }


def get_invite_for_preview(db: Session, token: str) -> Optional[Tuple["WorkspaceInviteLink", Workspace, Dict[str, object]]]:
    from app.domains.workspace.models.invite_link import WorkspaceInviteLink

    link = db.query(WorkspaceInviteLink).filter(WorkspaceInviteLink.token == token).first()
    if not link:
        return None
    workspace = db.query(Workspace).filter(Workspace.id == link.workspace_id).first()
    if not workspace:
        return None
    return link, workspace, serialize_invite_link(link)


def accept_invite_link(
    db: Session,
    token: str,
    user: User,
) -> Tuple[WorkspaceMember, "WorkspaceInviteLink", bool]:
    """接受邀请：返回 (member, link, already_member)。链接无效/失效时抛 ValueError。"""
    from app.domains.workspace.models.invite_link import WorkspaceInviteLink

    link = db.query(WorkspaceInviteLink).filter(WorkspaceInviteLink.token == token).first()
    if not link:
        raise ValueError("Invite link not found")

    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == link.workspace_id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    if existing:
        # 已是成员：无论链接当前是否有效，直接幂等放行
        return existing, link, True

    if invite_link_status(link) != INVITE_STATUS_ACTIVE:
        raise ValueError(f"Invite link is {invite_link_status(link).lower()}")

    member = WorkspaceMember(
        workspace_id=link.workspace_id,
        user_id=user.id,
        role=link.role,
        permissions_json=link.permissions_json,
        is_expert=bool(link.is_expert),
    )
    db.add(member)
    link.used_count = int(link.used_count or 0) + 1
    db.commit()
    db.refresh(member)
    db.refresh(link)
    return member, link, False
