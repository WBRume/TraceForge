"""
Change proposal orchestration and local agent result persistence.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.domains.asset.models.asset import SddAssetVersion
from app.domains.task.models.task import SddTask
from app.domains.workflow.models.task_change import (
    ChangeProposalFileType,
    ChangeProposalStatus,
    SddTaskChangeProposal,
    SddTaskChangeProposalFile,
    SddTaskConflictReport,
    SddTaskVerificationRun,
    VerificationRunStatus,
)
from app.domains.auth.models.user import User, Workspace, WorkspaceMember
from app.domains.task.services import git_patch_service
from app.domains.workflow.services import change_artifact_service


class ChangeProposalError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _as_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _next_task_sequence(db: Session, task_id: str, column) -> int:
    current = db.query(func.max(column)).filter(SddTaskChangeProposal.task_id == task_id).scalar()
    return int(current or 0) + 1


def _normalize_file_type(value: str) -> ChangeProposalFileType:
    normalized = str(value or "").strip().lower()
    try:
        return ChangeProposalFileType(normalized)
    except ValueError:
        return ChangeProposalFileType.MODIFIED


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    return value if isinstance(value, datetime) else None


def _ensure_base_matches(proposal: SddTaskChangeProposal, base_commit_sha: str) -> None:
    expected = str(proposal.base_commit_sha or "").strip()
    actual = str(base_commit_sha or "").strip()
    if not actual:
        raise ChangeProposalError("base_commit_sha is required", status_code=422)
    if expected and actual != expected:
        raise ChangeProposalError(
            "Patch base commit does not match proposal base_commit_sha",
            status_code=409,
        )


def get_visible_task(db: Session, *, task_id: str, user_id: str) -> Optional[SddTask]:
    return (
        db.query(SddTask)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == SddTask.workspace_id)
        .filter(SddTask.id == task_id, WorkspaceMember.user_id == user_id)
        .first()
    )


def list_agent_tasks(
    db: Session,
    *,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, Any]], int]:
    query = (
        db.query(SddTask)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == SddTask.workspace_id)
        .filter(WorkspaceMember.user_id == user_id)
    )
    total = query.count()
    tasks = (
        query.order_by(SddTask.created_at.desc())
        .offset((max(1, page) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [serialize_agent_task(db, task) for task in tasks], total


def serialize_agent_task(db: Session, task: SddTask) -> Dict[str, Any]:
    latest = get_latest_task_proposal(db, task_id=task.id)
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "creator_id": task.creator_id,
        "name": task.name,
        "description": task.description,
        "git_repo_url": task.git_repo_url,
        "status": _as_value(task.status),
        "current_phase": task.current_phase,
        "error_message": task.error_message,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "latest_change_proposal_id": latest.id if latest else None,
    }


def get_visible_proposal(
    db: Session,
    *,
    proposal_id: str,
    user_id: str,
) -> Optional[SddTaskChangeProposal]:
    return (
        db.query(SddTaskChangeProposal)
        .options(joinedload(SddTaskChangeProposal.files))
        .join(WorkspaceMember, WorkspaceMember.workspace_id == SddTaskChangeProposal.workspace_id)
        .filter(SddTaskChangeProposal.id == proposal_id, WorkspaceMember.user_id == user_id)
        .first()
    )


def get_latest_task_proposal(db: Session, *, task_id: str) -> Optional[SddTaskChangeProposal]:
    return (
        db.query(SddTaskChangeProposal)
        .filter(SddTaskChangeProposal.task_id == task_id)
        .order_by(SddTaskChangeProposal.patch_set_no.desc(), SddTaskChangeProposal.created_at.desc())
        .first()
    )


def list_proposal_files(db: Session, *, proposal_id: str) -> List[SddTaskChangeProposalFile]:
    return (
        db.query(SddTaskChangeProposalFile)
        .filter(SddTaskChangeProposalFile.proposal_id == proposal_id)
        .order_by(SddTaskChangeProposalFile.file_path.asc())
        .all()
    )


def create_change_proposal(
    db: Session,
    *,
    task: SddTask,
    workspace: Optional[Workspace],
    creator_id: str,
    summary: Optional[str] = None,
    risk_notes: Optional[str] = None,
) -> SddTaskChangeProposal:
    try:
        snapshot = git_patch_service.generate_task_patch_snapshot(task, workspace)
        proposal_no = _next_task_sequence(db, task.id, SddTaskChangeProposal.proposal_no)
        patch_set_no = _next_task_sequence(db, task.id, SddTaskChangeProposal.patch_set_no)
        proposal = SddTaskChangeProposal(
            task_id=task.id,
            workspace_id=task.workspace_id,
            proposal_no=proposal_no,
            patch_set_no=patch_set_no,
            status=ChangeProposalStatus.GENERATED,
            base_repo_url=snapshot.base_repo_url,
            base_branch=snapshot.base_branch,
            base_commit_sha=snapshot.base_commit_sha,
            cloud_task_branch=snapshot.cloud_task_branch,
            cloud_head_sha=snapshot.cloud_head_sha,
            changed_files_count=snapshot.changed_files_count,
            insertions=snapshot.insertions,
            deletions=snapshot.deletions,
            summary=(summary or "").strip() or f"Change proposal #{proposal_no}",
            risk_notes=(risk_notes or "").strip() or None,
        )
        db.add(proposal)
        db.flush()

        patch_asset, patch_version = change_artifact_service.create_patch_asset(
            db,
            task,
            creator_id=creator_id,
            proposal_no=proposal_no,
            patch_set_no=patch_set_no,
            patch_text=snapshot.patch_text,
            metadata={
                "proposal_id": proposal.id,
                "base_branch": snapshot.base_branch,
                "base_commit_sha": snapshot.base_commit_sha,
                "cloud_task_branch": snapshot.cloud_task_branch,
                "cloud_head_sha": snapshot.cloud_head_sha,
                "changed_files_count": snapshot.changed_files_count,
                "insertions": snapshot.insertions,
                "deletions": snapshot.deletions,
            },
        )
        proposal.patch_asset_id = patch_asset.id
        proposal.patch_asset_version_id = patch_version.id

        for change in snapshot.files:
            db.add(
                SddTaskChangeProposalFile(
                    proposal_id=proposal.id,
                    file_path=change.file_path,
                    old_path=change.old_path,
                    new_path=change.new_path,
                    change_type=_normalize_file_type(change.change_type),
                    insertions=int(change.insertions or 0),
                    deletions=int(change.deletions or 0),
                    diff_excerpt=change.diff_excerpt,
                    is_binary=bool(change.is_binary),
                )
            )

        db.commit()
        db.refresh(proposal)
        return proposal
    except Exception:
        db.rollback()
        raise


def mark_patch_downloaded(db: Session, proposal: SddTaskChangeProposal) -> SddTaskChangeProposal:
    if proposal.status in {ChangeProposalStatus.DRAFT, ChangeProposalStatus.GENERATED}:
        proposal.status = ChangeProposalStatus.DOWNLOADED
        db.commit()
        db.refresh(proposal)
    return proposal


def read_patch_file(db: Session, proposal: SddTaskChangeProposal) -> Tuple[bytes, str]:
    version_id = str(proposal.patch_asset_version_id or "").strip()
    if not version_id:
        raise ChangeProposalError("Patch artifact is missing", status_code=404)
    version = db.query(SddAssetVersion).filter(SddAssetVersion.id == version_id).first()
    if not version:
        raise ChangeProposalError("Patch artifact version not found", status_code=404)
    abs_path = os.path.abspath(str(version.original_path or "").strip())
    if not abs_path or not os.path.isfile(abs_path):
        raise ChangeProposalError("Patch file not found", status_code=404)
    with open(abs_path, "rb") as handle:
        raw = handle.read()
    filename = os.path.basename(abs_path) or f"change-proposal-{proposal.proposal_no}.patch"
    return raw, filename


def record_apply_result(
    db: Session,
    *,
    task: SddTask,
    user: User,
    proposal_id: str,
    status: str,
    base_commit_sha: str,
    local_head_sha: Optional[str] = None,
    message: Optional[str] = None,
) -> SddTaskChangeProposal:
    proposal = db.query(SddTaskChangeProposal).filter(SddTaskChangeProposal.id == proposal_id).first()
    if not proposal or proposal.task_id != task.id:
        raise ChangeProposalError("Change proposal not found", status_code=404)
    _ = user
    _ensure_base_matches(proposal, base_commit_sha)
    normalized = str(status or "").strip().lower()
    if normalized == "applied":
        proposal.status = ChangeProposalStatus.APPLIED
    elif normalized == "conflict":
        proposal.status = ChangeProposalStatus.CONFLICT
    elif normalized == "rejected":
        proposal.status = ChangeProposalStatus.REJECTED
    else:
        raise ChangeProposalError("Invalid apply result status", status_code=422)
    if message:
        proposal.risk_notes = "\n\n".join(part for part in [proposal.risk_notes, str(message).strip()] if part)
    _ = local_head_sha
    db.commit()
    db.refresh(proposal)
    return proposal


def create_verification_run(
    db: Session,
    *,
    task: SddTask,
    user: User,
    proposal_id: str,
    agent_id: Optional[str],
    machine_name: Optional[str],
    os_name: Optional[str],
    command: Optional[str],
    status: str,
    duration_ms: Optional[int],
    base_commit_sha: str,
    local_head_sha: Optional[str],
    log_excerpt: Optional[str],
    started_at: Optional[datetime],
    finished_at: Optional[datetime],
) -> SddTaskVerificationRun:
    proposal = db.query(SddTaskChangeProposal).filter(SddTaskChangeProposal.id == proposal_id).first()
    if not proposal or proposal.task_id != task.id:
        raise ChangeProposalError("Change proposal not found", status_code=404)
    _ensure_base_matches(proposal, base_commit_sha)
    try:
        normalized_status = VerificationRunStatus(str(status or "running").strip().lower())
    except ValueError as exc:
        raise ChangeProposalError("Invalid verification run status", status_code=422) from exc

    run = SddTaskVerificationRun(
        task_id=task.id,
        workspace_id=task.workspace_id,
        proposal_id=proposal.id,
        user_id=user.id,
        agent_id=(agent_id or "").strip() or None,
        machine_name=(machine_name or "").strip() or None,
        os_name=(os_name or "").strip() or None,
        command=(command or "").strip() or None,
        status=normalized_status,
        duration_ms=duration_ms,
        base_commit_sha=base_commit_sha,
        local_head_sha=(local_head_sha or "").strip() or None,
        log_excerpt=(log_excerpt or "").strip() or None,
        started_at=_normalize_datetime(started_at),
        finished_at=_normalize_datetime(finished_at),
    )
    db.add(run)
    if normalized_status == VerificationRunStatus.SUCCESS:
        proposal.status = ChangeProposalStatus.VERIFIED
    elif normalized_status == VerificationRunStatus.CONFLICT:
        proposal.status = ChangeProposalStatus.CONFLICT
    db.commit()
    db.refresh(run)
    return run


def attach_verification_log(
    db: Session,
    *,
    task: SddTask,
    run_id: str,
    user: User,
    file_name: str,
    file_content: bytes,
    log_excerpt: Optional[str] = None,
) -> SddTaskVerificationRun:
    run = db.query(SddTaskVerificationRun).filter(SddTaskVerificationRun.id == run_id).first()
    if not run or run.task_id != task.id:
        raise ChangeProposalError("Verification run not found", status_code=404)
    asset, version, excerpt = change_artifact_service.create_verification_log_asset(
        db,
        task,
        creator_id=user.id,
        run_id=run.id,
        file_name=file_name,
        file_content=file_content,
        metadata={"proposal_id": run.proposal_id},
    )
    run.log_asset_id = asset.id
    run.log_asset_version_id = version.id
    run.log_excerpt = (log_excerpt or "").strip() or excerpt
    db.commit()
    db.refresh(run)
    return run


def create_conflict_report(
    db: Session,
    *,
    task: SddTask,
    user: User,
    proposal_id: str,
    agent_id: Optional[str],
    machine_name: Optional[str],
    base_commit_sha: str,
    local_head_sha: Optional[str],
    conflicted_files: Any,
    git_apply_stderr: Optional[str],
    conflict_excerpt: Optional[str],
    report_file_name: Optional[str] = None,
    report_file_content: Optional[bytes] = None,
) -> SddTaskConflictReport:
    proposal = db.query(SddTaskChangeProposal).filter(SddTaskChangeProposal.id == proposal_id).first()
    if not proposal or proposal.task_id != task.id:
        raise ChangeProposalError("Change proposal not found", status_code=404)
    _ensure_base_matches(proposal, base_commit_sha)

    report = SddTaskConflictReport(
        task_id=task.id,
        workspace_id=task.workspace_id,
        proposal_id=proposal.id,
        user_id=user.id,
        agent_id=(agent_id or "").strip() or None,
        machine_name=(machine_name or "").strip() or None,
        base_commit_sha=base_commit_sha,
        local_head_sha=(local_head_sha or "").strip() or None,
        conflicted_files_json=conflicted_files,
        git_apply_stderr=(git_apply_stderr or "").strip() or None,
        conflict_excerpt=(conflict_excerpt or "").strip() or None,
    )
    db.add(report)
    db.flush()

    if report_file_content:
        asset, version, excerpt = change_artifact_service.create_conflict_report_asset(
            db,
            task,
            creator_id=user.id,
            report_id=report.id,
            file_name=report_file_name or f"conflict-report-{report.id}.log",
            file_content=report_file_content,
            metadata={"proposal_id": proposal.id},
        )
        report.report_asset_id = asset.id
        report.report_asset_version_id = version.id
        if not report.conflict_excerpt:
            report.conflict_excerpt = excerpt
    elif not report.conflict_excerpt and report.git_apply_stderr:
        report.conflict_excerpt = report.git_apply_stderr[:12000]

    proposal.status = ChangeProposalStatus.CONFLICT
    db.commit()
    db.refresh(report)
    return report
