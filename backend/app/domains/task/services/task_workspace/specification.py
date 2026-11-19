"""Publish uploaded task specifications as versioned assets and invalidate agent baselines."""

import os

from sqlalchemy.orm import Session

from app.domains.asset.services import asset_discussion_service
from app.domains.asset.services.document import versioning as document_versioning
from app.domains.task.models.task import SddTask

SUPPORTED_SPEC_EXTS = {".docx", ".md", ".txt"}


def ensure_supported_spec_ext(file_name: str | None) -> str:
    """Reject unsupported specification formats at the API boundary."""
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext == ".doc":
        raise ValueError("Legacy .doc files are not supported; please convert to .docx")
    if ext not in SUPPORTED_SPEC_EXTS:
        raise ValueError("Unsupported specification file type; supported formats: .docx, .md, .txt")
    return ext


def upload_task_spec(
    db: Session,
    task_id: str,
    file_name: str,
    file_content: bytes,
) -> tuple[str, str, str]:
    """Publish one immutable original and point the task at that committed version."""
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise ValueError("Task not found")

    ensure_supported_spec_ext(file_name)

    from app.domains.local_resource.service import is_local, materialize_file

    asset, version = document_versioning.create_asset_version_from_upload(
        db,
        task,
        creator_id=task.creator_id,
        file_name=file_name,
        file_content=file_content,
        change_note="Uploaded task specification",
    )
    if is_local(task):
        safe_name = os.path.basename(version.original_path)
        task.spec_doc_path = materialize_file(task, f".sdd/spec/{version.id}/{safe_name}", file_content)
    else:
        task.spec_doc_path = os.path.abspath(version.original_path)
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
