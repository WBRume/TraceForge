"""Publish uploaded task specifications as versioned assets and invalidate agent baselines."""

import os

from sqlalchemy.orm import Session

from app.domains.asset.services import asset_discussion_service
from app.domains.asset.services.document import versioning as document_versioning
from app.domains.task.models.task import SddTask

PDF_SPEC_BOOTSTRAP_DISABLED_EXTS = {".pdf"}


def spec_bootstrap_enabled_for_ext(ext: str) -> bool:
    return (ext or "").lower() not in PDF_SPEC_BOOTSTRAP_DISABLED_EXTS


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

    ext = os.path.splitext(file_name or "")[1].lower()
    if ext == ".doc":
        raise ValueError("Legacy .doc files are not supported; please convert to .docx or upload a PDF")

    from app.domains.asset.services.document.storage import normalize_filename
    from app.domains.local_resource.service import is_local, materialize_file

    file_name = normalize_filename(file_name)
    asset, version = document_versioning.create_asset_version_from_upload(
        db,
        task,
        creator_id=task.creator_id,
        file_name=file_name,
        file_content=file_content,
        change_note="Uploaded task specification",
    )
    if is_local(task):
        task.spec_doc_path = materialize_file(task, f".sdd/spec/{version.id}/{file_name}", file_content)
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
