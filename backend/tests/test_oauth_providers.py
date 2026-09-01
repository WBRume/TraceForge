"""
T03 Provider 可插拔性与 GitHub 适配用例（B-22）。

- 可插拔性（NFR-M1）：注册一个 mock provider，验证 registry / get_provider /
  authorize / callback 全链路可用，路由与判定逻辑零改动
- GitHub 适配（mock httpx 上游）：正常 profile / 无 email 走 /user/emails 补全 /
  code 失效（E-4c）/ 上游 5xx（E-9）/ 非法 JSON
"""

import httpx
import pytest

from app.config import settings
from app.domains.auth.errors import (
    ERR_OAUTH_PROVIDER_DISABLED,
    ERR_OAUTH_PROVIDER_NOT_FOUND,
    OAuthAPIError,
    OAuthProviderDisabledError,
    OAuthProviderNotFoundError,
    OAuthUpstreamError,
)
from app.domains.auth.providers import (
    PROVIDER_REGISTRY,
    get_provider,
    list_enabled_providers,
    register_provider,
)
from app.domains.auth.providers.base import (
    OAuthCodeInvalidError,
    OAuthProfile,
    OAuthProvider,
)
from app.domains.auth.services import oauth_service

from tests.conftest import github_profile, make_user, run_login_flow


# ══════════════════ 可插拔性（NFR-M1） ══════════════════

@register_provider("mockcorp")
class MockCorpProvider(OAuthProvider):
    """测试专用 mock provider：不触网、免配置（is_configured 恒真）、固定 profile。

    模拟真实新增 provider 的最小接入面：仅实现 3 个抽象方法 + 装饰器注册，
    路由 / 判定逻辑 / 数据模型零改动（NFR-M1）。
    """

    name = "mockcorp"
    display_name = "MockCorp"

    def is_configured(self) -> bool:
        return True

    def resolve_redirect_uri(self, client_type: str, loopback_port=None) -> str:
        return "http://frontend.test/oauth/callback/mockcorp"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return f"https://mockcorp.example/authorize?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        return "mockcorp-access-token"

    def fetch_profile(self, access_token: str) -> OAuthProfile:
        return OAuthProfile(
            provider_uid="mc-0001",
            email="mc-user@mockcorp.example",
            email_verified=True,
            display_name="MC User",
            raw={"source": "mockcorp"},
        )


@pytest.fixture()
def mockcorp_configured():
    """每用例重新注册（装饰器注册仅发生在模块导入时一次）；结束即注销避免污染。"""
    PROVIDER_REGISTRY["mockcorp"] = MockCorpProvider
    yield
    PROVIDER_REGISTRY.pop("mockcorp", None)


def test_registry_and_get_provider(mockcorp_configured):
    assert "mockcorp" in PROVIDER_REGISTRY
    provider = get_provider("mockcorp")
    assert isinstance(provider, MockCorpProvider)
    assert provider.name == "mockcorp"


def test_enabled_provider_list_includes_mockcorp(mockcorp_configured):
    names = [p.name for p in list_enabled_providers()]
    assert "mockcorp" in names


def test_new_provider_full_flow_with_zero_router_changes(db, mockcorp_configured):
    """新 provider 全链路：authorize → callback → 三路判定，路由/判定/模型零改动。"""
    params = oauth_service.build_authorize_url(
        db, provider="mockcorp", intent="login", client_type="web", user_id=None
    )
    assert params.authorize_url.startswith("https://mockcorp.example/authorize")

    cb = oauth_service.handle_callback(
        db, provider="mockcorp", code="mc-code", state=params.state, error=None
    )
    # 无本地用户 → 路径 C（注册判定逻辑对新 provider 完全复用）
    parsed = dict(
        fragment.split("=", 1) for fragment in cb.redirect_url.split("?", 1)[1].split("&")
    )
    assert parsed["status"] == "REGISTER_REQUIRED"
    assert parsed["ticket"]


def test_provider_not_registered_returns_404():
    with pytest.raises(OAuthProviderNotFoundError) as exc_info:
        get_provider("does-not-exist")
    assert exc_info.value.code == ERR_OAUTH_PROVIDER_NOT_FOUND
    assert exc_info.value.status_code == 404


def test_provider_registered_but_not_configured_returns_404(monkeypatch):
    """已注册但未配置 client_id/secret → OAUTH_PROVIDER_DISABLED（NFR-M2）。"""
    monkeypatch.delattr(settings, "OAUTH_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", "whatever")
    with pytest.raises(OAuthProviderDisabledError) as exc_info:
        get_provider("github")
    assert exc_info.value.code == ERR_OAUTH_PROVIDER_DISABLED
    assert exc_info.value.status_code == 404


# ══════════════════ GitHub 适配（mock httpx 上游） ══════════════════

