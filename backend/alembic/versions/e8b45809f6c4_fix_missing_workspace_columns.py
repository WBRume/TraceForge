"""fix_missing_workspace_columns

Revision ID: e8b45809f6c4
Revises: b3a9fd9e1c1f
Create Date: 2026-03-24 16:00:25.941872

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b45809f6c4'
down_revision: Union[str, None] = 'b3a9fd9e1c1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('workspaces'):
        columns = {c['name'] for c in inspector.get_columns('workspaces')}
        if 'project_path' not in columns:
            op.add_column('workspaces', sa.Column('project_path', sa.String(length=500), nullable=True))
        if 'git_repo_url' not in columns:
            op.add_column('workspaces', sa.Column('git_repo_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('workspaces'):
        columns = {c['name'] for c in inspector.get_columns('workspaces')}
        if 'git_repo_url' in columns:
            op.drop_column('workspaces', 'git_repo_url')
        if 'project_path' in columns:
            op.drop_column('workspaces', 'project_path')
