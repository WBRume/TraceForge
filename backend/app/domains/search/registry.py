"""Standalone workers need the same mapped relationship targets as the API."""
from importlib import import_module


def load_models():
    for module in ("user", "task", "log", "test_result", "asset", "metric", "chat", "skill",
                   "api_mock", "task_cli_bootstrap", "ai_job", "provision_job", "task_change",
                   "workspace_asset", "management", "workspace_repository", "task_repository",
                   "session_turn", "system_config"):
        import_module("app.models." + module)
