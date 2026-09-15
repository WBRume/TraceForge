"""workspace member (workspace_id, user_id) uniqueness

doc 审计 0c381413 §4.2：相同用户通过不同邀请链接同时加入也必须幂等。
增量迁移为 ``workspace_members`` 添加 (workspace_id, user_id) 唯一约束，
作为服务层 Workspace→Link 锁顺序与条件名额占用之外的数据库兜底。

前置条件：已按 §4.2 完成只读重复成员审计。若生产/开发库仍存在重复的
(workspace_id, user_id) 记录，本迁移拒绝自动处理——必须先给出明确的数据
处理方案并人工清理，禁止自动删除开发数据。不重建数据库、不修改历史
Alembic baseline。

Revision ID: c4e5f6a7b8d9
Revises: b9d2e4f6a8c0
Create Date: 2026-09-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4e5f6a7b8d9"
down_revision: Union[str, None] = "b9d2e4f6a8c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT_NAME = "uq_workspace_members_workspace_user"


def _existing_duplicates(bind) -> int:
    rows = bind.execute(
        sa.text(
            "SELECT workspace_id, user_id, COUNT(*) AS c "
            "FROM workspace_members GROUP BY workspace_id, user_id HAVING c > 1"
        )
    ).fetchall()
    return len(rows)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    duplicates = _existing_duplicates(bind)
    if duplicates:
        raise RuntimeError(
            "workspace_members contains %d duplicate (workspace_id, user_id) "
            "group(s); resolve them explicitly before applying this migration "
            "(automatic data deletion is forbidden)" % duplicates
        )

    existing = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("workspace_members")
    }
    if _CONSTRAINT_NAME not in existing:
        op.create_unique_constraint(
            _CONSTRAINT_NAME, "workspace_members", ["workspace_id", "user_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("workspace_members")
    }
    if _CONSTRAINT_NAME in existing:
        op.drop_constraint(
            _CONSTRAINT_NAME, "workspace_members", type_="unique"
        )
