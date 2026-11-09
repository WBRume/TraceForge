"""资产文档版本的数据查询（document 子包的读侧仓储）。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAsset, SddAssetVersion
from app.domains.task.models.task import SddTask


def list_asset_versions(db: Session, asset_id: str) -> list[SddAssetVersion]:
    return (
        db.query(SddAssetVersion)
        .filter(SddAssetVersion.asset_id == asset_id)
        .order_by(SddAssetVersion.version_no.desc(), SddAssetVersion.created_at.desc())
        .all()
    )


def get_asset_version(db: Session, asset_id: str, version_id: str) -> SddAssetVersion | None:
    return (
        db.query(SddAssetVersion)
        .filter(
            SddAssetVersion.asset_id == asset_id,
            SddAssetVersion.id == version_id,
        )
        .first()
    )


def next_version_no(db: Session, asset_id: str) -> int:
    """Allocate under the asset lock using a current read, even under MySQL REPEATABLE READ."""
    latest = (
        db.query(SddAssetVersion.version_no)
        .filter(SddAssetVersion.asset_id == asset_id)
        .order_by(SddAssetVersion.version_no.desc())
        .with_for_update()
        .first()
    )
    return int(latest[0] if latest else 0) + 1


def task_for_asset(db: Session, asset: SddAsset) -> SddTask:
    task = db.query(SddTask).filter(SddTask.id == asset.task_id).first()
    if not task:
        raise ValueError(f"Task not found for asset {asset.id}")
    return task
