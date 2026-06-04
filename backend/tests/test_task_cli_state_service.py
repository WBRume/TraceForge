import os
import sys
from pathlib import Path


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.services import task_cli_state_service as service  # noqa: E402


def test_session_context_uses_cli_project_store_snapshot(tmp_path, monkeypatch):
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    project_path = tmp_path / "workspace" / "base"
    local_claude = project_path / ".claude"
    local_claude.mkdir(parents=True)

    session_id = "23aa02a5-0499-480c-9083-55a4ba59277b"
    project_store = Path(service._claude_project_store_dir(str(project_path)))
    project_store.mkdir(parents=True)
    (project_store / f"{session_id}.jsonl").write_text(
        '{"type":"result","subtype":"success"}\n',
        encoding="utf-8",
    )

    source_kind, source_dir = service._resolve_session_context_location(
        str(project_path),
        session_id,
    )

    assert source_kind == "project_store"
    assert Path(source_dir) == project_store


def test_session_context_does_not_fallback_to_workspace_claude(
    tmp_path,
    monkeypatch,
):
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    project_path = tmp_path / "workspace" / "base"
    local_claude = project_path / ".claude"
    local_claude.mkdir(parents=True)

    session_id = "local-session"
    (local_claude / f"{session_id}.jsonl").write_text(
        '{"type":"result","subtype":"success"}\n',
        encoding="utf-8",
    )

    source_kind, source_dir = service._resolve_session_context_location(
        str(project_path),
        session_id,
    )

    assert source_kind == "project_store"
    assert Path(source_dir) == Path(service._claude_project_store_dir(str(project_path)))
    assert Path(source_dir) != local_claude
    assert service._session_snapshot_exists(source_dir, session_id) is False


def test_claude_project_store_uses_config_dir_override(tmp_path, monkeypatch):
    claude_config = tmp_path / "custom-claude"
    monkeypatch.delenv("CLAUDE_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config))

    project_path = tmp_path / "workspace" / "base"

    assert Path(service._claude_project_store_dir(str(project_path))).parent == (
        claude_config / "projects"
    )
