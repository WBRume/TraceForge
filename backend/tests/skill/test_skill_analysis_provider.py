import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.skill.services import skill_analysis_service as service


def test_semantic_review_uses_selected_remote_backend(monkeypatch, tmp_path):
    selected = []

    class Bridge:
        session_id = "real-provider-session-locator"

        async def start_session(self, **kwargs):
            assert kwargs["project_path"] == str(tmp_path)
            await kwargs["event_callback"]({"type": "result", "result": '{"risk_level":"LOW","risk_items":[]}'})

        async def wait(self):
            pass

    def create(backend):
        selected.append(backend)
        return Bridge()

    monkeypatch.setattr(service, "create_legacy_bridge", create)
    result = asyncio.run(service._run_semantic_analysis(str(tmp_path), backend_name="opencode"))
    assert selected == ["opencode"]
    assert result["_provider_session_id"] == "real-provider-session-locator"


def test_semantic_timeout_cancels_provider(monkeypatch, tmp_path):
    bridge = SimpleNamespace(start_session=AsyncMock(), wait=AsyncMock(side_effect=TimeoutError), cancel=AsyncMock())
    monkeypatch.setattr(service, "create_legacy_bridge", lambda _: bridge)
    with pytest.raises(TimeoutError):
        asyncio.run(service._run_semantic_analysis(str(tmp_path), backend_name="opencode"))
    bridge.cancel.assert_awaited_once()


def test_snapshot_is_under_shared_skill_storage_and_preserves_content(monkeypatch, tmp_path):
    monkeypatch.setattr(service.storage_service, "_skills_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        service, "_copy_worktree_snapshot", lambda _, target: Path(target, "SKILL.md").write_text("check")
    )
    root = Path(service._make_snapshot(SimpleNamespace(), SimpleNamespace(commit_sha=None)))
    assert root.is_relative_to(tmp_path / ".analysis-snapshots")
    assert (root / "package/SKILL.md").read_text() == "check"


def test_remote_background_permissions_are_rejected_and_provider_closed(monkeypatch, tmp_path):
    provider = SimpleNamespace(
        capabilities=SimpleNamespace(execution_kind="REMOTE_SESSION"),
        respond_to_ask_user=AsyncMock(),
        close=AsyncMock(),
    )
    bridge = SimpleNamespace(backend=provider, cancel=AsyncMock(), session_id=None)
    monkeypatch.setattr(service, "create_legacy_bridge", lambda _: bridge)

    async def run(actual, request, on_event):
        assert actual is provider
        assert request.permission_mode == "read-only"
        await on_event(
            SimpleNamespace(type="ask_user", payload={"ask_user_id": "per_test", "permission_request": True})
        )
        return SimpleNamespace(
            success=True, session_id="ses_remote", result_text='{"risk_level":"LOW","risk_items":[]}'
        )

    monkeypatch.setattr(service, "run_agent_backend_with_logging", run)
    result = asyncio.run(service._run_semantic_analysis(str(tmp_path), backend_name="opencode"))
    assert result["_provider_session_id"] == "ses_remote"
    provider.respond_to_ask_user.assert_awaited_once_with("per_test", "reject")
    provider.close.assert_awaited_once()
