"""Replace waterfall task phases with collaboration states.

Revision ID: a61d8c3e7f20
Revises: f4a7c2d9e1b6
"""

import sqlalchemy as sa

from alembic import op

revision = "a61d8c3e7f20"
down_revision = "f4a7c2d9e1b6"
branch_labels = None
depends_on = None

OLD = (
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
)
NEW = (
    "PROVISIONING",
    "INITIALIZED",
    "RUNNING",
    "ROUND_COMPLETED",
    "AWAITING_INPUT",
    "INTERRUPTED",
    "COMPLETED",
    "FAILED",
)
PHASES = ("BRAINSTORMING", "PLANNING", "CODING", "TESTING", "REVIEWING", "DEPLOYING")


def _prepare_type(values):
    bind = op.get_bind()
    info = next(c for c in sa.inspect(bind).get_columns("sdd_tasks") if c["name"] == "status")
    if bind.dialect.name in {"mysql", "mariadb"}:
        op.alter_column(
            "sdd_tasks",
            "status",
            existing_type=info["type"],
            type_=sa.Enum(*dict.fromkeys((*OLD, *NEW))),
            existing_nullable=False,
        )
    elif bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE sdd_tasks ALTER COLUMN status DROP DEFAULT")
        op.execute("ALTER TABLE sdd_tasks ALTER COLUMN status TYPE VARCHAR(40) USING status::text")
    else:
        # SQLite's old enum can have a named CHECK constraint; remove it before rewriting data.
        checks = sa.inspect(bind).get_check_constraints("sdd_tasks")
        with op.batch_alter_table("sdd_tasks") as batch:
            for check in checks:
                if check.get("name") and "status" in check.get("sqltext", ""):
                    batch.drop_constraint(check["name"], type_="check")
            batch.alter_column("status", existing_type=info["type"], type_=sa.String(40), existing_nullable=False)
    return info["type"]


def _finish_type(values, old_type):
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Recreate rather than ADD VALUE: newly added enum labels cannot be used in the same transaction.
        name = getattr(old_type, "name", None) or "taskstatus"
        quoted = bind.dialect.identifier_preparer.quote(name)
        op.execute(f"DROP TYPE IF EXISTS {quoted}")
        enum = sa.Enum(*values, name=name)
        enum.create(bind, checkfirst=True)
        op.execute(f"ALTER TABLE sdd_tasks ALTER COLUMN status TYPE {quoted} USING status::{quoted}")
    elif bind.dialect.name in {"mysql", "mariadb"}:
        op.alter_column(
            "sdd_tasks", "status", existing_type=sa.String(40), type_=sa.Enum(*values), existing_nullable=False
        )
    else:
        with op.batch_alter_table("sdd_tasks") as batch:
            batch.alter_column(
                "status",
                existing_type=sa.String(40),
                type_=sa.Enum(*values, name="taskstatus", create_constraint=True),
                existing_nullable=False,
            )


def upgrade():
    previous = _prepare_type(NEW)
    tasks = sa.table(
        "sdd_tasks",
        sa.column("id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("baselined_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("created_at", sa.DateTime()),
    )
    jobs = sa.table(
        "sdd_ai_jobs",
        sa.column("task_id", sa.String()),
        sa.column("channel", sa.String()),
        sa.column("status", sa.String()),
    )
    active = sa.exists(
        sa.select(1)
        .select_from(jobs)
        .where(
            jobs.c.task_id == tasks.c.id,
            jobs.c.channel == "TASK_CHAT",
            jobs.c.status.in_(("PENDING", "RUNNING", "WAITING_HITL", "TERMINATING", "ORPHANED")),
        )
    )
    op.execute(
        tasks.update()
        .where(tasks.c.status.in_(PHASES))
        .values(status=sa.case((active, "RUNNING"), else_="ROUND_COMPLETED"))
    )
    op.execute(
        tasks.update()
        .where(tasks.c.status == "BASELINED")
        .values(
            baselined_at=sa.func.coalesce(tasks.c.baselined_at, tasks.c.updated_at, tasks.c.created_at, sa.func.now()),
            status="COMPLETED",
        )
    )
    for old, new in (("PENDING", "INITIALIZED"), ("DONE", "COMPLETED"), ("SUSPENDED", "AWAITING_INPUT")):
        op.execute(tasks.update().where(tasks.c.status == old).values(status=new))
    _finish_type(NEW, previous)


def downgrade():
    previous = _prepare_type(OLD)
    tasks = sa.table("sdd_tasks", sa.column("status", sa.String()), sa.column("baselined_at", sa.DateTime()))
    op.execute(
        tasks.update()
        .where(tasks.c.status == "COMPLETED")
        .values(status=sa.case((tasks.c.baselined_at.is_not(None), "BASELINED"), else_="DONE"))
    )
    for new, old in (
        ("INITIALIZED", "PENDING"),
        ("RUNNING", "CODING"),
        ("ROUND_COMPLETED", "CODING"),
        ("AWAITING_INPUT", "SUSPENDED"),
    ):
        op.execute(tasks.update().where(tasks.c.status == new).values(status=old))
    _finish_type(OLD, previous)
