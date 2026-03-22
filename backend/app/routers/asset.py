"""
Asset API Router
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.services import asset_service
from app.schemas.asset import AssetListResponse, AssetResponse

router = APIRouter(prefix="/workspaces/{ws_id}/assets", tags=["Assets"])

@router.get("", response_model=AssetListResponse)
def search_assets(
    ws_id: str,
    task_id: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    creator_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """搜索并分页获取工作区下的资产列表"""
    items, total = asset_service.search_assets(
        db=db,
        workspace_id=ws_id,
        task_id=task_id,
        asset_type=asset_type,
        keyword=keyword,
        creator_id=creator_id,
        page=page,
        page_size=page_size,
    )
    return AssetListResponse(items=items, total=total)


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(
    ws_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取单个资产详情"""
    asset = asset_service.get_asset(db, asset_id, ws_id)
    if not asset:
        raise HTTPException(status_code=404, detail="找不到该资产")
    return asset
