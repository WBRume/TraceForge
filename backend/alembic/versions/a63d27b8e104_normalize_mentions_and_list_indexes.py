"""Normalize pre-input mentions and index frequent ordered lists."""

import sqlalchemy as sa

from alembic import op

revision = "a63d27b8e104"
down_revision = "f42a81d9c630"
branch_labels = None
depends_on = None

INDEXES = (
    ("sdd_tasks", "ix_sdd_tasks_workspace_created", ["workspace_id", "created_at", "id"]),
    ("sdd_user_notifications", "ix_notifications_recipient_created", ["recipient_user_id", "created_at", "id"]),
    (
        "sdd_user_notifications",
        "ix_notifications_recipient_unread",
        ["recipient_user_id", "read_at", "created_at", "id"],
    ),
    ("task_collaboration_handoffs", "ix_collaboration_handoff_history", ["task_id", "created_at", "id"]),
)


def _tables():
    metadata = sa.MetaData()
    pre_inputs = sa.Table(
        "sdd_task_pre_inputs",
        metadata,
        sa.Column("id", sa.String(36)),
        sa.Column("mentioned_user_ids", sa.JSON),
    )
    mentions = sa.Table(
        "sdd_task_pre_input_mentions",
        metadata,
        sa.Column("pre_input_id", sa.String(36)),
        sa.Column("user_id", sa.String(36)),
        sa.Column("position", sa.Integer),
    )
    return pre_inputs, mentions


def _batches(connection, table):
    cursor = None
    while True:
        query = sa.select(table).order_by(table.c.id).limit(500)
        if cursor is not None:
            query = query.where(table.c.id > cursor)
        rows = connection.execute(query).mappings().all()
        if not rows:
            return
        yield rows
        cursor = rows[-1]["id"]


def upgrade():
    op.create_table(
        "sdd_task_pre_input_mentions",
        sa.Column(
            "pre_input_id", sa.String(36), sa.ForeignKey("sdd_task_pre_inputs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("position", sa.Integer, nullable=False),
    )
    op.create_index("ix_pre_input_mentions_user", "sdd_task_pre_input_mentions", ["user_id", "pre_input_id"])
    connection = op.get_bind()
    pre_inputs, mentions = _tables()
    for rows in _batches(connection, pre_inputs):
        records = []
        for row in rows:
            users = list(dict.fromkeys(str(value) for value in (row["mentioned_user_ids"] or [])))
            records.extend(
                {"pre_input_id": row["id"], "user_id": user_id, "position": position}
                for position, user_id in enumerate(users)
            )
        if records:
            connection.execute(mentions.insert(), records)
    # The relation is authoritative; retaining an independently writable JSON
    # copy would let list filters and collaboration permissions disagree.
    with op.batch_alter_table("sdd_task_pre_inputs") as batch:
        batch.drop_column("mentioned_user_ids")
    for table_name, name, columns in INDEXES:
        op.create_index(name, table_name, columns)


def downgrade():
    with op.batch_alter_table("sdd_task_pre_inputs") as batch:
        batch.add_column(sa.Column("mentioned_user_ids", sa.JSON, nullable=True))
    connection = op.get_bind()
    pre_inputs, mentions = _tables()
    for rows in _batches(connection, pre_inputs):
        users_by_id = {row["id"]: [] for row in rows}
        for pre_input_id, user_id in connection.execute(
            sa.select(mentions.c.pre_input_id, mentions.c.user_id)
            .where(mentions.c.pre_input_id.in_(users_by_id))
            .order_by(mentions.c.position)
        ):
            users_by_id[pre_input_id].append(user_id)
        connection.execute(
            pre_inputs.update()
            .where(pre_inputs.c.id == sa.bindparam("row_identity"))
            .values(mentioned_user_ids=sa.bindparam("users")),
            [{"row_identity": identity, "users": users} for identity, users in users_by_id.items()],
        )
    with op.batch_alter_table("sdd_task_pre_inputs") as batch:
        batch.alter_column("mentioned_user_ids", existing_type=sa.JSON, nullable=False)
    op.drop_table("sdd_task_pre_input_mentions")
    for table_name, name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table_name)
