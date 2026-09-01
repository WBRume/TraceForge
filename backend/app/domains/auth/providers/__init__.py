"""
OAuth Provider 注册表（B-09，NFR-M1 落地，对应设计文档 §4.3）。

机制：装饰器注册，模块导入即生效。``get_provider`` 负责两级校验：
1. 未注册 → ``OAuthProviderNotFoundError``（404 OAUTH_PROVIDER_NOT_FOUND）
2. 已注册但未配置 client_id/secret → ``OAuthProviderDisabledError``（404 OAUTH_PROVIDER_DISABLED）

新增 provider 只需两步：新增适配文件 + 本文件底部加一行 import（见 §1.4）。
"""

from typing import TYPE_CHECKING

from app.domains.auth.errors import (
    OAuthProviderDisabledError,
    OAuthProviderNotFoundError,
)
from app.domains.auth.providers.base import OAuthProvider

if TYPE_CHECKING:  # 仅为类型标注，避免运行时循环导入
    from app.domains.auth.schemas.oauth import ProviderInfo

# 模块级注册表：provider name → 适配类
PROVIDER_REGISTRY: dict[str, type[OAuthProvider]] = {}


def register_provider(name: str):
    """装饰器：把 provider 适配类注册进注册表。"""

    def _wrap(cls: type[OAuthProvider]) -> type[OAuthProvider]:
        PROVIDER_REGISTRY[name] = cls
        return cls

    return _wrap


def get_provider(name: str) -> OAuthProvider:
    """按 name 取 provider 实例（全同步，无 IO）。"""
    cls = PROVIDER_REGISTRY.get(name)
    if cls is None:
        raise OAuthProviderNotFoundError(provider=name)
    provider = cls()
    if not provider.is_configured():
        raise OAuthProviderDisabledError(provider=name)
    return provider


def list_enabled_providers() -> list["ProviderInfo"]:
    """遍历注册表，按配置过滤（NFR-M2：未配置 client_id 的不出现）。"""
    from app.domains.auth.schemas.oauth import ProviderInfo  # 局部导入避免循环

    providers: list[ProviderInfo] = []
    for name, cls in PROVIDER_REGISTRY.items():
        instance = cls()
        if not instance.is_configured():
            continue
        providers.append(
            ProviderInfo(
                name=instance.name,
                display_name=instance.display_name,
                authorize_path=f"/api/auth/oauth/{instance.name}/authorize",
                icon_key=instance.name,
            )
        )
    return providers


# ── 底部集中 import 触发注册（新增 provider 时只加这一行）──
from . import github  # noqa: E402,F401
