"""资产 ORM → API DTO 映射（asset / task 路由共用）。"""

from __future__ import annotations

from app.domains.asset.models.asset import SddAsset
from app.domains.asset.schemas.asset import AssetResponse


def serialize_asset(asset: SddAsset) -> AssetResponse:
    asset_type = asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type)
    return AssetResponse(
        id=asset.id,
        task_id=asset.task_id,
        workspace_id=asset.workspace_id,
        asset_type=asset_type,
        name=asset.name,
        content_text=asset.content_text,
        content_json=asset.content_json,
        source_ext=asset.source_ext,
        source_mime=asset.source_mime,
        created_at=asset.created_at,
    )
