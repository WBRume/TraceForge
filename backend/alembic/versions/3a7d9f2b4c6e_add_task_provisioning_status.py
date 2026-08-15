"""add task provisioning status

Revision ID: 3a7d9f2b4c6e
Revises: 2f8e5a1c3b9d
Create Date: 2026-08-16 12:00:00.000000

- sdd_tasks.status ENUM 增加 PROVISIONING（任务资源准备中，禁止启动任务会话）
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "3a7d9f2b4c6e"
down_revision: Union[str, None] = "2f8e5a1c3b9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TASK_STATUS_VALUES = [
    "PROVISIONING",
    "PENDING",
    "BRAINSTORMING",
    "PLANNING",
    "CODING",
    "TESTING",
    "REVIEWING",
    "DEPLOYING",
    "DONE",
    "FAILED",
    "SUSPENDED",
    "INTERRUPTED",
    "BASELINED",
]


def upgrade() -> None:
    enum_values = ", ".join(f"'{value}'" for value in TASK_STATUS_VALUES)
    op.execute(f"ALTER TABLE sdd_tasks MODIFY COLUMN status ENUM({enum_values}) NOT NULL")


def downgrade() -> None:
    values = [value for value in TASK_STATUS_VALUES if value != "PROVISIONING"]
    enum_values = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE sdd_tasks MODIFY COLUMN status ENUM({enum_values}) NOT NULL")
