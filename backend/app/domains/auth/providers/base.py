"""
OAuth Provider 基础设施层（B-10）。

- ``OAuthProfile``：三方用户资料快照（不可变 dataclass）。
- ``OAuthProvider``：抽象基类（authorize_url / exchange_code / fetch_profile 三方法）。
- ``_http_client``：共享 httpx 同步 Client 工厂（统一超时，K-3：connect 5s / read 10s）。
- ``_request_with_retry``：仅对网络类错误重试（K-3 / NFR-P3：4xx 不重试）。
- ``oauth_setting``：按 ``OAUTH_{PROVIDER_UPPER}_{SUFFIX}`` 约定读配置
  （新增 provider 无需改 config.py，NFR-M1 前提）。

🔴 依赖规则（设计文档 §1.5）：本包**不得** import ``services/`` 或 ``models/``，
保持纯协议适配、可单测；只允许依赖 ``app.config`` 与 ``app.domains.auth.errors``。
"""

import abc
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, ClassVar, Optional

import httpx

from app.config import settings
from app.domains.auth.errors import OAuthUpstreamError

# 仅对这些网络类异常重试（K-3）；HTTPError / 协议错误 / 4xx 不重试
_NETWORK_RETRY_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)


@dataclass(frozen=True)
class OAuthProfile:
    """三方用户资料快照。``provider_uid`` 是账号判定的唯一可信依据 🔴。

    ``email`` 可空（E-11，为空走路径 C 手填）；``raw`` 保留原始 JSON
    快照供排障（NFR-R4），落库时序列化为 ``oauth_tickets.profile_json``。
    """

    provider_uid: str
    email: Optional[str] = None
    email_verified: Optional[bool] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    raw: dict = field(default_factory=dict)


def oauth_setting(provider_name: str, suffix: str, default: str = "") -> str:
    """按 ``OAUTH_{PROVIDER_UPPER}_{SUFFIX}`` 约定读取配置。

    例：``oauth_setting("github", "CLIENT_ID")`` → ``settings.OAUTH_GITHUB_CLIENT_ID``。
    配置项缺失时返回 ``default``（新增 provider 只需在 .env 加键，NFR-M1）。
    """
    key = f"OAUTH_{provider_name.upper()}_{suffix}"
    return str(getattr(settings, key, default) or default)


def _http_client() -> httpx.Client:
    """统一超时配置的同步 httpx Client 工厂。

    🔴 K-3：三方 HTTP 调用必须走本工厂，禁止各处自建 client
    （connect=OAUTH_HTTP_CONNECT_TIMEOUT / read=OAUTH_HTTP_READ_TIMEOUT）。
    """
    return httpx.Client(
        timeout=httpx.Timeout(
            connect=float(settings.OAUTH_HTTP_CONNECT_TIMEOUT),
            read=float(settings.OAUTH_HTTP_READ_TIMEOUT),
        ),
        follow_redirects=False,
    )


def _request_with_retry(
    fn: Callable[[], httpx.Response],
    *,
    max_retries: Optional[int] = None,
) -> httpx.Response:
    """执行 HTTP 请求，仅对网络类错误做有限重试（K-3 / NFR-P3）。

    - ``max_retries`` 默认取 ``settings.OAUTH_HTTP_MAX_RETRIES``（=1）。
    - 重试仅针对 ``ConnectError / ConnectTimeout / ReadTimeout``；
      4xx / 5xx 响应**不**重试（调用方自行判定状态码语义）。
    - 重试耗尽后抛出最后一个网络异常，由调用方映射为
      ``OAuthUpstreamError``（502 OAUTH_UPSTREAM_ERROR，E-9）。
    """
    retries = int(settings.OAUTH_HTTP_MAX_RETRIES if max_retries is None else max_retries)
    attempts = retries + 1
    last_error: Optional[BaseException] = None
    for _ in range(attempts):
        try:
            return fn()
        except _NETWORK_RETRY_ERRORS as exc:  # 网络类错误：有限重试
            last_error = exc
    assert last_error is not None
    raise last_error


class OAuthProvider(abc.ABC):
    """OAuth provider 抽象基类。

    新增 provider 的步骤（NFR-M1 验收标尺）：
    1. 新增 ``providers/{name}.py``，实现 3 个抽象方法 + ``@register_provider("{name}")``
    2. ``providers/__init__.py`` 底部加一行 ``from . import {name}  # noqa: F401``
    3. ``.env`` 加 ``OAUTH_{NAME}_CLIENT_ID / _SECRET / _REDIRECT_URI_WEB / _REDIRECT_URI_DESKTOP``
    —— 路由、判定逻辑、数据模型零改动。
    """

    # 类级元数据（子类必须覆盖）
    name: ClassVar[str] = ""
    display_name: ClassVar[str] = ""

    def is_configured(self) -> bool:
        """是否已启用：client_id 与 client_secret 均非空（NFR-M2，空 = 不启用）。"""
        return bool(oauth_setting(self.name, "CLIENT_ID")) and bool(
            oauth_setting(self.name, "CLIENT_SECRET")
        )

    def resolve_redirect_uri(self, client_type: str, loopback_port: Optional[int] = None) -> str:
        """按 client_type 解析本次授权的 redirect_uri。

        - ``web`` → ``OAUTH_{NAME}_REDIRECT_URI_WEB``
        - ``desktop`` → ``OAUTH_{NAME}_REDIRECT_URI_DESKTOP`` 模板，
          运行时将 ``127.0.0.1`` 的端口替换为 Electron 本地回环服务的实际端口
          （RFC 8252 / 拍板 #10：``http://127.0.0.1:{port}/callback``）。
        """
        if client_type == "desktop":
            raw_uri = oauth_setting(self.name, "REDIRECT_URI_DESKTOP")
            if loopback_port:
                parts = urllib.parse.urlsplit(raw_uri)
                hostname = parts.hostname or "127.0.0.1"
                netloc = f"{hostname}:{int(loopback_port)}"
                return urllib.parse.urlunsplit(
                    (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
                )
            return raw_uri
        return oauth_setting(self.name, "REDIRECT_URI_WEB")

    @abc.abstractmethod
    def authorize_url(self, state: str, redirect_uri: str) -> str:
        """构造三方授权页 URL（含 client_id / state / redirect_uri / scope）。"""

    @abc.abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> str:
        """code 换 access_token。

        🔴 拍板 #9：token 仅在内存中流转（用于 fetch_profile 后立即丢弃），
        不写库、不写日志、不返回前端。
        失败时抛 ``OAuthUpstreamError``（或其子类 ``OAuthCodeInvalidError``）。
        """

    @abc.abstractmethod
    def fetch_profile(self, access_token: str) -> OAuthProfile:
        """用 access_token 拉取三方用户资料，产出 ``OAuthProfile`` 快照。"""


class OAuthCodeInvalidError(OAuthUpstreamError):
    """code 换 token 失败（失效 / 重复使用，E-4c）的内部信号。

    继承 ``OAuthUpstreamError``：未专门捕获时按 502 上游错误处理（错误码
    ``OAUTH_UPSTREAM_ERROR``，与 §4.5 错误码表一致）；T02 的 callback 可
    专门捕获本异常并映射为 302 ``error=code_invalid``。
    """
