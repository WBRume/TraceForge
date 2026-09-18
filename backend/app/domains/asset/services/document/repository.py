"""资产文档版本的数据查询（document 子包的读侧仓储）。"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAsset, SddAssetVersion
from app.domains.task.models.task import SddTask


def list_asset_versions(db: Session, asset_id: str) -> List[SddAssetVersion]:
    return (
        db.query(SddAssetVersion)
        .filter(SddAssetVersion.asset_id == asset_id)
        .order_by(SddAssetVersion.version_no.desc(), SddAssetVersion.created_at.desc())
        .all()
    )


def get_asset_version(db: Session, asset_id: str, version_id: str) -> Optional[SddAssetVersion]:
    return (
        db.query(SddAssetVersion)
        .filter(
            SddAssetVersion.asset_id == asset_id,
            SddAssetVersion.id == version_id,
        )
        .first()
    )


def next_version_no(db: Session, asset_id: str) -> int:
    max_no = (
        db.query(func.max(SddAssetVersion.version_no))
        .filter(SddAssetVersion.asset_id == asset_id)
        .scalar()
    )
    return int(max_no or 0) + 1


def task_for_asset(db: Session, asset: SddAsset) -> SddTask:
    task = db.query(SddTask).filter(SddTask.id == asset.task_id).first()
    if not task:
        raise ValueError(f"Task not found for asset {asset.id}")
    return task
