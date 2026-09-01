"""
OAuth 错误体系（B-14，对应设计文档 §4.5 错误码规范）。

- ``OAuthAPIError``：携带 ``code`` 的 HTTPException 子类，经 exception handler
  统一输出 ``{"detail": "<中文用户可读文案>", "code": "OAUTH_XXX"}``，
  兼容现有前端 ``formatApiError``（读 ``detail``）。
- 细分异常子类：供 ``services/oauth_service.py``（T02）按语义抛出，
  router 层无需逐个捕获。
- ``oauth_api_error_handler``：由 ``main.py``（B-16，T02）注册：
  ``app.add_exception_handler(OAuthAPIError, oauth_api_error_handler)``。
"""

from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi import HTTPException

# ══════════════════ 错误码常量（§4.5 错误码全表） ══════════════════

ERR_OAUTH_PROVIDER_NOT_FOUND = "OAUTH_PROVIDER_NOT_FOUND"      # 404 provider 未注册
ERR_OAUTH_PROVIDER_DISABLED = "OAUTH_PROVIDER_DISABLED"        # 404 provider 未配置 client_id/secret
ERR_OAUTH_TICKET_INVALID = "OAUTH_TICKET_INVALID"              # 404 ticket 不存在
ERR_OAUTH_TICKET_EXPIRED = "OAUTH_TICKET_EXPIRED"              # 410 ticket 过期（E-17）
ERR_OAUTH_TICKET_LOCKED = "OAUTH_TICKET_LOCKED"                # 423 连续失败锁定（E-18）
ERR_OAUTH_PASSWORD_REQUIRED = "OAUTH_PASSWORD_REQUIRED"        # 400 管理员加绑未传密码
ERR_OAUTH_PASSWORD_INVALID = "OAUTH_PASSWORD_INVALID"          # 🔴 401 密码错误/账号不存在（同码同文案）
ERR_OAUTH_EMAIL_TAKEN = "OAUTH_EMAIL_TAKEN"                    # 409 手填邮箱已注册（E-1b）
ERR_OAUTH_IDENTITY_CONFLICT = "OAUTH_IDENTITY_CONFLICT"        # 409 身份已绑其他账号（E-2）
ERR_OAUTH_NO_PASSWORD = "OAUTH_NO_PASSWORD"                    # 400 解绑防御：账号无密码（E-6b）
ERR_REGISTER_EMAIL_NOT_ALLOWED = "REGISTER_EMAIL_NOT_ALLOWED"  # 403 域名白名单未通过
ERR_OAUTH_UPSTREAM_ERROR = "OAUTH_UPSTREAM_ERROR"              # 502 三方服务不可用（E-9）
ERR_AUTH_REQUIRED = "AUTH_REQUIRED"                            # 401 intent=bind 缺 token


class OAuthAPIError(HTTPException):
    """OAuth 域统一业务异常。

    经 exception handler 输出 ``{"detail": message, "code": code}``。
    """

    def __init__(self, status_code: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        # 额外载荷（如 OAUTH_TICKET_LOCKED 的 retry_after），handler 原样并入响应体
        self.extra = extra

    def to_response(self) -> JSONResponse:
        payload: dict[str, Any] = {"detail": self.message, "code": self.code}
        payload.update(self.extra)
        return JSONResponse(status_code=self.status_code, content=payload)


# ══════════════════ 语义化异常子类（services 层抛出） ══════════════════

class OAuthProviderNotFoundError(OAuthAPIError):
    """provider 未注册（未 import / 未装饰注册）。"""

    def __init__(self, provider: str = "") -> None:
        super().__init__(
            status_code=404,
            code=ERR_OAUTH_PROVIDER_NOT_FOUND,
            message="该登录方式不存在",
        )
        self.provider = provider


class OAuthProviderDisabledError(OAuthAPIError):
    """provider 已注册但未配置 client_id/secret（NFR-M2：不出现在 provider 列表）。"""

    def __init__(self, provider: str = "") -> None:
        super().__init__(
            status_code=404,
            code=ERR_OAUTH_PROVIDER_DISABLED,
            message="该登录方式暂未启用",
        )
        self.provider = provider


class OAuthTicketInvalidError(OAuthAPIError):
    """ticket 不存在 / 已消费 / 被并发抢占（原子消费 rowcount=0）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code=ERR_OAUTH_TICKET_INVALID,
            message="登录凭证无效或已被使用，请重新发起登录",
        )


class OAuthTicketExpiredError(OAuthAPIError):
    """ticket 过期（E-17 → 410）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=410,
            code=ERR_OAUTH_TICKET_EXPIRED,
            message="登录凭证已过期，请重新发起登录",
        )


