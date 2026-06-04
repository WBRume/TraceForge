from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# ----------------- Custom Code -----------------
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import settings
from app.database import Base

# 显式导入所有模型表以便 Alembic 能够发现它们
from app.models.user import User, Workspace, WorkspaceMember
from app.models.task import SddTask, SddPlanNode
from app.models.log import SddExecutionLog
from app.models.test_result import SddTestResult
from app.models.asset import (
    SddAsset,
    SddAssetVersion,
    SddAssetThread,
    SddAssetThreadMessage,
    SddAssetResolutionProposal,
)
from app.models.metric import SddDashboardMetric
from app.models.chat import ChatMessage
from app.models.skill import (
    SddSkill,
    SddTaskSkill,
    SddSkillVersion,
    SddSkillExpertRating,
    SddSkillReviewComment,
)
from app.models.api_mock import (
    SddApiMockProject,
    SddApiMockSourceVersion,
    SddApiMockEndpoint,
    SddApiMockEntity,
    SddApiMockRule,
    SddApiMockCollabEvent,
    SddApiMockJob,
)
from app.models.task_cli_bootstrap import SddTaskCliBootstrap
from app.models.ai_job import SddAiJob
from app.models.provision_job import SddProvisionJob
from app.models.task_change import (
    SddTaskChangeProposal,
    SddTaskChangeProposalFile,
    SddTaskVerificationRun,
    SddTaskConflictReport,
)
from app.models.workspace_asset import (
    SddAiOutput,
    SddClarification,
    SddDecision,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddKnowledgeAsset,
    SddRequirement,
    SddRequirementAuditLog,
    SddRequirementImportBatch,
    SddRequirementImportItem,
    SddTaskRequirement,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Overwrite sqlalchemy.url dynamically
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata
# -----------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
