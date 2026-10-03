"""asset.routers.assets.catalog domain operations."""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.asset.schemas.asset import AssetListResponse, AssetResponse
from app.domains.asset.services import asset_service

from app.domains.asset.routers.assets.transport import ReviewRoute
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import serialization as asset_review_serialization



router = APIRouter(route_class=ReviewRoute)



@router.get("", response_model=AssetListResponse)
def search_assets(
    ws_id: str,
    task_id: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    creator_id: Optional[str] = Query(None),
    include_unfinished_task_spec: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    items, total = asset_service.search_assets(
        db=db,
        workspace_id=ws_id,
        task_id=task_id,
        asset_type=asset_type,
        keyword=keyword,
        creator_id=creator_id,
        include_unfinished_task_spec=include_unfinished_task_spec,
        page=page,
        page_size=page_size,
    )
    return AssetListResponse(items=[asset_review_serialization._serialize_asset(item) for item in items], total=total)


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(
    ws_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset_review_serialization._serialize_asset(asset)
