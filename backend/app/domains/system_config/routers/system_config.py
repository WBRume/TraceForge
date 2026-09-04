"""
系统配置 API：读取（登录用户）与更新（管理员）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db, require_admin
from app.domains.auth.models.user import User
from app.domains.system_config.schemas.system_config import SystemConfigUpdate
from app.domains.system_config.services import system_config_service

router = APIRouter(prefix="/system-configs", tags=["System Configs"])


@router.get("")
def get_system_configs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return system_config_service.list_public_configs(db)


@router.put("/{key}")
def update_system_config(
    key: str,
    data: SystemConfigUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        system_config_service.set_config_value(
            db,
            key,
            "true" if data.value else "false",
            updated_by=current_user.id,
        )
    except system_config_service.SystemConfigError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    audit_log(
        action="update_system_config",
        outcome="success",
        resource_type="system_config",
        resource_id=key,
        user_id=current_user.id,
        value=data.value,
    )
    return system_config_service.list_public_configs(db)
