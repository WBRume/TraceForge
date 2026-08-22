"""
Task domain models registry.

Late imports register cross-domain tables into Base.metadata so that
create_all / autogenerate always see the complete schema.
"""
from app.domains.task.models import chat as _chat_models  # noqa: E402,F401
from app.domains.task.models import diagnosis as _diagnosis_models  # noqa: E402,F401
from app.domains.task.models import pre_input as _pre_input_models  # noqa: E402,F401
from app.domains.task.models import task as _task_models  # noqa: E402,F401
from app.domains.task.models import task_cli_bootstrap as _task_cli_bootstrap_models  # noqa: E402,F401
from app.domains.task.models import task_repository as _task_repo_models  # noqa: E402,F401

# Notification tables reference workspaces/users; register alongside task models
# so create_all / autogenerate always see the complete schema.
from app.domains.notification.models import notification as _notification_models  # noqa: E402,F401

# Case center tables reference sdd_tasks; register them here so the metadata
# is complete even when tests only import task models.
from app.domains.case_center.models import case as _case_center_models  # noqa: E402,F401
