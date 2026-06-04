"""
Skill API routes (package + git version model).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_skill, make_resource_busy_error
from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.skill.schemas.skill import (
    SkillAnalysisCreateRequest,
    SkillAnalysisResponse,
    SkillCommitRequest,
    SkillCreate,
    SkillDetailResponse,
    SkillFileContentResponse,
    SkillFileCreateRequest,
    SkillFileMoveRequest,
    SkillFileTreeResponse,
    SkillFileWriteRequest,
    SkillGithubImportRequest,
    SkillListResponse,
    SkillPublishStatusResponse,
    SkillRatingItem,
    SkillRatingResponse,
    SkillRatingsResponse,
    SkillRatingUpsert,
    SkillResponse,
    SkillReviewCommentCreate,
    SkillReviewCommentResponse,
    SkillReviewCommentsResponse,
    SkillReviewOverviewResponse,
    SkillUpdate,
    SkillAnalysisRefKindValue,
    SkillVersionCompareResponse,
    SkillVersionDetailResponse,
    SkillVersionFileDiffResponse,
    SkillVersionListResponse,
    SkillVersionResponse,
)
from app.domains.workflow.schemas.provision import ProvisionJobAcceptedResponse
from app.domains.auth.services import auth_service
from app.domains.workflow.services import provision_job_service
from app.domains.skill.services import skill_analysis_service, skill_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/skills", tags=["Skills"])
_SKILL_BUSY_MSG = "Skill is being modified by another request. Please retry later."


def _raise_skill_lock_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, _SKILL_BUSY_MSG)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def _verify_workspace_access(ws_id: str, current_user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")


def _verify_manage_skills_permission(ws_id: str, current_user: User, db: Session) -> None:
    _verify_workspace_access(ws_id, current_user, db)
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.MANAGE_SKILLS):
        raise HTTPException(status_code=403, detail="No permission to manage skills")


def _resolve_user_display_name(user: User | None, fallback_user_id: str | None = None) -> str:
    if user and user.display_name and str(user.display_name).strip():
        return str(user.display_name).strip()
    if fallback_user_id:
        return f"user-{str(fallback_user_id)[:8]}"
    return "unknown-user"


def _normalize_workspace_id(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _skill_dimension_value(skill) -> str:
    return skill.dimension.value if hasattr(skill.dimension, "value") else str(skill.dimension)


def _to_skill_response(db: Session, ws_id: str | None, skill, current_user: User) -> SkillResponse:
    context_ws_id = _normalize_workspace_id(ws_id) or _normalize_workspace_id(skill.workspace_id)
    latest_version = skill_service.get_latest_skill_version(db, skill.id)
    try:
        publish_status = skill_service.get_skill_package_publish_status(skill)
    except Exception:
        publish_status = {
            "publish_state": "PUBLISHED",
            "has_pending_changes": False,
            "changed_files_count": 0,
        }
    average_score = None
    review_count = 0
    my_score = None
    my_note = None
    can_review = False
    is_workspace_expert = False
    if context_ws_id and workspace_service.get_workspace_member(db, context_ws_id, current_user.id):
        average_score, review_count, my_score, my_note = skill_service.get_skill_rating_summary(
            db,
            context_ws_id,
            skill,
            current_user.id,
        )
        can_review = skill_service.can_review_skill(db, current_user, context_ws_id, skill)
        is_workspace_expert = workspace_service.is_workspace_expert(db, context_ws_id, current_user.id)

    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        dimension=skill.dimension.value if hasattr(skill.dimension, "value") else skill.dimension,
        workspace_id=skill.workspace_id,
        creator_id=skill.creator_id,
        creator_display_name=_resolve_user_display_name(skill.creator, skill.creator_id),
        last_modifier_id=skill.last_modifier_id,
        last_modifier_display_name=_resolve_user_display_name(skill.last_modifier, skill.last_modifier_id),
        last_modified_at=skill.updated_at,
        package_path=skill.package_path,
        entry_file_path=skill.entry_file_path,
        manifest_path=skill.manifest_path,
        head_commit_sha=skill.head_commit_sha,
        source_type=skill.source_type,
        source_repo_url=skill.source_repo_url,
        source_skill_name=skill.source_skill_name,
        source_subdir=skill.source_subdir,
        source_locked=bool(skill.source_locked),
        source_commit_sha=skill.source_commit_sha,
        source_last_synced_at=skill.source_last_synced_at,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        can_manage=skill_service.can_manage_skill(db, skill, current_user),
        publish_state=str(publish_status.get("publish_state") or "PUBLISHED"),
        has_pending_changes=bool(publish_status.get("has_pending_changes")),
        changed_files_count=int(publish_status.get("changed_files_count") or 0),
        latest_version_no=latest_version.version_no if latest_version else 0,
        average_score=average_score,
        review_count=review_count,
        my_score=my_score,
        can_review=can_review,
        is_workspace_expert=is_workspace_expert,
    )


def _to_version_response(version) -> SkillVersionResponse:
    return SkillVersionResponse(
        id=version.id,
        skill_id=version.skill_id,
        version_no=version.version_no,
        commit_sha=version.commit_sha,
        parent_commit_sha=version.parent_commit_sha,
        tree_sha=version.tree_sha,
        changed_files_count=version.changed_files_count,
        change_note=version.change_note,
        creator_id=version.creator_id,
        creator_display_name=_resolve_user_display_name(version.creator, version.creator_id),
        created_at=version.created_at,
    )


def _to_comment_response(comment) -> SkillReviewCommentResponse:
    expert_avatar_svg = None
    if comment.expert:
        expert_avatar_svg = auth_service.resolve_user_avatar_svg(comment.expert)

    return SkillReviewCommentResponse(
        id=comment.id,
        skill_id=comment.skill_id,
        workspace_id=comment.workspace_id,
        version_id=comment.version_id,
        expert_user_id=comment.expert_user_id,
        expert_display_name=comment.expert.display_name if comment.expert else None,
        expert_avatar_svg=expert_avatar_svg,
        file_path=comment.file_path,
        body=comment.body,
        selected_text=comment.selected_text,
        line_start=comment.line_start,
        line_end=comment.line_end,
        column_start=comment.column_start,
        column_end=comment.column_end,
        char_start=comment.char_start,
        char_end=comment.char_end,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def _to_analysis_response(analysis) -> SkillAnalysisResponse:
    return SkillAnalysisResponse(**skill_analysis_service.serialize_analysis(analysis))


def _to_rating_item(rating) -> SkillRatingItem:
    expert_avatar_svg = None
    if rating.expert:
        expert_avatar_svg = auth_service.resolve_user_avatar_svg(rating.expert)

    return SkillRatingItem(
        id=rating.id,
        expert_user_id=rating.expert_user_id,
        expert_display_name=rating.expert.display_name if rating.expert else None,
        expert_avatar_svg=expert_avatar_svg,
        score=rating.score,
        note=rating.note,
        version_no=rating.version.version_no if rating.version else None,
        created_at=rating.created_at,
        updated_at=rating.updated_at,
    )


def _get_visible_skill_or_404(db: Session, ws_id: str | None, skill_id: str):
    skill = skill_service.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    normalized_ws_id = _normalize_workspace_id(ws_id)
    if not normalized_ws_id:
        if _skill_dimension_value(skill) != "GLOBAL":
            raise HTTPException(status_code=422, detail="workspace_id is required for workspace skill")
        return skill
    if not skill_service.ensure_skill_visible_in_workspace(skill, normalized_ws_id):
        raise HTTPException(status_code=404, detail="Skill not found in this workspace scope")
    return skill


def _get_skill_for_read(db: Session, current_user: User, workspace_id: str | None, skill_id: str):
    if workspace_id:
        _verify_workspace_access(workspace_id, current_user, db)
    return _get_visible_skill_or_404(db, workspace_id, skill_id)


def _get_skill_for_manage(db: Session, current_user: User, workspace_id: str | None, skill_id: str):
    if workspace_id:
        _verify_manage_skills_permission(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)
    if not skill_service.can_manage_skill(db, skill, current_user):
        raise HTTPException(status_code=403, detail="No permission to modify this skill")
    return skill


@router.get("", response_model=SkillListResponse)
def list_skills(
    workspace_id: str | None = Query(default=None, min_length=1),
    scope: str = Query("all", pattern="^(all|global|workspace)$"),
    keyword: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        skills, total = skill_service.list_skills_paginated(
            db,
            current_user,
            workspace_id=workspace_id,
            scope=scope,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return SkillListResponse(
        items=[_to_skill_response(db, workspace_id, skill, current_user) for skill in skills],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=SkillResponse)
def create_skill(
    data: SkillCreate,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dimension = str(data.dimension or "WORKSPACE")
    context_workspace_id = workspace_id or data.workspace_id or ""
    if dimension == "WORKSPACE":
        if not context_workspace_id:
            raise HTTPException(status_code=422, detail="workspace_id is required for workspace skill")
        _verify_manage_skills_permission(context_workspace_id, current_user, db)
    try:
        skill = skill_service.create_skill(
            db,
            current_user,
            context_workspace_id=context_workspace_id,
            name=data.name,
            description=data.description,
            dimension_value=data.dimension,
            workspace_id=data.workspace_id,
            entry_file_path=data.entry_file_path,
            manifest_path=data.manifest_path,
            entry_content=data.entry_content,
            manifest_content=data.manifest_content,
            initial_entries=[item.model_dump() for item in (data.initial_entries or [])],
        )
        audit_log(
            action="create_skill",
            outcome="success",
            resource_type="skill",
            resource_id=skill.id,
            user_id=current_user.id,
            workspace_id=context_workspace_id or None,
            skill_name=skill.name,
        )
        return _to_skill_response(db, context_workspace_id, skill, current_user)
    except PermissionError as exc:
        audit_log(
            action="create_skill",
            outcome="failed",
            resource_type="skill",
            user_id=current_user.id,
            workspace_id=context_workspace_id or None,
            reason=str(exc),
        )
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        audit_log(
            action="create_skill",
            outcome="failed",
            resource_type="skill",
            user_id=current_user.id,
            workspace_id=context_workspace_id or None,
            reason=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/import/github", response_model=ProvisionJobAcceptedResponse, status_code=202)
def import_skill_from_github(
    data: SkillGithubImportRequest,
    background_tasks: BackgroundTasks,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dimension = str(data.dimension or "WORKSPACE")
    context_workspace_id = workspace_id or data.workspace_id or ""
    if dimension == "WORKSPACE":
        if not context_workspace_id:
            raise HTTPException(status_code=422, detail="workspace_id is required for workspace skill")
        _verify_manage_skills_permission(context_workspace_id, current_user, db)
    try:
        job = provision_job_service.create_job(
            db,
            job_type=provision_job_service.ProvisionJobType.IMPORT_SKILL,
            creator_id=current_user.id,
            workspace_id=context_workspace_id or None,
            context_json={
                "dimension": dimension,
                "workspace_id": data.workspace_id,
                "context_workspace_id": context_workspace_id,
                "repo_url": data.repo_url,
                "skill_name": data.skill_name,
                "description": data.description,
                "follow_official_source": data.follow_official_source,
            },
            stage="QUEUED",
            message="Skill import queued",
        )
        audit_log(
            action="import_skill",
            outcome="accepted",
            resource_type="skill",
            user_id=current_user.id,
            workspace_id=context_workspace_id or None,
            repo_url=data.repo_url,
            skill_name=data.skill_name,
            source="github",
            job_id=job.id,
        )
        background_tasks.add_task(provision_job_service.run_import_skill_job, job.id)
        return provision_job_service.serialize_accepted(job)
    except PermissionError as exc:
        audit_log(
            action="import_skill",
            outcome="failed",
            resource_type="skill",
            user_id=current_user.id,
            workspace_id=context_workspace_id or None,
            repo_url=data.repo_url,
            skill_name=data.skill_name,
            reason=str(exc),
            source="github",
        )
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        audit_log(
            action="import_skill",
            outcome="failed",
            resource_type="skill",
            user_id=current_user.id,
            workspace_id=context_workspace_id or None,
            repo_url=data.repo_url,
            skill_name=data.skill_name,
            reason=str(exc),
            source="github",
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_id}", response_model=SkillDetailResponse)
def get_skill_detail(
    skill_id: str,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)
    return SkillDetailResponse(**_to_skill_response(db, workspace_id, skill, current_user).model_dump())


def _update_skill_common(
    workspace_id: str | None,
    skill_id: str,
    data: SkillUpdate,
    current_user: User,
    db: Session,
) -> SkillResponse:
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)
    requested_dimension = data.dimension or _skill_dimension_value(skill)
    requested_workspace_id = _normalize_workspace_id(data.workspace_id)
    if requested_dimension == "WORKSPACE" and requested_workspace_id and requested_workspace_id != skill.workspace_id:
        _verify_manage_skills_permission(requested_workspace_id, current_user, db)

    try:
        updated = skill_service.update_skill_metadata(
            db,
            current_user,
            skill,
            context_workspace_id=workspace_id or skill.workspace_id or "",
            name=data.name,
            description=data.description,
            dimension_value=data.dimension,
            workspace_id=data.workspace_id,
            entry_file_path=data.entry_file_path,
            manifest_path=data.manifest_path,
        )
        response_workspace_id = updated.workspace_id if _skill_dimension_value(updated) == "WORKSPACE" else workspace_id
        return _to_skill_response(db, response_workspace_id, updated, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/{skill_id}", response_model=SkillResponse)
def patch_skill(
    skill_id: str,
    data: SkillUpdate,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _update_skill_common(workspace_id, skill_id, data, current_user, db)


@router.put("/{skill_id}", response_model=SkillResponse)
def put_skill(
    skill_id: str,
    data: SkillUpdate,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _update_skill_common(workspace_id, skill_id, data, current_user, db)


@router.post("/{skill_id}/source/sync", response_model=SkillResponse)
async def sync_skill_official_source(
    skill_id: str,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)

    try:
        async with lock_skill(skill_id):
            skill_service.sync_skill_from_official_source(
                db,
                current_user,
                skill,
                context_workspace_id=workspace_id or skill.workspace_id or "",
            )
        audit_log(
            action="sync_skill_source",
            outcome="success",
            resource_type="skill",
            resource_id=skill.id,
            user_id=current_user.id,
            workspace_id=workspace_id,
            source="github",
        )
        return _to_skill_response(db, workspace_id, skill, current_user)
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{skill_id}", response_model=dict)
async def delete_skill(
    skill_id: str,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = skill_service.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_dimension = skill.dimension.value if hasattr(skill.dimension, "value") else str(skill.dimension)
    if skill_dimension == "WORKSPACE":
        if not workspace_id:
            raise HTTPException(status_code=422, detail="workspace_id is required for workspace skill deletion")
        _verify_manage_skills_permission(workspace_id, current_user, db)
        if not skill_service.ensure_skill_visible_in_workspace(skill, workspace_id):
            raise HTTPException(status_code=404, detail="Skill not found in this workspace scope")

    try:
        async with lock_skill(skill_id):
            skill_service.delete_skill(db, current_user, skill)
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        audit_log(
            action="delete_skill",
            outcome="failed",
            resource_type="skill",
            resource_id=skill_id,
            user_id=current_user.id,
            workspace_id=workspace_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        audit_log(
            action="delete_skill",
            outcome="failed",
            resource_type="skill",
            resource_id=skill_id,
            user_id=current_user.id,
            workspace_id=workspace_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))

    audit_log(
        action="delete_skill",
        outcome="success",
        resource_type="skill",
        resource_id=skill_id,
        user_id=current_user.id,
        workspace_id=workspace_id,
        skill_name=skill.name,
    )
    return {"msg": "Skill deleted successfully"}


@router.get("/{skill_id}/analyses/latest", response_model=SkillAnalysisResponse | None)
def get_latest_skill_analysis(
    skill_id: str,
    workspace_id: str = Query(..., min_length=1),
    ref_kind: SkillAnalysisRefKindValue = Query(default="LATEST"),
    version_id: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)
    try:
        analysis = skill_analysis_service.get_latest_analysis_for_ref(
            db,
            workspace_id=workspace_id,
            skill=skill,
            ref_kind=ref_kind,
            version_id=version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_analysis_response(analysis) if analysis else None


@router.get("/{skill_id}/analyses/{analysis_id}", response_model=SkillAnalysisResponse)
def get_skill_analysis(
    skill_id: str,
    analysis_id: str,
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    _get_visible_skill_or_404(db, workspace_id, skill_id)
    analysis = skill_analysis_service.get_analysis(
        db,
        workspace_id=workspace_id,
        skill_id=skill_id,
        analysis_id=analysis_id,
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Skill analysis not found")
    return _to_analysis_response(analysis)


@router.post("/{skill_id}/analyses", response_model=SkillAnalysisResponse)
def create_skill_analysis(
    skill_id: str,
    data: SkillAnalysisCreateRequest,
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_skills_permission(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)
    try:
        analysis = skill_analysis_service.create_analysis_job(
            db,
            user=current_user,
            skill=skill,
            workspace_id=workspace_id,
            ref_kind=data.ref_kind,
            version_id=data.version_id,
        )
        skill_analysis_service.schedule_analysis_job(analysis.id)
        audit_log(
            action="create_skill_analysis",
            outcome="success",
            resource_type="skill_analysis",
            resource_id=analysis.id,
            user_id=current_user.id,
            workspace_id=workspace_id,
            skill_id=skill.id,
            ref_kind=data.ref_kind,
            version_id=data.version_id,
        )
        return _to_analysis_response(analysis)
    except ValueError as exc:
        audit_log(
            action="create_skill_analysis",
            outcome="failed",
            resource_type="skill_analysis",
            user_id=current_user.id,
            workspace_id=workspace_id,
            skill_id=skill.id,
            reason=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/{skill_id}/files/tree", response_model=SkillFileTreeResponse)
def get_skill_file_tree(
    skill_id: str,
    ref: str = Query("WORKTREE"),
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)

    try:
        nodes = skill_service.build_skill_file_tree(db, skill, ref=ref)
        return SkillFileTreeResponse(ref=ref or "WORKTREE", nodes=nodes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_id}/files/content", response_model=SkillFileContentResponse)
def get_skill_file_content(
    skill_id: str,
    path: str = Query(..., min_length=1),
    ref: str = Query("WORKTREE"),
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)

    try:
        content, is_binary, size = skill_service.read_skill_file(db, skill, path=path, ref=ref)
        return SkillFileContentResponse(
            ref=ref or "WORKTREE",
            path=path,
            content=content,
            is_binary=is_binary,
            size=size,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{skill_id}/files/content", response_model=SkillFileContentResponse)
async def write_skill_file_content(
    skill_id: str,
    data: SkillFileWriteRequest,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)

    try:
        async with lock_skill(skill_id):
            size = skill_service.write_skill_file(skill, path=data.path, content=data.content)
        return SkillFileContentResponse(
            ref="WORKTREE",
            path=data.path,
            content=data.content,
            is_binary=False,
            size=size,
        )
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{skill_id}/files", response_model=dict)
async def create_skill_file_or_dir(
    skill_id: str,
    data: SkillFileCreateRequest,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)

    try:
        async with lock_skill(skill_id):
            skill_service.create_skill_file_or_dir(skill, path=data.path, node_type=data.node_type, content=data.content)
        return {"msg": "Created"}
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{skill_id}/files", response_model=dict)
async def delete_skill_file_or_dir(
    skill_id: str,
    path: str = Query(..., min_length=1),
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)

    try:
        async with lock_skill(skill_id):
            skill_service.delete_skill_file_or_dir(skill, path=path)
        return {"msg": "Deleted"}
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Path not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{skill_id}/files/move", response_model=dict)
async def move_skill_file_or_dir(
    skill_id: str,
    data: SkillFileMoveRequest,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)

    try:
        async with lock_skill(skill_id):
            skill_service.move_skill_file_or_dir(skill, old_path=data.old_path, new_path=data.new_path)
        return {"msg": "Moved"}
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Source path not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_id}/versions", response_model=SkillVersionListResponse)
def list_skill_versions(
    skill_id: str,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)
    versions = skill_service.list_skill_versions(db, skill.id)
    current_version_no = versions[0].version_no if versions else 0
    return SkillVersionListResponse(
        items=[_to_version_response(version) for version in versions],
        total=len(versions),
        current_version_no=current_version_no,
    )


@router.get("/{skill_id}/versions/pending", response_model=SkillPublishStatusResponse)
def get_skill_publish_status(
    skill_id: str,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)
    try:
        status = skill_service.get_skill_package_publish_status(skill)
        return SkillPublishStatusResponse(
            publish_state=str(status.get("publish_state") or "PUBLISHED"),
            has_pending_changes=bool(status.get("has_pending_changes")),
            changed_files_count=int(status.get("changed_files_count") or 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{skill_id}/versions/commit", response_model=SkillVersionResponse)
async def commit_skill_version(
    skill_id: str,
    data: SkillCommitRequest,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)

    try:
        async with lock_skill(skill_id):
            version = skill_service.commit_skill_package(
                db,
                current_user,
                skill,
                change_note=data.change_note,
            )
        audit_log(
            action="publish_skill",
            outcome="success",
            resource_type="skill_version",
            resource_id=version.id,
            user_id=current_user.id,
            workspace_id=workspace_id,
            skill_id=skill.id,
            commit_sha=version.commit_sha,
            version_no=version.version_no,
        )
        return _to_version_response(version)
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        audit_log(
            action="publish_skill",
            outcome="failed",
            resource_type="skill_version",
            resource_id=skill_id,
            user_id=current_user.id,
            workspace_id=workspace_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        audit_log(
            action="publish_skill",
            outcome="failed",
            resource_type="skill_version",
            resource_id=skill_id,
            user_id=current_user.id,
            workspace_id=workspace_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_id}/versions/compare", response_model=SkillVersionCompareResponse)
def compare_skill_versions(
    skill_id: str,
    from_version_id: str = Query(..., min_length=1),
    to_version_id: str = Query(..., min_length=1),
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)

    from_version = skill_service.get_skill_version(db, skill.id, from_version_id)
    to_version = skill_service.get_skill_version(db, skill.id, to_version_id)
    if not from_version or not to_version:
        raise HTTPException(status_code=404, detail="Version not found")

    files = skill_service.compare_skill_versions(
        db,
        skill,
        from_version=from_version,
        to_version=to_version,
    )

    return SkillVersionCompareResponse(
        from_version_id=from_version.id,
        to_version_id=to_version.id,
        files=files,
    )


@router.get("/{skill_id}/versions/compare/file", response_model=SkillVersionFileDiffResponse)
def compare_skill_file(
    skill_id: str,
    from_version_id: str = Query(..., min_length=1),
    to_version_id: str = Query(..., min_length=1),
    path: str = Query(..., min_length=1),
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)

    from_version = skill_service.get_skill_version(db, skill.id, from_version_id)
    to_version = skill_service.get_skill_version(db, skill.id, to_version_id)
    if not from_version or not to_version:
        raise HTTPException(status_code=404, detail="Version not found")

    try:
        payload = skill_service.compare_skill_file_between_versions(
            skill,
            from_version=from_version,
            to_version=to_version,
            path=path,
        )
        return SkillVersionFileDiffResponse(
            from_version_id=from_version.id,
            to_version_id=to_version.id,
            path=payload.get("path") or path,
            is_binary=bool(payload.get("is_binary")),
            diff=payload.get("diff"),
            original=payload.get("original"),
            modified=payload.get("modified"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{skill_id}/versions/{version_id}", response_model=SkillVersionDetailResponse)
def get_skill_version_detail(
    skill_id: str,
    version_id: str,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_read(db, current_user, workspace_id, skill_id)
    version = skill_service.get_skill_version(db, skill.id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    payload = _to_version_response(version).model_dump()
    return SkillVersionDetailResponse(**payload)


@router.post("/{skill_id}/versions/{version_id}/restore", response_model=SkillVersionResponse)
async def restore_skill_version(
    skill_id: str,
    version_id: str,
    workspace_id: str | None = Query(default=None, min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    skill = _get_skill_for_manage(db, current_user, workspace_id, skill_id)
    version = skill_service.get_skill_version(db, skill.id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    try:
        async with lock_skill(skill_id):
            restored = skill_service.restore_skill_version(db, current_user, skill, version)
        return _to_version_response(restored)
    except LockAcquireTimeout as exc:
        _raise_skill_lock_conflict(exc)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/{skill_id}/reviews/overview", response_model=SkillReviewOverviewResponse)
def get_skill_review_overview(
    skill_id: str,
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)

    latest = skill_service.get_latest_skill_version(db, skill.id)
    average_score, review_count, my_score, my_note = skill_service.get_skill_rating_summary(
        db,
        workspace_id,
        skill,
        current_user.id,
    )
    can_review = skill_service.can_review_skill(db, current_user, workspace_id, skill)
    return SkillReviewOverviewResponse(
        average_score=average_score,
        review_count=review_count,
        my_score=my_score,
        my_note=my_note,
        can_review=can_review,
        current_version_no=latest.version_no if latest else 0,
    )


@router.post("/{skill_id}/reviews/rating", response_model=SkillRatingResponse)
def upsert_skill_rating(
    skill_id: str,
    data: SkillRatingUpsert,
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)

    try:
        rating = skill_service.upsert_skill_rating(
            db,
            current_user,
            workspace_id,
            skill,
            score=data.score,
            note=data.note,
        )
        return SkillRatingResponse(
            id=rating.id,
            skill_id=rating.skill_id,
            workspace_id=rating.workspace_id,
            version_id=rating.version_id,
            expert_user_id=rating.expert_user_id,
            score=rating.score,
            note=rating.note,
            created_at=rating.created_at,
            updated_at=rating.updated_at,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/{skill_id}/reviews/ratings", response_model=SkillRatingsResponse)
def list_skill_ratings(
    skill_id: str,
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)

    ratings = skill_service.list_skill_ratings(db, workspace_id, skill)
    return SkillRatingsResponse(
        items=[_to_rating_item(r) for r in ratings],
        total=len(ratings),
    )


@router.get("/{skill_id}/reviews/comments", response_model=SkillReviewCommentsResponse)
def list_skill_review_comments(
    skill_id: str,
    version_id: str | None = Query(default=None),
    file_path: str | None = Query(default=None),
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)

    try:
        comments, resolved_version_id = skill_service.list_skill_review_comments(
            db,
            workspace_id,
            skill,
            version_id=version_id,
            file_path=file_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SkillReviewCommentsResponse(
        items=[_to_comment_response(comment) for comment in comments],
        total=len(comments),
        version_id=resolved_version_id,
        file_path=file_path,
    )


@router.post("/{skill_id}/reviews/comments", response_model=SkillReviewCommentResponse)
def create_skill_review_comment(
    skill_id: str,
    data: SkillReviewCommentCreate,
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)

    try:
        comment = skill_service.create_skill_review_comment(
            db,
            current_user,
            workspace_id,
            skill,
            version_id=data.version_id,
            file_path=data.file_path,
            body=data.body,
            line_start=data.line_start,
            line_end=data.line_end,
            column_start=data.column_start,
            column_end=data.column_end,
            char_start=data.char_start,
            char_end=data.char_end,
            selected_text=data.selected_text,
        )
        reloaded = skill_service.get_skill_review_comment(db, skill_id, comment.id) or comment
        return _to_comment_response(reloaded)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{skill_id}/reviews/comments/{comment_id}", response_model=dict)
def delete_skill_review_comment(
    skill_id: str,
    comment_id: str,
    workspace_id: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(workspace_id, current_user, db)
    skill = _get_visible_skill_or_404(db, workspace_id, skill_id)
    comment = skill_service.get_skill_review_comment(db, skill_id, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Review comment not found")

    try:
        skill_service.delete_skill_review_comment(db, current_user, skill, comment)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return {"msg": "Review comment deleted"}
