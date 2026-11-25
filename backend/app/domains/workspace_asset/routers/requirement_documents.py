from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocumentLink
from app.domains.workspace_asset.routers.workspace_asset import _verify_manage_requirements, _verify_view_assets
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.requirements import documents
from app.domains.workspace_asset.services.requirements.queries import get_requirement
from app.domains.workspace_asset.services.requirements.segmentation import parse_requirement_document
from app.domains.workspace_canvas.documents import plan_blocks
from app.domains.workspace_canvas.events import notify_canvas_changed

router = APIRouter(prefix="/workspaces/{ws_id}/workspace-assets", tags=["requirement-documents"])
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def _require_requirement(db: Session, workspace_id: str, requirement_id: str) -> None:
    if not get_requirement(db, workspace_id, requirement_id):
        raise HTTPException(404, "Requirement not found")


@router.get("/requirements/{requirement_id}/documents")
def list_documents(
    ws_id: str, requirement_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _verify_view_assets(ws_id, user, db)
    _require_requirement(db, ws_id, requirement_id)
    return {"items": documents.requirement_documents(db, ws_id, requirement_id)}


@router.post("/requirements/{requirement_id}/documents", status_code=201)
def upload_document(
    ws_id: str,
    requirement_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, user, db)
    _require_requirement(db, ws_id, requirement_id)
    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "Requirement documents must be at most 10 MiB")
    filename = file.filename or ""
    try:
        parsed = parse_requirement_document(filename, content)
    except WorkspaceAssetError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    document = documents.store_document(
        db, ws_id, user.id, [requirement_id], filename, parsed["normalized_markdown"], content
    )
    db.commit()
    background.add_task(notify_canvas_changed, ws_id)
    return {"id": document.id, "name": document.filename}


@router.put("/requirements/{requirement_id}/documents/task-assets/{asset_id}")
def attach_task_document(
    ws_id: str,
    requirement_id: str,
    asset_id: str,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, user, db)
    _require_requirement(db, ws_id, requirement_id)
    link = documents.attach_task_document(db, ws_id, requirement_id, asset_id, user.id)
    if link is None:
        raise HTTPException(404, "Task document not found")
    db.commit()
    background.add_task(notify_canvas_changed, ws_id)
    return {"link_id": link.id}


@router.delete("/requirements/{requirement_id}/documents/{link_id}", status_code=204)
def detach_document(
    ws_id: str,
    requirement_id: str,
    link_id: str,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, user, db)
    link = (
        documents.requirement_links(db, ws_id)
        .filter(SddRequirementDocumentLink.requirement_id == requirement_id, SddRequirementDocumentLink.id == link_id)
        .one_or_none()
    )
    if link is None:
        raise HTTPException(404, "Requirement document link not found")
    db.delete(link)
    db.commit()
    background.add_task(notify_canvas_changed, ws_id)
    return Response(status_code=204)


@router.get("/requirement-documents/{document_id}")
def read_document(
    ws_id: str,
    document_id: str,
    block: str | None = Query(default=None, max_length=64),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, user, db)
    document = documents.get_document(db, ws_id, document_id)
    if document is None:
        raise HTTPException(404, "Requirement document not found")
    focus = plan_blocks(document.markdown).get(block) if block else None
    return {"id": document.id, "name": document.filename, "markdown": document.markdown, "focus_text": focus}


@router.get("/requirement-documents/{document_id}/download")
def download_document(
    ws_id: str, document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _verify_view_assets(ws_id, user, db)
    document = documents.get_document(db, ws_id, document_id)
    if document is None:
        raise HTTPException(404, "Requirement document not found")
    content, filename = document.content, document.filename
    if content is None:
        content = document.markdown.encode("utf-8")
        filename = f"{PurePosixPath(filename).stem}.md"
    return Response(
        content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"},
    )
