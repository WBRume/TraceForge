"""
GitHub OAuth 适配器（B-11，首批唯一 provider，拍板 #2）。

全流程仅 3 次 HTTP 调用（设计文档 §1.3 决策 1）：
1. ``POST {TOKEN_ENDPOINT}``     code → access_token
2. ``GET  {USER_ENDPOINT}``      profile → provider_uid / 资料
3. ``GET  {EMAILS_ENDPOINT}``    补全 email + email_verified（仅当 profile 未返回 email）

🔴 安全红线：access_token 只存在于方法局部变量中，用后即弃，
不落库、不写日志、不返回前端（拍板 #9 / K-9）。
"""

import urllib.parse
from typing import Any, Optional

import httpx

from app.domains.auth.errors import OAuthUpstreamError
from app.domains.auth.providers.base import (
    OAuthCodeInvalidError,
    OAuthProfile,
    OAuthProvider,
    _http_client,
    _request_with_retry,
    oauth_setting,
)
from app.domains.auth.providers import register_provider


@register_provider("github")
class GitHubProvider(OAuthProvider):
    """GitHub OAuth 2.0（非 OIDC，无 id_token，故无验签需求）。"""

    name = "github"
    display_name = "GitHub"

    AUTHORIZE_ENDPOINT = "https://github.com/login/oauth/authorize"
    TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
    USER_ENDPOINT = "https://api.github.com/user"
    EMAILS_ENDPOINT = "https://api.github.com/user/emails"
    DEFAULT_SCOPE = "read:user,user:email"  # 最小权限（NFR-S8），可被 OAUTH_GITHUB_SCOPE 覆盖

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        """构造 GitHub 授权页 URL。state 由服务端生成并落 ``oauth_states``（防 CSRF）。"""
        params = {
            "client_id": oauth_setting(self.name, "CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": oauth_setting(self.name, "SCOPE", self.DEFAULT_SCOPE),
        }
        return f"{self.AUTHORIZE_ENDPOINT}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        """code 换 access_token。仅网络错误重试（K-3）；GitHub 业务错误（如
        ``bad_verification_code``）抛 ``OAuthCodeInvalidError`` → 302 ``code_invalid``。"""
        payload = {
            "client_id": oauth_setting(self.name, "CLIENT_ID"),
            "client_secret": oauth_setting(self.name, "CLIENT_SECRET"),
            "code": code,
            "redirect_uri": redirect_uri,
        }

        def _do() -> httpx.Response:
            with _http_client() as client:
                return client.post(
                    self.TOKEN_ENDPOINT,
                    json=payload,
                    headers={"Accept": "application/json"},
                )

        response = _request_with_retry(_do)
        if response.status_code >= 500:
            raise OAuthUpstreamError()
        if response.status_code != 200:
            # 4xx：code 无效 / 凭据配置错误，按 code 失效处理（E-4c）
            raise OAuthCodeInvalidError()
        data = self._parse_json(response)
        access_token = data.get("access_token")
        if not access_token or data.get("error"):
            # GitHub 换 token 失败时返回 200 + {"error": "bad_verification_code", ...}
            raise OAuthCodeInvalidError()
        return str(access_token)

    def fetch_profile(self, access_token: str) -> OAuthProfile:
        """拉取用户资料；profile 未含 email 时调用 /user/emails 补全（E-11 前置）。"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }

        def _do() -> httpx.Response:
            with _http_client() as client:
                return client.get(self.USER_ENDPOINT, headers=headers)

        response = _request_with_retry(_do)
        if response.status_code != 200:
            raise OAuthUpstreamError()
        data = self._parse_json(response)
        provider_uid = data.get("id")
        if provider_uid is None:
            raise OAuthUpstreamError()

        email: Optional[str] = data.get("email")
        email_verified: Optional[bool] = None
        if not email:
            # profile 未返回 email（可能为私密）→ 查 emails 端点取 primary 邮箱
            email, email_verified = self._fetch_primary_email(access_token)

        return OAuthProfile(
            provider_uid=str(provider_uid),
            email=email,
            email_verified=email_verified,
            display_name=data.get("name") or data.get("login"),
            avatar_url=data.get("avatar_url"),
            raw=data,
        )

    def _fetch_primary_email(self, access_token: str) -> tuple[Optional[str], Optional[bool]]:
        """GET /user/emails，取 primary 邮箱及其验证状态；失败不阻断登录（email 可空走路径 C）。"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }

        def _do() -> httpx.Response:
            with _http_client() as client:
                return client.get(self.EMAILS_ENDPOINT, headers=headers)

        try:
            response = _request_with_retry(_do)
        except httpx.HTTPError:
            return None, None
        if response.status_code != 200:
            return None, None
        # GitHub 的 /user/emails 响应是 JSON 数组，而 token/profile 接口返回对象。
        # 先解析合法 JSON，再由调用方校验期望的顶层形状。
        emails: Any = self._parse_json_value(response)
        if not isinstance(emails, list):
            return None, None
        for item in emails:
            if isinstance(item, dict) and item.get("primary") and item.get("email"):
                verified = item.get("verified")
                return str(item["email"]), bool(verified) if verified is not None else None
        return None, None

    @staticmethod
    def _parse_json_value(response: httpx.Response) -> Any:
        """安全解析任意 JSON 值；非法响应按上游错误处理（NFR-U2）。"""
        try:
            data = response.json()
        except ValueError as exc:
            raise OAuthUpstreamError() from exc
        return data

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict:
        """安全解析 JSON 对象；非法响应按上游错误处理（严禁透传原始报文，NFR-U2）。"""
        data = GitHubProvider._parse_json_value(response)
        if not isinstance(data, dict):
            raise OAuthUpstreamError()
        return data
