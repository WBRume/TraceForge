"""
OAuth 三方登录测试基础设施（T03 / B-19）。

约定（沿用 tests/ 既有风格）：
- SQLite 内存库（StaticPool）+ ``get_db`` 依赖覆盖 —— 绝不连 MySQL 主库；
- ``github_mock``：用 ``httpx.MockTransport`` 替换 ``GitHubProvider`` 的
  ``_http_client`` 工厂，可编程模拟 GitHub 上游三个端点
  （POST access_token / GET /user / GET /user/emails）；
- ``client``：最小 FastAPI 应用，只挂 OAuth 路由 + ``OAuthAPIError``
  统一异常 handler（与 main.py B-16 的注册方式一致）。
"""

import os
import sys
import urllib.parse
from typing import Optional

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# 补全 ORM mapper / FK 注册表：User 及各域模型的 relationship / ForeignKey
# 指向跨域表，必须全量导入 models 包后才能 create_all（与生产 app 全量加载等价）
import importlib  # noqa: E402
import pkgutil  # noqa: E402

from app import domains as _domains  # noqa: E402

for _name in [n for _, n, _ in pkgutil.iter_modules(_domains.__path__)]:
    try:
        _models_pkg = importlib.import_module(f"app.domains.{_name}.models")
    except ModuleNotFoundError:
        continue
    # models 可能是单文件模块（无 __path__），导入本身即完成注册
    if not hasattr(_models_pkg, "__path__"):
        continue
    for _, _mod, _ in pkgutil.walk_packages(
        _models_pkg.__path__, prefix=f"app.domains.{_name}.models."
    ):
        importlib.import_module(_mod)

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.dependencies import get_current_user, get_db  # noqa: E402
from app.domains.auth.errors import OAuthAPIError, oauth_api_error_handler  # noqa: E402
from app.domains.auth.models.oauth import OAuthIdentity  # noqa: E402
from app.domains.auth.models.user import User  # noqa: E402
from app.domains.auth.routers import auth as auth_router_module  # noqa: E402
from app.domains.auth.routers import oauth as oauth_router_module  # noqa: E402
from app.domains.auth.services import auth_service  # noqa: E402


# ══════════════════ 数据库 fixtures ══════════════════

