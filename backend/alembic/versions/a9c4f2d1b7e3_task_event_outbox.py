"""Task event outbox with receipt versioning for reliable submission sync."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "a9c4f2d1b7e3"
down_revision = "e6a718293b4c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sdd_task_chat_submissions',
                  sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_sdd_task_chat_submissions_ai_job_id', 'sdd_task_chat_submissions', ['ai_job_id'], unique=False)
    op.create_table('task_event_outbox',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('receipt_id', sa.String(length=36), nullable=True),
    sa.Column('receipt_version', sa.Integer(), nullable=True),
    sa.Column('payload_json', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
    sa.Column('available_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False, server_default=sa.func.now()),
    sa.Column('lease_token', sa.String(length=36), nullable=True),
    sa.Column('lease_until', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('last_error_code', sa.String(length=80), nullable=True),
    sa.Column('created_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False, server_default=sa.func.now()),
    sa.Column('finished_at', sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', name='uq_task_event_outbox_event_id')
    )
    op.create_index('ix_task_event_outbox_task_id', 'task_event_outbox', ['task_id'], unique=False)
    op.create_index('ix_task_event_outbox_pending', 'task_event_outbox', ['status', 'available_at', 'id'], unique=False)
    op.create_index('ix_task_event_outbox_lease', 'task_event_outbox', ['status', 'lease_until', 'id'], unique=False)


def downgrade():
    op.drop_index('ix_task_event_outbox_lease', table_name='task_event_outbox')
    op.drop_index('ix_task_event_outbox_pending', table_name='task_event_outbox')
    op.drop_index('ix_task_event_outbox_task_id', table_name='task_event_outbox')
    op.drop_table('task_event_outbox')
    op.drop_index('ix_sdd_task_chat_submissions_ai_job_id', table_name='sdd_task_chat_submissions')
    op.drop_column('sdd_task_chat_submissions', 'version')
