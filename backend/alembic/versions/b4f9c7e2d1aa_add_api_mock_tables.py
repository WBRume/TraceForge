"""add_api_mock_tables

Revision ID: b4f9c7e2d1aa
Revises: 6f52f8d3b9aa
Create Date: 2026-03-27 23:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4f9c7e2d1aa"
down_revision: Union[str, None] = "6f52f8d3b9aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _has_fk(inspector, table_name: str, fk_name: str) -> bool:
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    source_type_enum = sa.Enum("CODE_ANALYSIS", "SWAGGER_IMPORT", name="api_mock_source_type_enum")
    rule_mode_enum = sa.Enum("STATIC", "MOCKJS", "PROXY", name="api_mock_rule_mode_enum")
    collab_event_type_enum = sa.Enum("DRAFT", "SAVE", "CONFLICT", "PRESENCE", name="api_mock_collab_event_type_enum")
    job_status_enum = sa.Enum("PENDING", "RUNNING", "SUCCESS", "FAILED", name="api_mock_job_status_enum")

    source_type_enum.create(bind, checkfirst=True)
    rule_mode_enum.create(bind, checkfirst=True)
    collab_event_type_enum.create(bind, checkfirst=True)
    job_status_enum.create(bind, checkfirst=True)

    if not inspector.has_table("sdd_api_mock_projects"):
        op.create_table(
            "sdd_api_mock_projects",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("proxy_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("proxy_base_url", sa.String(length=1000), nullable=True),
            sa.Column("temp_workspace_path", sa.String(length=1000), nullable=False),
            sa.Column("active_source_version_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "task_id", name="uq_api_mock_project_workspace_task"),
        )

    if not inspector.has_table("sdd_api_mock_source_versions"):
        op.create_table(
            "sdd_api_mock_source_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("source_type", source_type_enum, nullable=False),
            sa.Column("source_name", sa.String(length=500), nullable=True),
            sa.Column("raw_content", sa.Text(), nullable=False),
            sa.Column("normalized_oas_json", sa.JSON(), nullable=False),
            sa.Column("summary_json", sa.JSON(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["project_id"], ["sdd_api_mock_projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("sdd_api_mock_endpoints"):
        op.create_table(
            "sdd_api_mock_endpoints",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("source_version_id", sa.String(length=36), nullable=False),
            sa.Column("method", sa.String(length=16), nullable=False),
            sa.Column("path", sa.String(length=800), nullable=False),
            sa.Column("operation_id", sa.String(length=255), nullable=True),
            sa.Column("tag", sa.String(length=255), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("request_schema_json", sa.JSON(), nullable=True),
            sa.Column("response_schema_json", sa.JSON(), nullable=True),
            sa.Column("entity_refs_json", sa.JSON(), nullable=True),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["project_id"], ["sdd_api_mock_projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_version_id"], ["sdd_api_mock_source_versions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("sdd_api_mock_entities"):
        op.create_table(
            "sdd_api_mock_entities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("source_version_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("schema_json", sa.JSON(), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["project_id"], ["sdd_api_mock_projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_version_id"], ["sdd_api_mock_source_versions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("sdd_api_mock_rules"):
        op.create_table(
            "sdd_api_mock_rules",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("endpoint_id", sa.String(length=36), nullable=False),
            sa.Column("mode", rule_mode_enum, nullable=False),
            sa.Column("static_body_json", sa.JSON(), nullable=True),
            sa.Column("mockjs_template", sa.Text(), nullable=True),
            sa.Column("status_code", sa.Integer(), nullable=False, server_default=sa.text("200")),
            sa.Column("headers_json", sa.JSON(), nullable=True),
            sa.Column("cookies_json", sa.JSON(), nullable=True),
            sa.Column("delay_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("updated_by", sa.String(length=36), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["project_id"], ["sdd_api_mock_projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["endpoint_id"], ["sdd_api_mock_endpoints.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "endpoint_id", name="uq_api_mock_rule_project_endpoint"),
        )

    if not inspector.has_table("sdd_api_mock_collab_events"):
        op.create_table(
            "sdd_api_mock_collab_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("endpoint_id", sa.String(length=36), nullable=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", collab_event_type_enum, nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["project_id"], ["sdd_api_mock_projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["endpoint_id"], ["sdd_api_mock_endpoints.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not inspector.has_table("sdd_api_mock_jobs"):
        op.create_table(
            "sdd_api_mock_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("job_type", sa.String(length=64), nullable=False),
            sa.Column("status", job_status_enum, nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["sdd_api_mock_projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_api_mock_projects") and not _has_fk(inspector, "sdd_api_mock_projects", "fk_api_mock_project_active_source_version"):
        op.create_foreign_key(
            "fk_api_mock_project_active_source_version",
            "sdd_api_mock_projects",
            "sdd_api_mock_source_versions",
            ["active_source_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    inspector = sa.inspect(bind)
    index_specs = [
        ("sdd_api_mock_projects", "ix_sdd_api_mock_projects_workspace_id", ["workspace_id"]),
        ("sdd_api_mock_projects", "ix_sdd_api_mock_projects_task_id", ["task_id"]),
        ("sdd_api_mock_projects", "ix_sdd_api_mock_projects_creator_id", ["creator_id"]),
        ("sdd_api_mock_projects", "ix_sdd_api_mock_projects_active_source_version_id", ["active_source_version_id"]),
        ("sdd_api_mock_source_versions", "ix_sdd_api_mock_source_versions_project_id", ["project_id"]),
        ("sdd_api_mock_source_versions", "ix_sdd_api_mock_source_versions_creator_id", ["creator_id"]),
        ("sdd_api_mock_endpoints", "ix_sdd_api_mock_endpoints_project_id", ["project_id"]),
        ("sdd_api_mock_endpoints", "ix_sdd_api_mock_endpoints_source_version_id", ["source_version_id"]),
        ("sdd_api_mock_entities", "ix_sdd_api_mock_entities_project_id", ["project_id"]),
        ("sdd_api_mock_entities", "ix_sdd_api_mock_entities_source_version_id", ["source_version_id"]),
        ("sdd_api_mock_rules", "ix_sdd_api_mock_rules_project_id", ["project_id"]),
        ("sdd_api_mock_rules", "ix_sdd_api_mock_rules_endpoint_id", ["endpoint_id"]),
        ("sdd_api_mock_rules", "ix_sdd_api_mock_rules_updated_by", ["updated_by"]),
        ("sdd_api_mock_collab_events", "ix_sdd_api_mock_collab_events_project_id", ["project_id"]),
        ("sdd_api_mock_collab_events", "ix_sdd_api_mock_collab_events_endpoint_id", ["endpoint_id"]),
        ("sdd_api_mock_collab_events", "ix_sdd_api_mock_collab_events_user_id", ["user_id"]),
        ("sdd_api_mock_jobs", "ix_sdd_api_mock_jobs_project_id", ["project_id"]),
        ("sdd_api_mock_jobs", "ix_sdd_api_mock_jobs_creator_id", ["creator_id"]),
    ]

    for table_name, index_name, columns in index_specs:
        if inspector.has_table(table_name) and not _has_index(inspector, table_name, index_name):
            op.create_index(index_name, table_name, columns)
            inspector = sa.inspect(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_api_mock_projects") and _has_fk(inspector, "sdd_api_mock_projects", "fk_api_mock_project_active_source_version"):
        op.drop_constraint("fk_api_mock_project_active_source_version", "sdd_api_mock_projects", type_="foreignkey")

    table_order = [
        "sdd_api_mock_jobs",
        "sdd_api_mock_collab_events",
        "sdd_api_mock_rules",
        "sdd_api_mock_entities",
        "sdd_api_mock_endpoints",
        "sdd_api_mock_source_versions",
        "sdd_api_mock_projects",
    ]
    for table_name in table_order:
        inspector = sa.inspect(bind)
        if inspector.has_table(table_name):
            op.drop_table(table_name)

    source_type_enum = sa.Enum("CODE_ANALYSIS", "SWAGGER_IMPORT", name="api_mock_source_type_enum")
    rule_mode_enum = sa.Enum("STATIC", "MOCKJS", "PROXY", name="api_mock_rule_mode_enum")
    collab_event_type_enum = sa.Enum("DRAFT", "SAVE", "CONFLICT", "PRESENCE", name="api_mock_collab_event_type_enum")
    job_status_enum = sa.Enum("PENDING", "RUNNING", "SUCCESS", "FAILED", name="api_mock_job_status_enum")

    source_type_enum.drop(bind, checkfirst=True)
    rule_mode_enum.drop(bind, checkfirst=True)
    collab_event_type_enum.drop(bind, checkfirst=True)
    job_status_enum.drop(bind, checkfirst=True)
