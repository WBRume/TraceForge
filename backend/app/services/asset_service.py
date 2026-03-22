"""
资产检索服务
"""

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from app.models.asset import SddAsset


def search_assets(
    db: Session,
    workspace_id: str,
    task_id: Optional[str] = None,
    asset_type: Optional[str] = None,
    keyword: Optional[str] = None,
    creator_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddAsset], int]:
    query = db.query(SddAsset).filter(SddAsset.workspace_id == workspace_id)

    if task_id:
        query = query.filter(SddAsset.task_id == task_id)
    if asset_type:
        query = query.filter(SddAsset.asset_type == asset_type)
    if creator_id:
        query = query.filter(SddAsset.creator_id == creator_id)
    if keyword:
        query = query.filter(
            SddAsset.name.contains(keyword) | SddAsset.content_text.contains(keyword)
        )

    total = query.count()
    items = (
        query.order_by(SddAsset.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_asset(db: Session, asset_id: str, workspace_id: str) -> Optional[SddAsset]:
    return (
        db.query(SddAsset)
        .filter(SddAsset.id == asset_id, SddAsset.workspace_id == workspace_id)
        .first()
    )
