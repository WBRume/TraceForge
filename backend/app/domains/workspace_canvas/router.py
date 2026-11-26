from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.offload import run_db_txn_with_bind
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, Workspace
from app.domains.workspace_canvas import documents, map_queries, quarters, root_tree, service, sources
from app.domains.workspace_canvas.events import notify_canvas_changed
from app.domains.workspace_canvas.quarter_calendar import (
    CanvasCalendarSettings,
    CanvasCalendarView,
    FiscalCalendar,
    FiscalYear,
    QuarterKey,
)
from app.domains.workspace_canvas.read_budget import budgeted_read
from app.domains.workspace_canvas.schemas import (
    CanvasAsset,
    CanvasAssetWindow,
    CanvasBranchQuery,
    CanvasBranchWindow,
    CanvasOperation,
    CanvasReceipt,
    CanvasRootQuery,
    CanvasRootWindow,
    CanvasView,
    DocumentSource,
    PlanFilesPage,
    SourceId,
    SourceKind,
    SourcePage,
)

router = APIRouter(prefix="/workspaces/{ws_id}/canvas", tags=["Workspace Canvas"])


@router.get("", response_model=CanvasView)
def get_workspace_canvas(
    ws_id: str,
    response: Response,
    quarter: QuarterKey | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanvasView:
    member = service.require_member(db, ws_id, current_user.id)
    response.headers["Cache-Control"] = "no-store"
    with budgeted_read(db):
        calendar = quarters.get_calendar(db, ws_id)
        period = calendar.period(quarter) if quarter else calendar.at(datetime.now(UTC))
        return service.read_canvas(db, ws_id, member, calendar, period)


@router.get("/calendar", response_model=CanvasCalendarView)
def get_canvas_calendar(
    ws_id: str,
    year: FiscalYear | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanvasCalendarView:
    member = service.require_member(db, ws_id, current_user.id)
    with budgeted_read(db, lookup=True):
        return quarters.get_calendar(db, ws_id).view(member.can_edit_calendar, year)


@router.put("/calendar", response_model=CanvasCalendarView)
async def update_canvas_calendar(
    ws_id: str,
    settings: CanvasCalendarSettings,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanvasCalendarView:
    bind, actor_id = db.get_bind(), current_user.id
    db.close()

    def save(session):
        if not service.require_member(session, ws_id, actor_id).can_edit_calendar:
            raise HTTPException(403, "CANVAS_CALENDAR_PERMISSION")
        with budgeted_read(session):
            session.query(Workspace).filter(Workspace.id == ws_id).update(
                {Workspace.canvas_calendar: settings.model_dump(mode="json")}
            )
            return FiscalCalendar(settings).view(True)

    result = await run_db_txn_with_bind(bind, save)
    await notify_canvas_changed(ws_id)
    return result


@router.get("/search", response_model=list[CanvasAsset])
def search_canvas_assets(
    ws_id: str,
    q: str = Query(min_length=1, max_length=120),
    kind: SourceKind | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CanvasAsset]:
    member = service.require_member(db, ws_id, current_user.id)
    kinds = [source for source in member.access.source_kinds if kind is None or source == kind]
    with budgeted_read(db, lookup=True):
        if not q.strip():
            return []
        assets = map_queries.search_assets(db, ws_id, kinds, q.strip())
        return sources.assign_quarters(assets, quarters.get_calendar(db, ws_id))


@router.get("/window", response_model=CanvasAssetWindow)
def read_canvas_window(
    ws_id: str,
    kind: SourceKind,
    id: SourceId,
    response: Response,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    quarter: QuarterKey | None = None,
    visible: Annotated[list[map_queries.VisibleAsset] | None, Query(max_length=120)] = None,
    reveal: map_queries.VisibleAsset | None = None,
    children: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanvasAssetWindow:
    member = service.require_member(db, ws_id, current_user.id)
    if kind not in member.access.source_kinds or kind == "plan_document":
        raise HTTPException(404, "Canvas asset not found")
    anchor = sources.reference_for(kind, id)
    response.headers["Cache-Control"] = "no-store"
    with budgeted_read(db):
        calendar = quarters.get_calendar(db, ws_id)
        window = map_queries.read_window(
            db, ws_id, member.access.source_kinds, anchor, cursor, calendar, quarter, visible, reveal, children
        )
        if not window.assets:
            raise HTTPException(404, "Canvas asset not found")
        return window


@router.get("/roots", response_model=CanvasRootWindow)
def read_canvas_roots(
    ws_id: str,
    params: Annotated[CanvasRootQuery, Query()],
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanvasRootWindow:
    member = service.require_member(db, ws_id, current_user.id)
    response.headers["Cache-Control"] = "no-store"
    with budgeted_read(db):
        return root_tree.read_roots(db, ws_id, member.access.source_kinds, quarters.get_calendar(db, ws_id), params)


@router.get("/branches", response_model=CanvasBranchWindow)
def read_canvas_branch(
    ws_id: str,
    params: Annotated[CanvasBranchQuery, Query()],
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanvasBranchWindow:
    member = service.require_member(db, ws_id, current_user.id)
    response.headers["Cache-Control"] = "no-store"
    with budgeted_read(db):
        return quarters.read_branch(db, ws_id, member.access.source_kinds, quarters.get_calendar(db, ws_id), params)


@router.post("/operations", response_model=CanvasReceipt)
async def submit_canvas_operation(
    ws_id: str, payload: CanvasOperation, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CanvasReceipt:
    bind, actor_id = db.get_bind(), current_user.id
    db.close()

    def persist(session):
        with budgeted_read(session):
            return service.submit_operation(session, ws_id, actor_id, payload)

    receipt = await run_db_txn_with_bind(bind, persist)
    await notify_canvas_changed(ws_id)
    return receipt


@router.get("/plan-files", response_model=PlanFilesPage)
def list_canvas_plan_files(
    ws_id: str,
    cursor: str | None = Query(default=None, max_length=36),
    task_id: list[SourceId] | None = Query(default=None, max_length=12),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanFilesPage:
    member = service.require_member(db, ws_id, current_user.id)
    if "plan_document" not in member.access.source_kinds:
        raise HTTPException(status_code=403, detail="No permission to view this canvas source")
    return sources.workspace_plan_files(db, ws_id, cursor, task_id)


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
