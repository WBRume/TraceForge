"""Separate snapshot event metadata from compressed, content-addressed inventories."""

import hashlib
import json

import sqlalchemy as sa
import zstandard
from sqlalchemy.dialects.mysql import LONGBLOB

from alembic import op

revision = "f42a81d9c630"
down_revision = "e16c8a43d920"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    snapshots = sa.Table(
        "task_collaboration_snapshots",
        metadata,
        sa.Column("id", sa.String(36)),
        sa.Column("task_id", sa.String(36)),
        sa.Column("content_digest", sa.String(64)),
        sa.Column("manifest_json", sa.JSON),
    )
    manifests = sa.Table(
        "task_collaboration_manifests",
        metadata,
        sa.Column("task_id", sa.String(36)),
        sa.Column("content_digest", sa.String(64)),
        sa.Column("repositories_zstd", sa.LargeBinary),
    )
    return snapshots, manifests


def _snapshot_ids(connection, snapshots):
    # Page over small keys; load only one potentially large manifest at a time.
    cursor = None
    while True:
        query = sa.select(snapshots.c.id).order_by(snapshots.c.id).limit(100)
        if cursor is not None:
            query = query.where(snapshots.c.id > cursor)
        ids = connection.execute(query).scalars().all()
        if not ids:
            return
        yield from ids
        cursor = ids[-1]


def upgrade():
    op.create_table(
        "task_collaboration_manifests",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("content_digest", sa.String(64), primary_key=True),
        sa.Column("repositories_zstd", sa.LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=False),
    )
    connection = op.get_bind()
    snapshots, manifests = _tables()
    compressor = zstandard.ZstdCompressor(level=3)
    for identity in _snapshot_ids(connection, snapshots):
        row = connection.execute(sa.select(snapshots).where(snapshots.c.id == identity)).mappings().one()
        header = dict(row["manifest_json"])
        repositories = header.pop("repositories")
        raw = json.dumps(repositories, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row["content_digest"]:
            raise ValueError(f"Snapshot {identity} inventory does not match its recorded digest")
        key = (manifests.c.task_id == row["task_id"]) & (manifests.c.content_digest == digest)
        if connection.execute(sa.select(manifests.c.content_digest).where(key)).first() is None:
            connection.execute(
                manifests.insert().values(
                    task_id=row["task_id"],
                    content_digest=digest,
                    repositories_zstd=compressor.compress(raw),
                )
            )
        connection.execute(snapshots.update().where(snapshots.c.id == identity).values(manifest_json=header))
    op.create_index(
        "ix_collaboration_snapshot_lookup",
        "task_collaboration_snapshots",
        ["task_id", "content_digest", "source", "created_at", "id"],
    )
    with op.batch_alter_table("task_collaboration_snapshots") as batch:
        batch.create_foreign_key(
            "fk_collaboration_snapshot_manifest",
            "task_collaboration_manifests",
            ["task_id", "content_digest"],
            ["task_id", "content_digest"],
            ondelete="CASCADE",
        )


def downgrade():
    connection = op.get_bind()
    snapshots, manifests = _tables()
    decompressor = zstandard.ZstdDecompressor()
    for identity in _snapshot_ids(connection, snapshots):
        row = connection.execute(sa.select(snapshots).where(snapshots.c.id == identity)).mappings().one()
        payload = connection.execute(
            sa.select(manifests.c.repositories_zstd).where(
                manifests.c.task_id == row["task_id"],
                manifests.c.content_digest == row["content_digest"],
            )
        ).scalar_one()
        raw = decompressor.decompress(payload)
        if hashlib.sha256(raw).hexdigest() != row["content_digest"]:
            raise ValueError(f"Snapshot {identity} inventory digest differs")
        manifest = {**row["manifest_json"], "repositories": json.loads(raw)}
        connection.execute(snapshots.update().where(snapshots.c.id == identity).values(manifest_json=manifest))
    with op.batch_alter_table("task_collaboration_snapshots") as batch:
        batch.drop_constraint("fk_collaboration_snapshot_manifest", type_="foreignkey")
    # InnoDB may replace an implicit task FK index with the new composite one.
    # Keep that older FK supported before removing our index.
    indexes = sa.inspect(connection).get_indexes("task_collaboration_snapshots")
    if not any(
        index["name"] != "ix_collaboration_snapshot_lookup" and index["column_names"][:1] == ["task_id"]
        for index in indexes
    ):
        op.create_index("ix_task_collaboration_snapshots_task_id", "task_collaboration_snapshots", ["task_id"])
    op.drop_index("ix_collaboration_snapshot_lookup", table_name="task_collaboration_snapshots")
    op.drop_table("task_collaboration_manifests")
