"""
认证服务 — JWT 签发/验证, 密码哈希
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt
import bcrypt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User, Workspace, WorkspaceMember, WorkspaceRole


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
        {"sub": user_id, "exp": expire, "type": "access"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "refresh"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def register_user(db: Session, email: str, password: str, display_name: str) -> User:
    """注册新用户并自动创建默认工作区"""
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise ValueError("该邮箱已被注册")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        display_name=display_name,
    )
    db.add(user)
    db.flush()

    # 自动创建默认工作区
    workspace = Workspace(
        name=f"{display_name} 的工作区",
        description="默认工作区",
        project_path=f"./projects/{user.id}",  # 默认生成路径
        owner_id=user.id,
    )
    db.add(workspace)
    db.flush()

    # 添加 owner 成员关系
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    db.add(member)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """验证用户登录"""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user
