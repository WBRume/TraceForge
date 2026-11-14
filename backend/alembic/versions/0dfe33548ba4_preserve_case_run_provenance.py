"""Keep historical case provenance when its execution is removed."""

from alembic import op

revision = "0dfe33548ba4"
down_revision = "70dc62f40f8a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE case_playbook_links ALTER CONSTRAINT case_playbook_links_source_run_id_fkey NOT ENFORCED")


def downgrade() -> None:
    op.execute("ALTER TABLE case_playbook_links ALTER CONSTRAINT case_playbook_links_source_run_id_fkey ENFORCED")
