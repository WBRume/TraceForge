"""
认证服务 — JWT 签发/验证, 密码哈希
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session

from app.config import settings
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.task.services import avatar_service

# SERVER_BOOT_ID = str(uuid.uuid4())
SERVER_BOOT_ID = "DEBUG_BOOT_ID" # 调试模式固定 ID，避免重启后强制重新登录


def hash_password(password: str) -> str:
    # bcrypt 限制最大 72 字节，为避免前端传递过长密码引发崩溃，手动截断
    pwd_bytes = password.encode('utf-8')[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    try:
        pwd_bytes = plain.encode('utf-8')[:72]
        return bcrypt.checkpw(pwd_bytes, hashed.encode('utf-8'))
    except Exception:
        return False


def create_access_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "access", "boot_id": SERVER_BOOT_ID},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "refresh", "boot_id": SERVER_BOOT_ID},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str, expected_type: str = "access") -> dict:
    payload = jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    if payload.get("type") != expected_type:
        raise JWTError("invalid token type")
    # if payload.get("boot_id") != SERVER_BOOT_ID:
    #     raise JWTError("token expired after server restart")
    if not payload.get("sub"):
        raise JWTError("missing token subject")
    return payload


def register_user(db: Session, email: str, password: str, display_name: str) -> User:
    """Register a new user only. Workspace creation is manual."""
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise ValueError("This email has already been registered")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Verify user credentials for login."""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def ensure_user_avatar_svg(db: Session, user: User) -> User:
    """
    Backfill avatar_svg on first profile read to support older accounts.
    """
    if user.avatar_svg and user.avatar_svg.strip():
        try:
            normalized_svg = avatar_service.sanitize_avatar_svg(user.avatar_svg)
        except ValueError:
            normalized_svg = avatar_service.build_default_avatar_svg(
                user.display_name,
                user.email,
                user.id,
            )

        if normalized_svg != user.avatar_svg:
            user.avatar_svg = normalized_svg
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    user.avatar_svg = avatar_service.build_default_avatar_svg(
        user.display_name,
        user.email,
        user.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_avatar(db: Session, user: User, avatar_svg: str) -> User:
    sanitized_svg = avatar_service.sanitize_avatar_svg(avatar_svg)
    user.avatar_svg = sanitized_svg
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def resolve_user_avatar_svg(user: User) -> str:
    return avatar_service.resolve_avatar_svg(
        user.avatar_svg,
        user.avatar_url,
        display_name=user.display_name,
        email=user.email,
        user_id=user.id,
    )
