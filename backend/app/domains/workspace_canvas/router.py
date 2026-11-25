from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.offload import run_db_txn_with_bind
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.workspace_canvas import documents, service, sources
from app.domains.workspace_canvas.events import notify_canvas_changed
from app.domains.workspace_canvas.schemas import (
    CanvasOperation,
    CanvasReceipt,
    CanvasView,
    DocumentSource,
    PlanFilesPage,
    SourcePage,
)

router = APIRouter(prefix="/workspaces/{ws_id}/canvas", tags=["Workspace Canvas"])


@router.get("", response_model=CanvasView)
def get_workspace_canvas(
    ws_id: str, response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CanvasView:
    member = service.require_member(db, ws_id, current_user.id)
    response.headers["Cache-Control"] = "no-store"
    return service.read_canvas(db, ws_id, member)


@router.post("/operations", response_model=CanvasReceipt)
async def submit_canvas_operation(
    ws_id: str, payload: CanvasOperation, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CanvasReceipt:
    bind, actor_id = db.get_bind(), current_user.id
    db.close()
    receipt = await run_db_txn_with_bind(
        bind, lambda session: service.submit_operation(session, ws_id, actor_id, payload)
    )
    await notify_canvas_changed(ws_id)
    return receipt


@router.get("/plan-files", response_model=PlanFilesPage)
def list_canvas_plan_files(
    ws_id: str,
    cursor: str | None = Query(default=None, max_length=36),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanFilesPage:
    member = service.require_member(db, ws_id, current_user.id)
    if "plan_document" not in member.access.source_kinds:
        raise HTTPException(status_code=403, detail="No permission to view this canvas source")
    return sources.workspace_plan_files(db, ws_id, cursor)


@router.post("/paragraphs", response_model=SourcePage)
def list_canvas_paragraphs(
    ws_id: str,
    payload: DocumentSource,
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourcePage:
    member = service.require_member(db, ws_id, current_user.id)
    if payload.kind not in member.access.source_kinds:
        raise HTTPException(status_code=403, detail="No permission to view this canvas source")
    try:
        paragraphs = documents.select_document_paragraphs(db, ws_id, payload, q.strip(), page)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail="Document paragraphs are unavailable") from error
    if paragraphs is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return paragraphs
