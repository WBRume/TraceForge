"""add oauth tables (三方登录：oauth_identities / oauth_states / oauth_tickets)

Revision ID: b7e4a1c9d3f6
Revises: f3bc9223e419
Create Date: 2026-08-27

⚠️⚠️⚠️ 多 head 环境警示（K-1 / C-5，评审必查）⚠️⚠️⚠️

本仓库 alembic 存在 3 个 head（历史遗留 2 个 base）。新迁移的
``down_revision`` **必须**挂在 ``f3bc9223e419``（数据库当前停在
``c8f4d9e7f0b2``，位于该链链尾前一步）。挂错链会导致
``alembic upgrade head`` 永远走不通。

🔴 本迁移**禁止**用 ``alembic upgrade head`` 执行：
    1. 多 head 下 ``upgrade head`` 必然报错；
    2. 待执行的 ``f3bc9223e419``（drop case conversation snapshot）是
       drop 操作，真跑会删表。
    验证方式：``alembic upgrade b7e4a1c9d3f6 --sql``（离线输出 SQL 人工核对）。

表结构依据：docs/design-oauth-login.md §2.1。
🔴 安全要点：
- ``oauth_identities`` 的 ``uq_oauth_provider_uid``（UNIQUE(provider, provider_uid)）
  是账号判定的唯一可信依据，不得删除或放宽；
- 三张表均不含 access_token / refresh_token 字段（拍板 #9：三方 token 不持久化）；
- ``users`` 表零改动（K-2）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e4a1c9d3f6'
down_revision: Union[str, None] = 'f3bc9223e419'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. oauth_identities：三方身份绑定（长期数据）──
    op.create_table(
        "oauth_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_uid", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=255), nullable=True),
        sa.Column("provider_display_name", sa.String(length=255), nullable=True),
        sa.Column("provider_avatar_url", sa.String(length=500), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=True),
        sa.Column("raw_profile_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # ON DELETE CASCADE：删除用户时级联清理绑定，避免孤儿行
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # 🔴 全局唯一：同一三方身份只能绑定一个邮箱账号（E-2 / AC-S6）
        sa.UniqueConstraint("provider", "provider_uid", name="uq_oauth_provider_uid"),
    )
    op.create_index(
        "ix_oauth_identities_user_id", "oauth_identities", ["user_id"], unique=False
    )

    # ── 2. oauth_states：一次性授权请求（防 CSRF，短生命周期）──
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("client_type", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state", name="uq_oauth_states_state"),
    )
    # UNIQUE(state) 本身即唯一索引，不再叠加普通索引（与 ORM 模型保持一致）
    op.create_index("ix_oauth_states_expires_at", "oauth_states", ["expires_at"], unique=False)

    # ── 3. oauth_tickets：一次性结果凭证（短生命周期）──
    op.create_table(
        "oauth_tickets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("ticket", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_uid", sa.String(length=255), nullable=False),
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("client_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("normalized_email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket", name="uq_oauth_tickets_ticket"),
    )
    # UNIQUE(ticket) 本身即唯一索引，不再叠加普通索引（与 ORM 模型保持一致）
    op.create_index("ix_oauth_tickets_provider_uid", "oauth_tickets", ["provider_uid"], unique=False)
    op.create_index("ix_oauth_tickets_normalized_email", "oauth_tickets", ["normalized_email"], unique=False)
    op.create_index("ix_oauth_tickets_expires_at", "oauth_tickets", ["expires_at"], unique=False)


def downgrade() -> None:
    # 逆序删除：先索引后表；三表之间无外键依赖（user_id FK 指向 users，随表删除）
    op.drop_index("ix_oauth_tickets_expires_at", table_name="oauth_tickets")
    op.drop_index("ix_oauth_tickets_normalized_email", table_name="oauth_tickets")
    op.drop_index("ix_oauth_tickets_provider_uid", table_name="oauth_tickets")
    op.drop_table("oauth_tickets")

    op.drop_index("ix_oauth_states_expires_at", table_name="oauth_states")
    op.drop_table("oauth_states")

    op.drop_index("ix_oauth_identities_user_id", table_name="oauth_identities")
    op.drop_table("oauth_identities")
