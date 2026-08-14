"""
Workspace service.
"""

import json
import os
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspacePermission,
    WorkspaceRole,
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

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
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
        "base_dir": row.base_dir,
        "state": row.state.value if hasattr(row.state, "value") else str(row.state),
        "base_commit_sha": row.base_commit_sha,
        "error_message": row.error_message,
        "created_at": row.created_at,
    }


def serialize_workspace(workspace: Workspace, member: WorkspaceMember) -> Dict[str, object]:
    repositories = [serialize_workspace_repository(row) for row in workspace.repositories]
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "project_path": workspace.project_path,
        "git_repo_url": workspace.git_repo_url,
        "project_id": workspace.project_id,
        "owner_id": workspace.owner_id,
        "created_at": workspace.created_at,
        "my_role": member.role.value if hasattr(member.role, "value") else str(member.role),
        "my_is_expert": bool(member.is_expert),
        "can_delete_workspace": member.role == WorkspaceRole.OWNER,
        "repositories": repositories,
    }


def _normalize_optional(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def create_workspace(
    db: Session,
    user: User,
    name: str,
    description: Optional[str] = None,
    project_path: Optional[str] = None,
    git_repo_url: Optional[str] = None,
    project_id: Optional[str] = None,
    repositories: Optional[List[Dict[str, str]]] = None,
) -> Workspace:
    from app.domains.management.models.management import SddManagementProject
    from app.domains.management.services import project_service
    from app.domains.management.services import repository_service as mgmt_repository_service
    from app.domains.workspace.models.workspace_repository import (
        SddWorkspaceRepository,
        WorkspaceRepositoryState,
    )

    normalized_project_path = _normalize_optional(project_path)
    normalized_git_repo_url = _normalize_optional(git_repo_url)

    if project_id:
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

        overrides: Dict[str, str] = {}
        for item in repositories or []:
            repository_id = str((item or {}).get("repository_id") or "").strip()
            branch_name = str((item or {}).get("branch_name") or "").strip()
            if repository_id and branch_name:
                overrides[repository_id] = branch_name

        repo_set = project_service.resolve_project_repo_set(db, project, branch_overrides=overrides)
        seen_slugs: set = set()
        for item in repo_set:
            slug = mgmt_repository_service.build_repo_slug(item["repository_name"])
            candidate = slug
            sequence = 1
            while candidate in seen_slugs:
                candidate = f"{slug}-{sequence}"
                sequence += 1
            seen_slugs.add(candidate)
            base_dir = os.path.join(normalized_project_path or "", ".repos", candidate)
            db.add(
                SddWorkspaceRepository(
                    workspace_id=workspace.id,
                    repository_id=item["repository_id"],
                    repo_url=item["git_url"],
                    repo_name=item["repository_name"],
                    repo_slug=candidate,
                    branch_name=item["branch_name"],
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
