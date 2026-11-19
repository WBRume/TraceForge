"""HTTP endpoints for the current user's document draft."""

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.asset.routers.assets.transport import ReviewRoute, _get_db_bind, _run_asset_route_db_txn
from app.domains.asset.schemas.asset import AssetDraftResponse, AssetDraftSave, AssetDraftState, AssetVersionResponse
from app.domains.asset.services.document.docx import DOCX_MIME
from app.domains.asset.services.review import drafts, serialization
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.auth.models.user import User
from app.domains.task.services import task_cli_state_service

router = APIRouter(route_class=ReviewRoute)


@router.get("/{asset_id}/draft", response_model=AssetDraftResponse | None)
def get_draft(ws_id: str, asset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return drafts.read_draft(db, ws_id, asset_id, user.id)


@router.get("/{asset_id}/draft/file")
def get_draft_file(
    ws_id: str,
    asset_id: str,
    revision: int = Query(ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    content = drafts.read_draft_docx(db, ws_id, asset_id, user.id, revision)
    return Response(content, media_type=DOCX_MIME, headers={"Cache-Control": "private, no-store"})


@router.put("/{asset_id}/draft", response_model=AssetDraftResponse)
async def put_draft(
    ws_id: str,
    asset_id: str,
    data: AssetDraftSave,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
    return await _run_asset_route_db_txn(
        db, _get_db_bind(db), lambda session: drafts.save_draft(session, ws_id, asset_id, user_id, data)
    )


@router.delete("/{asset_id}/draft", status_code=204)
async def delete_draft(
    ws_id: str,
    asset_id: str,
    data: AssetDraftState,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
    await _run_asset_route_db_txn(
        db, _get_db_bind(db), lambda session: drafts.discard_draft(session, ws_id, asset_id, user_id, data)
    )


@router.post("/{asset_id}/draft/publish", response_model=AssetVersionResponse, status_code=201)
async def post_publish(
    ws_id: str,
    asset_id: str,
    data: AssetDraftState,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id

    def publish(session):
        version, task_id = drafts.publish_draft(session, ws_id, asset_id, user_id, data)
        return serialization._serialize_version(version), task_id

    version, task_id = await _run_asset_route_db_txn(db, _get_db_bind(db), publish)
    db.close()
    await task_cli_state_service.publish_bootstrap_snapshot(task_id)
    await asset_discussion_ws_manager.broadcast(
        asset_id, {"type": "version_applied", "asset_id": asset_id, "version": version.model_dump(mode="json")}
    )
    return version
