"""
资产检索服务
"""

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.task.models.task import SddTask, TaskStatus


def search_assets(
    db: Session,
    workspace_id: str,
    task_id: Optional[str] = None,
    asset_type: Optional[str] = None,
    keyword: Optional[str] = None,
    creator_id: Optional[str] = None,
    include_unfinished_task_spec: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddAsset], int]:
    query = (
        db.query(SddAsset)
        .join(SddTask, SddTask.id == SddAsset.task_id)
        .filter(SddAsset.workspace_id == workspace_id)
    )

    if not include_unfinished_task_spec:
        query = query.filter(
            ~(
                (SddAsset.asset_type == AssetType.SPEC)
                & (SddTask.status != TaskStatus.DONE)
            )
        )

    if task_id:
        query = query.filter(SddAsset.task_id == task_id)
    if asset_type:
        try:
            normalized_type = asset_type if isinstance(asset_type, AssetType) else AssetType(asset_type)
        except ValueError:
            return [], 0
        query = query.filter(SddAsset.asset_type == normalized_type)
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


def get_task_asset_by_type(
    db: Session,
    *,
    task_id: str,
    asset_type: AssetType | str,
) -> Optional[SddAsset]:
    normalized = asset_type if isinstance(asset_type, AssetType) else AssetType(asset_type)
    return (
        db.query(SddAsset)
        .filter(
            SddAsset.task_id == task_id,
            SddAsset.asset_type == normalized,
        )
        .order_by(SddAsset.created_at.asc())
        .first()
    )
