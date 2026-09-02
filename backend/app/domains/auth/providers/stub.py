"""
Stub OAuth Provider —— 本地 Demo 专用（非三方接入）。

背景：真实三方登录（如 GitHub OAuth App）必须在外网登记回调地址，而内网 /
localhost 环境无法被外部回调。为了在「零申请、零外部回调」的前提下验证
本项目三方登录的全链路，本 provider 在本地模拟一个 IdP：

  authorize_url(state, redirect_uri)
      → 后端自己的模拟授权页  /api/auth/oauth/stub/authorize-redirect
      → 该页直接 302 回回调路由（携带 code + state，模拟用户已同意授权）

其后的 state 校验 / 换 token / ticket 创建 / 三路判定 / 注册绑定 / JWT 签发
全部复用真实后端链路（``oauth_service``），与真实 IdP 逐节点一致，仅
「三方侧」为零网络调用。

🔴 安全：默认关闭（``OAUTH_STUB_ENABLED=false``，见 config.py）。仅本地演示时
置 true；生产环境禁止开启 —— 该 provider 不校验任何真实身份，等于任意免密登录。
"""

import urllib.parse

from app.config import settings
from app.domains.auth.providers import register_provider
from app.domains.auth.providers.base import OAuthProfile, OAuthProvider


@register_provider("stub")
class StubProvider(OAuthProvider):
    """本地模拟 IdP：免申请、免外部回调、全程 localhost 闭环。"""

    name = "stub"
    display_name = "Stub (Demo)"

    def is_configured(self) -> bool:
        """是否启用：仅受 ``OAUTH_STUB_ENABLED`` 开关控制（默认 false）。"""
        return bool(settings.OAUTH_STUB_ENABLED)

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        """返回后端本地模拟授权页 URL（不触网；origin 由回调地址推导，天然适配本机端口）。"""
        parts = urllib.parse.urlsplit(redirect_uri)
        origin = f"{parts.scheme}://{parts.netloc}"
        query = urllib.parse.urlencode({"state": state, "redirect_uri": redirect_uri})
        return f"{origin}/api/auth/oauth/stub/authorize-redirect?{query}"

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        """模拟「code 换 access_token」：固定返回 stub token（无 HTTP）。

        code 参数仅保持与真实 IdP 契约一致；本演示不校验具体值。
        """
        # noqa: ARG001 —— code / redirect_uri 仅为契约占位
        return "stub-access-token"

    def fetch_profile(self, access_token: str) -> OAuthProfile:
        """模拟「拉取三方用户资料」：固定返回 Stub 用户。

        固定邮箱 demo@example.com（RFC 2606 保留演示域名，EmailStr 校验通过）：
        首次走路径 C（补全注册），之后走路径 A（直接登录），一条 demo 即可覆盖两条主判定路径。
        """
        # noqa: ARG001 —— access_token 仅为契约占位
        return OAuthProfile(
            provider_uid="stub-1001",
            email="demo@example.com",
            email_verified=True,
            display_name="Stub Demo User",
            avatar_url=None,
            raw={"source": "stub", "demo": True},
        )