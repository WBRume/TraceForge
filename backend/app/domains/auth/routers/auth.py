"""
Auth & User API Routers
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.logging import audit_log, get_logger
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.auth.schemas.auth import (
    TokenResponse,
    UserAvatarUpdate,
    UserRegister,
    UserResponse,
)
from app.domains.auth.services import auth_service, avatar_image, avatar_vector

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = get_logger(__name__)


@router.post("/register", response_model=UserResponse)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    try:
        # OAuth 增量（拍板 #4 / E-12）：接入域名白名单（留空 = 不限制）；
        # email 归一化在 register_user 内部完成
        auth_service.assert_email_allowed(user_data.email)
        user = auth_service.register_user(
            db=db,
            email=user_data.email,
            password=user_data.password,
            display_name=user_data.display_name,
        )
        return user
    except ValueError as e:
        logger.warning("Register rejected for email {}: {}", user_data.email, str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = auth_service.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        audit_log(
            action="login",
            outcome="failed",
            resource_type="auth",
            resource_id=form_data.username,
            username=form_data.username,
            reason="invalid_credentials",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = auth_service.create_access_token(user.id)
    refresh_token = auth_service.create_refresh_token(user.id)
    audit_log(
        action="login",
        outcome="success",
        resource_type="auth",
        resource_id=user.id,
        user_id=user.id,
        username=form_data.username,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = auth_service.ensure_user_avatar_svg(db, current_user)
    response = UserResponse.model_validate(user)
    # OAuth 增量（接口 11）：已绑定 provider 名列表，如 ["github"]
    response.bound_providers = sorted({i.provider for i in user.oauth_identities})
    return response


@router.put("/me/avatar", response_model=UserResponse)
def update_my_avatar(
    payload: UserAvatarUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return auth_service.update_user_avatar(db, current_user, payload.avatar_svg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/me/avatar/image", response_model=UserResponse)
async def upload_my_avatar_image(
    request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Save a static or animated crop from the avatar editor."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in avatar_image.AVATAR_UPLOAD_FORMATS and media_type != avatar_vector.SVG_MIME:
        raise HTTPException(status_code=415, detail="Expected a PNG, WebP, APNG, or SVG avatar image")

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > avatar_image.AVATAR_MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Avatar image exceeds the upload limit")
        raw.extend(chunk)

    try:
        return await run_in_threadpool(auth_service.update_user_avatar_image, db, current_user, bytes(raw), media_type)
    except avatar_image.AvatarImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/avatars/{user_id}/{revision}.{extension}", response_class=Response)
def get_avatar_image(
    user_id: str,
    revision: UUID,
    extension: Literal["webp", "svg"],
    db: Session = Depends(get_db),
) -> Response:
    """Serve a profile photo to image tags using its versioned URL."""
    image = auth_service.read_user_avatar_image(db, user_id, str(revision), extension)
    if image is None:
        raise HTTPException(status_code=404, detail="Avatar image not found")

    headers = {"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"}
    if extension == "svg":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        return Response(image, media_type=avatar_vector.SVG_MIME, headers=headers)
    return Response(image, media_type="image/webp", headers=headers)
