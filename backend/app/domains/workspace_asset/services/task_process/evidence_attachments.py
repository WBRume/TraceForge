"""Storage and ownership checks for task evidence attachments."""

import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.domains.task.models.task import SddTask
from app.domains.workspace_asset.models.evidence_attachment import TaskEvidenceAttachment
from app.domains.workspace_asset.models.workspace_asset import SddEvidence
from app.domains.workspace_asset.schemas.workspace_asset import EvidenceAttachmentResponse
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError

ATTACHMENT_ROOT = Path(__file__).resolve().parents[5] / "storage" / "task-evidence-attachments"


def attachment_path(attachment: TaskEvidenceAttachment) -> Path:
    root = ATTACHMENT_ROOT.resolve()
    path = root / attachment.task_id / attachment.id
    if path.resolve() != path or not path.is_relative_to(root):
        raise WorkspaceAssetError("Attachment file not found", status_code=404)
    return path


def upload(db: Session, task: SddTask, actor_id: str, file: UploadFile) -> EvidenceAttachmentResponse:
    """Store the bytes and commit the pending attachment for this task."""
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if (
        not filename.strip()
        or len(filename) > 255
        or filename in {".", ".."}
        or any(ord(char) < 32 for char in filename)
    ):
        raise WorkspaceAssetError("Invalid attachment filename", status_code=422)
    attachment = TaskEvidenceAttachment(
        id=str(uuid4()),
        workspace_id=task.workspace_id,
        task_id=task.id,
        uploader_id=actor_id,
        filename=filename,
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )
    path = attachment_path(attachment)
    path.parent.mkdir(parents=True, exist_ok=True)
    destination = path.open("xb")
    try:
        with destination:
            shutil.copyfileobj(file.file, destination)
            attachment.size = destination.tell()
    except OSError:
        path.unlink(missing_ok=True)
        raise
    db.add(attachment)
    db.commit()
    return _describe(attachment)


def load_pending(
    db: Session, workspace_id: str, task_id: str, actor_id: str, attachment_ids: list[str]
) -> list[TaskEvidenceAttachment]:
    """Lock and validate all attachments before associating them in the closeout transaction."""
    if not attachment_ids:
        return []
    unique_ids = set(attachment_ids)
    if len(unique_ids) != len(attachment_ids):
        raise WorkspaceAssetError("An attachment can only be submitted once", status_code=422)
    attachments = {
        row.id: row
        for row in db.query(TaskEvidenceAttachment)
        .filter_by(workspace_id=workspace_id, task_id=task_id, uploader_id=actor_id, evidence_id=None)
        .filter(TaskEvidenceAttachment.id.in_(attachment_ids))
        .with_for_update()
        .all()
    }
    if attachments.keys() != unique_ids:
        raise WorkspaceAssetError("One or more attachments are unavailable for this task", status_code=404)
    ordered = [attachments[attachment_id] for attachment_id in attachment_ids]
    if any(not attachment_path(row).is_file() for row in ordered):
        raise WorkspaceAssetError("Attachment file not found", status_code=404)
    return ordered


def _describe(row: TaskEvidenceAttachment) -> EvidenceAttachmentResponse:
    return EvidenceAttachmentResponse(id=row.id, filename=row.filename, content_type=row.content_type, size=row.size)


def list_for_evidence(db: Session, evidence: SddEvidence) -> list[EvidenceAttachmentResponse]:
    """List files attached to the exact evidence, task and workspace."""
    rows = (
        db.query(TaskEvidenceAttachment)
        .filter_by(workspace_id=evidence.workspace_id, task_id=evidence.task_id, evidence_id=evidence.id)
        .order_by(TaskEvidenceAttachment.created_at, TaskEvidenceAttachment.id)
        .all()
    )
    return [_describe(row) for row in rows]


def get_for_evidence(
    db: Session, workspace_id: str, task_id: str, evidence_id: str, attachment_id: str
) -> TaskEvidenceAttachment | None:
    """Look up the exact association, independent of editable evidence source metadata."""
    return (
        db.query(TaskEvidenceAttachment)
        .join(SddEvidence, TaskEvidenceAttachment.evidence_id == SddEvidence.id)
        .filter(
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
            SddEvidence.id == evidence_id,
            TaskEvidenceAttachment.workspace_id == workspace_id,
            TaskEvidenceAttachment.task_id == task_id,
            TaskEvidenceAttachment.id == attachment_id,
        )
        .first()
    )
