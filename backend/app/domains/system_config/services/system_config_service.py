"""
系统配置服务：提供带默认值与类型解析的配置读写。
"""

import os
import re
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.domains.system_config.models.system_config import SystemConfig

# 新建工作区时是否启用“项目管理/产品管理”选择功能。
# 开启：按既有流程选择项目与产品，仓库集合由产品版本绑定生成。
# 关闭（默认）：屏蔽项目管理/产品管理页面；新建工作区时直接填写项目与产品名称，
#       并手动选择仓库与各仓库使用的分支。
CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED = "project_product_management_enabled"

# 工作区根目录。为空时保持原有逻辑：用户创建工作区时手动输入根目录。
# 设置后：新建工作区路径默认为 根目录/workspace/工作区名称，
#       且仅允许位于 根目录/workspace 之内。
CONFIG_WORKSPACE_ROOT_DIR = "workspace_root_dir"

# 工作区根目录下固定的工作区容器目录名
WORKSPACE_BASE_SEGMENT = "workspace"


def _validate_workspace_root_dir(value: str) -> str:
    """校验工作区根目录：必须为绝对路径，且不能是文件系统根目录。"""
    if not value:
        return value
    if not os.path.isabs(value):
        raise SystemConfigError("workspace_root_dir must be an absolute path", status_code=400)
    expanded = os.path.abspath(os.path.expanduser(value))
    if os.path.dirname(expanded) == expanded:
        raise SystemConfigError(
            "workspace_root_dir cannot be a filesystem root directory", status_code=400
        )
    return value


def _workspace_root_dir_env_default() -> str:
    """工作区根目录的 env 层默认值（backend/.env 的 WORKSPACE_ROOT_DIR）。

    优先级：系统配置表（界面保存）> env 默认值 > 空（未启用）。
    """
    from app.config import settings

    return str(getattr(settings, "WORKSPACE_ROOT_DIR", "") or "").strip()


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
    CONFIG_WORKSPACE_ROOT_DIR: {
        "default": "",
        "default_fn": _workspace_root_dir_env_default,
        "description": (
            "工作区根目录；env（WORKSPACE_ROOT_DIR）提供默认值，"
            "界面保存的配置非空时覆盖 env 默认值，清空后回退 env 默认值；"
            "生效时新建工作区路径默认为 根目录/workspace/工作区名称，"
            "且仅允许位于 根目录/workspace 之内"
        ),
        "type": "str",
        "allow_empty": True,
        "parser": lambda raw: str(raw).strip(),
        "validator": _validate_workspace_root_dir,
    },
}


class SystemConfigError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _get_spec(key: str) -> Dict[str, Any]:
    spec = _CONFIG_SPECS.get(key)
    if spec is None:
        raise SystemConfigError(f"Unknown system config: {key}", status_code=404)
    return spec


def is_string_config(key: str) -> bool:
    """该配置项是否为字符串类型（bool 配置以外的类型均视为字符串）。"""
    return _get_spec(key).get("type") == "str"


def _resolve_spec_default(spec: Dict[str, Any]) -> str:
    """解析配置默认值：优先 default_fn（env 层），否则静态 default。"""
    default_fn = spec.get("default_fn")
    if default_fn is not None:
        return str(default_fn() or "")
    return str(spec.get("default", ""))


def get_config_value(db: Session, key: str) -> str:
    """返回配置原始字符串值；未设置时返回默认值（env 层）。未知 key 抛出 SystemConfigError。"""
    spec = _get_spec(key)
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None or str(row.value or "").strip() == "":
        return _resolve_spec_default(spec)
    return str(row.value)


def get_config_bool(db: Session, key: str) -> bool:
    spec = _get_spec(key)
    return bool(spec["parser"](get_config_value(db, key)))


def get_config_str(db: Session, key: str) -> str:
    """返回字符串型配置的去除首尾空白后的值；未设置时返回空字符串。"""
    spec = _get_spec(key)
    return str(spec["parser"](get_config_value(db, key)))


def set_config_value(db: Session, key: str, value: str, updated_by: str = "") -> SystemConfig:
    spec = _get_spec(key)
    normalized = str(value or "").strip()
    if normalized == "" and not spec.get("allow_empty"):
        raise SystemConfigError("config value cannot be empty", status_code=400)
    validator = spec.get("validator")
    if validator is not None:
        validator(normalized)
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