@pytest.fixture()
def db() -> Session:
    """每用例独立的 SQLite 内存库；create_all 覆盖全部已注册模型。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    # 与生产 SessionLocal 一致（app/database.py：默认 expire_on_commit=True）。
    # oauth_service 的 ticket 释放逻辑依赖 commit 后重查刷新属性，
    # 测试会话不可改用 expire_on_commit=False，否则语义失真。
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ══════════════════ GitHub 上游 mock ══════════════════

class GitHubUpstreamMock:
    """可编程 GitHub 上游模拟器：按 URL 分发预置 (status, json) 响应。

    属性（测试用例直接赋值即可改变上游行为）：
    - ``token_response``   POST /login/oauth/access_token
    - ``user_response``    GET  /user
    - ``emails_response``  GET  /user/emails
    - ``raw_user_content`` 非空时 /user 返回原始字节（模拟非法 JSON）
    """

    def __init__(self) -> None:
        self.token_response: tuple = (200, {"access_token": "gho_mock_token"})
        self.user_response: tuple = (200, {"id": 9001})
        self.emails_response: tuple = (200, [])
        self.raw_user_content: Optional[bytes] = None
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, str(request.url)))
        if request.url.path.endswith("/access_token"):
            status, payload = self.token_response
            return httpx.Response(status, json=payload)
        if request.url.path == "/user/emails":
            status, payload = self.emails_response
            return httpx.Response(status, json=payload)
        if request.url.path == "/user":
            if self.raw_user_content is not None:
                return httpx.Response(200, content=self.raw_user_content)
            status, payload = self.user_response
            return httpx.Response(status, json=payload)
        return httpx.Response(404, json={"message": "unexpected endpoint"})


@pytest.fixture()
def github_mock(monkeypatch) -> GitHubUpstreamMock:
    """替换 github provider 的 http client 工厂，并配置 OAuth_GITHUB_* 最小配置集。"""
    mock = GitHubUpstreamMock()

    def _fake_http_client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(mock.handler))

    monkeypatch.setattr(
        "app.domains.auth.providers.github._http_client", _fake_http_client
    )
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(
        settings,
        "OAUTH_GITHUB_REDIRECT_URI_WEB",
        "http://frontend.test/oauth/callback/github",
    )
    return mock


@pytest.fixture(autouse=True)
def _stub_disabled_in_tests(monkeypatch):
    """stub 仅本地 Demo 用；测试环境恒定关闭它，避免 backend/.env 的 OAUTH_STUB_ENABLED=true 泄漏进用例。

    需要验证 stub 的用例（test_oauth_stub_demo.py）在自己的 fixture 中显式置 true。
    """
    monkeypatch.setattr(settings, "OAUTH_STUB_ENABLED", False)


# ══════════════════ FastAPI app / TestClient ══════════════════

@pytest.fixture()
def app(db: Session) -> FastAPI:
    """仅挂 OAuth 路由的最小应用；get_db 指向 SQLite 内存库。"""
    test_app = FastAPI()
    test_app.include_router(oauth_router_module.router, prefix="/api")
    test_app.add_exception_handler(OAuthAPIError, oauth_api_error_handler)
    test_app.dependency_overrides[get_db] = lambda: db
    return test_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def full_app(db: Session) -> FastAPI:
    """auth + oauth 双路由应用：``/api/auth/me`` 的 ``bound_providers`` 需要 auth 路由。

    挂载方式与 ``app/main.py`` 一致（两个 router 均 ``prefix="/api"`` +
    注册 ``OAuthAPIError`` handler），因此 URL 与生产环境逐字符相同。
    """
    test_app = FastAPI()
    test_app.include_router(auth_router_module.router, prefix="/api")
    test_app.include_router(oauth_router_module.router, prefix="/api")
    test_app.add_exception_handler(OAuthAPIError, oauth_api_error_handler)
    test_app.dependency_overrides[get_db] = lambda: db
    return test_app


@pytest.fixture()
def full_client(full_app: FastAPI) -> TestClient:
    return TestClient(full_app, follow_redirects=False)


def auth_headers(user: User) -> dict[str, str]:
    """用应用自身的 ``JWT_SECRET_KEY`` 签发 access token 的 Authorization 头。

    刻意复用 ``auth_service.create_access_token``（与 ``issue_token_pair`` 同一
    实现），确保 ``get_current_user`` 的解码路径与生产完全一致。
    """
    return {"Authorization": f"Bearer {auth_service.create_access_token(user.id)}"}


# ══════════════════ 通用构造助手 ══════════════════

def make_user(
    db: Session,
    email: str = "legacy@example.com",
    password: str = "Correct-Pass-1",
    is_admin: bool = False,
    display_name: str = "Legacy User",
) -> User:
    """按邮箱+密码建一个本地账号（bcrypt 哈希入库）。"""
    user = User(
        email=email,
        hashed_password=auth_service.hash_password(password) if password else "",
        display_name=display_name,
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_identity(db: Session, user: User, provider: str = "github", provider_uid: str = "9001") -> OAuthIdentity:
    """直接预置一条三方身份绑定（路径 A / 冲突场景用）。"""
    identity = OAuthIdentity(
        user_id=user.id, provider=provider, provider_uid=provider_uid
    )
    db.add(identity)
    db.commit()
    db.refresh(identity)
    return identity


def github_profile(
    uid: int = 9001,
    email: Optional[str] = "octo@example.com",
    name: str = "Octo Cat",
) -> dict:
    """构造 GitHub ``/user`` 响应 JSON。"""
    return {
        "id": uid,
        "login": f"user{uid}",
        "name": name,
        "email": email,
        "avatar_url": f"https://avatars.example/{uid}.png",
    }


def parse_redirect(redirect_url: str) -> dict:
    """解析回调 302 Location 的 query 参数。"""
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(redirect_url).query))


def run_login_flow(
    db: Session,
    github_mock: GitHubUpstreamMock,
    *,
    profile: dict,
    intent: str = "login",
    user: Optional[User] = None,
    code: str = "good-code",
) -> dict:
    """完整走 authorize → callback（三方上游用 mock），返回 302 query 参数字典。

    成功时含 ``ticket`` / ``status`` / ``client_type``；失败时含 ``error``。
    """
    from app.domains.auth.services import oauth_service

    github_mock.user_response = (200, profile)
    authz = oauth_service.build_authorize_url(
        db,
        provider="github",
        intent=intent,
        client_type="web",
        user_id=user.id if user is not None else None,
    )
    cb = oauth_service.handle_callback(
        db, provider="github", code=code, state=authz.state, error=None
    )
    return parse_redirect(cb.redirect_url)
