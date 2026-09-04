"""
系统配置服务：提供带默认值与类型解析的配置读写。
"""

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.domains.system_config.models.system_config import SystemConfig

# 新建工作区时是否启用“项目管理/产品管理”选择功能。
# 开启：按既有流程选择项目与产品，仓库集合由产品版本绑定生成。
# 关闭（默认）：屏蔽项目管理/产品管理页面；新建工作区时直接填写项目与产品名称，
#       并手动选择仓库与各仓库使用的分支。
CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED = "project_product_management_enabled"

# 公开配置项白名单：key -> (默认值, 说明, 解析函数)
_CONFIG_SPECS: Dict[str, Dict[str, Any]] = {
    CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED: {
        "default": "false",
        "description": (
            "新建工作区时是否启用项目管理/产品管理选择功能；"
            "关闭后屏蔽相关页面，改为直接填写项目与产品名称并手动选择仓库分支"
        ),
        "parser": lambda raw: str(raw).strip().lower() in {"1", "true", "yes", "on"},
    },
}


class SystemConfigError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def get_config_value(db: Session, key: str) -> str:
    """返回配置原始字符串值；未设置时返回默认值。未知 key 返回空字符串。"""
    spec = _CONFIG_SPECS.get(key)
    if spec is None:
        raise SystemConfigError(f"Unknown system config: {key}", status_code=404)
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None or str(row.value or "").strip() == "":
        return str(spec["default"])
    return str(row.value)


def get_config_bool(db: Session, key: str) -> bool:
    spec = _CONFIG_SPECS.get(key)
    if spec is None:
        raise SystemConfigError(f"Unknown system config: {key}", status_code=404)
    return bool(spec["parser"](get_config_value(db, key)))


def set_config_value(db: Session, key: str, value: str, updated_by: str = "") -> SystemConfig:
    spec = _CONFIG_SPECS.get(key)
    if spec is None:
        raise SystemConfigError(f"Unknown system config: {key}", status_code=404)
    normalized = str(value or "").strip()
    if normalized == "":
        raise SystemConfigError("config value cannot be empty", status_code=400)
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        row = SystemConfig(
            key=key,
            value=normalized,
            description=spec["description"],
            updated_by=str(updated_by or "") or None,
        )
        db.add(row)
    else:
        row.value = normalized
        row.updated_by = str(updated_by or "") or None
    db.commit()
    db.refresh(row)
    return row


def list_public_configs(db: Session) -> Dict[str, Any]:
    """返回前端可见的配置项（已按类型解析）。"""
    result: Dict[str, Any] = {}
    for key in _CONFIG_SPECS:
        spec = _CONFIG_SPECS[key]
        raw = get_config_value(db, key)
        result[key] = spec["parser"](raw)
    return result