class OAuthTicketLockedError(OAuthAPIError):
    """连续密码失败达阈值进入冷却（E-18 → 423），响应含 retry_after。"""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=423,
            code=ERR_OAUTH_TICKET_LOCKED,
            message="尝试次数过多，请稍后再试",
            retry_after=retry_after,
        )


class OAuthPasswordRequiredError(OAuthAPIError):
    """管理员账号加绑未传密码（拍板 #8 / E-8 → 400）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=400,
            code=ERR_OAUTH_PASSWORD_REQUIRED,
            message="该账号为管理员账号，绑定前需确认密码",
        )


class OAuthPasswordInvalidError(OAuthAPIError):
    """🔴 密码错误 / 账号不存在 —— 两者必须同码同文案，不可区分（AC-S7 / K-7）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code=ERR_OAUTH_PASSWORD_INVALID,
            message="邮箱或密码错误",
        )


class OAuthEmailTakenError(OAuthAPIError):
    """路径 C 手填邮箱已被注册（E-1b → 409）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ERR_OAUTH_EMAIL_TAKEN,
            message="该邮箱已被注册",
        )


class OAuthIdentityConflictError(OAuthAPIError):
    """该三方身份已绑定到其他账号（E-2 → 409 + 审计 WARN，T02 负责）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code=ERR_OAUTH_IDENTITY_CONFLICT,
            message="该三方身份已绑定到其他账号",
        )


class OAuthNoPasswordError(OAuthAPIError):
    """解绑防御：账号无密码，禁止解绑最后一个身份（E-6b → 400）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=400,
            code=ERR_OAUTH_NO_PASSWORD,
            message="请先设置密码后再解绑",
        )


class RegisterEmailNotAllowedError(OAuthAPIError):
    """注册域名白名单未通过（拍板 #4 → 403）。白名单留空 = 不限制，不会触发本错误。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=403,
            code=ERR_REGISTER_EMAIL_NOT_ALLOWED,
            message="该邮箱域名不在允许注册的范围内",
        )


class OAuthUpstreamError(OAuthAPIError):
    """三方服务超时 / 5xx（E-9 → 502）。严禁透传三方原始错误（NFR-U2）。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code=ERR_OAUTH_UPSTREAM_ERROR,
            message="三方服务暂时不可用，请稍后重试或使用邮箱登录",
        )


class AuthRequiredError(OAuthAPIError):
    """intent=bind 但缺少有效 JWT → 401。"""

    def __init__(self) -> None:
        super().__init__(
            status_code=401,
            code=ERR_AUTH_REQUIRED,
            message="请先登录后再绑定三方身份",
        )


# ══════════════════ Exception Handler（main.py 注册，B-16） ══════════════════

async def oauth_api_error_handler(request: Request, exc: OAuthAPIError) -> JSONResponse:
    """统一输出 ``{"detail": ..., "code": ..., **extra}``。

    注册方式（T02 在 main.py 中）::

        app.add_exception_handler(OAuthAPIError, oauth_api_error_handler)
    """
    return exc.to_response()


__all__ = [
    "OAuthAPIError",
    "OAuthProviderNotFoundError",
    "OAuthProviderDisabledError",
    "OAuthTicketInvalidError",
    "OAuthTicketExpiredError",
    "OAuthTicketLockedError",
    "OAuthPasswordRequiredError",
    "OAuthPasswordInvalidError",
    "OAuthEmailTakenError",
    "OAuthIdentityConflictError",
    "OAuthNoPasswordError",
    "RegisterEmailNotAllowedError",
    "OAuthUpstreamError",
    "AuthRequiredError",
    "oauth_api_error_handler",
    "ERR_OAUTH_PROVIDER_NOT_FOUND",
    "ERR_OAUTH_PROVIDER_DISABLED",
    "ERR_OAUTH_TICKET_INVALID",
    "ERR_OAUTH_TICKET_EXPIRED",
    "ERR_OAUTH_TICKET_LOCKED",
    "ERR_OAUTH_PASSWORD_REQUIRED",
    "ERR_OAUTH_PASSWORD_INVALID",
    "ERR_OAUTH_EMAIL_TAKEN",
    "ERR_OAUTH_IDENTITY_CONFLICT",
    "ERR_OAUTH_NO_PASSWORD",
    "ERR_REGISTER_EMAIL_NOT_ALLOWED",
    "ERR_OAUTH_UPSTREAM_ERROR",
    "ERR_AUTH_REQUIRED",
]