def test_github_fetch_profile_with_email(github_mock):
    github_mock.user_response = (
        200,
        {
            "id": 1001,
            "login": "octo",
            "name": "Octo Cat",
            "email": "octo@example.com",
            "avatar_url": "https://avatars.example/1001.png",
        },
    )
    provider = get_provider("github")
    profile = provider.fetch_profile("token-1")
    assert profile.provider_uid == "1001"
    assert profile.email == "octo@example.com"
    assert profile.display_name == "Octo Cat"
    # profile 自带 email 时不再调用 /user/emails
    assert all("emails" not in url for _, url in github_mock.requests)


def test_github_fetch_profile_without_email_falls_back_to_emails_endpoint(github_mock):
    """E-11 前置：profile 无 email → GET /user/emails 取 primary 邮箱。"""
    github_mock.user_response = (200, {"id": 1002, "login": "noemail", "email": None})
    github_mock.emails_response = (
        200,
        [
            {"email": "secondary@example.com", "primary": False, "verified": False},
            {"email": "primary@example.com", "primary": True, "verified": True},
        ],
    )
    provider = get_provider("github")
    profile = provider.fetch_profile("token-2")
    assert profile.email == "primary@example.com"
    assert profile.email_verified is True
    # 确实触达了 /user/emails
    assert any("user/emails" in url for _, url in github_mock.requests)


def test_github_emails_endpoint_failure_does_not_block(github_mock):
    """emails 端点失败不阻断（email 可空 → 路径 C 手填）。"""
    github_mock.user_response = (200, {"id": 1003, "login": "noemail", "email": None})
    github_mock.emails_response = (500, {"message": "boom"})
    provider = get_provider("github")
    profile = provider.fetch_profile("token-3")
    assert profile.email is None
    assert profile.provider_uid == "1003"


def test_github_exchange_code_200_with_error_body_raises_code_invalid(github_mock):
    """GitHub 换 token 失败返回 200 + error 字段 → OAuthCodeInvalidError（E-4c）。"""
    github_mock.token_response = (
        200,
        {"error": "bad_verification_code", "error_description": "The code passed is incorrect"},
    )
    provider = get_provider("github")
    with pytest.raises(OAuthCodeInvalidError):
        provider.exchange_code("bad-code", "http://frontend.test/oauth/callback/github")


def test_github_exchange_code_4xx_raises_code_invalid(github_mock):
    github_mock.token_response = (400, {"error": "invalid_request"})
    provider = get_provider("github")
    with pytest.raises(OAuthCodeInvalidError):
        provider.exchange_code("bad-code", "http://frontend.test/oauth/callback/github")


def test_github_exchange_code_5xx_raises_upstream_error(github_mock):
    """E-9：上游 5xx → OAuthUpstreamError（502），严禁透传原始错误。"""
    github_mock.token_response = (502, {"message": "upstream down"})
    provider = get_provider("github")
    with pytest.raises(OAuthUpstreamError) as exc_info:
        provider.exchange_code("code", "http://frontend.test/oauth/callback/github")
    assert exc_info.value.status_code == 502
    assert exc_info.value.code == "OAUTH_UPSTREAM_ERROR"


def test_github_fetch_profile_non_200_raises_upstream_error(github_mock):
    github_mock.user_response = (500, {"message": "boom"})
    provider = get_provider("github")
    with pytest.raises(OAuthUpstreamError):
        provider.fetch_profile("token-4")


def test_github_fetch_profile_invalid_json_raises_upstream_error(github_mock):
    """非法 JSON 响应按上游错误处理（NFR-U2，不透传原始报文）。"""
    github_mock.raw_user_content = b"<html>not json</html>"
    provider = get_provider("github")
    with pytest.raises(OAuthUpstreamError):
        provider.fetch_profile("token-5")


def test_github_callback_maps_code_invalid_to_302(db, github_mock):
    """E-4c 全链路：callback 中 code 失效 → 302 error=code_invalid。"""
    make_user(db, email="seed@example.com", password="Seed-Pass-1")
    github_mock.token_response = (200, {"error": "bad_verification_code"})

    params = oauth_service.build_authorize_url(
        db, provider="github", intent="login", client_type="web", user_id=None
    )
    cb = oauth_service.handle_callback(
        db, provider="github", code="bad-code", state=params.state, error=None
    )
    query = dict(
        fragment.split("=", 1) for fragment in cb.redirect_url.split("?", 1)[1].split("&")
    )
    assert query["error"] == "code_invalid"
    assert "ticket" not in query


def test_github_authorize_url_contains_state_and_scope(github_mock):
    provider = get_provider("github")
    url = provider.authorize_url("state-xyz", "http://frontend.test/cb")
    assert "client_id=test-client-id" in url
    assert "state=state-xyz" in url
    assert "scope=read%3Auser%2Cuser%3Aemail" in url


def test_github_callback_access_denied_maps_to_semantic_error(db, github_mock):
    """E-4a：用户取消授权（error=access_denied）→ 归并为语义化错误，不透传原文。"""
    cb = oauth_service.handle_callback(
        db, provider="github", code=None, state=None, error="access_denied"
    )
    assert "error=access_denied" in cb.redirect_url
