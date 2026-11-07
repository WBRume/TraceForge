import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.domain_tools.invocation import active_domain_run
from app.domains.ai.services.jobs import provider_turn
from app.domains.skill.services import skill_analysis_service as service


@pytest.mark.asyncio
async def test_analysis_notification_serializes_persisted_timestamps(monkeypatch):
    from app.domains.notification.ws.notification_manager import notification_ws_manager
    from app.domains.skill.models.skill import SddSkillAnalysis, SkillAnalysisRefKind, SkillAnalysisStatus

    received = asyncio.Event()
    messages = []

    def broadcast(room, text, **kwargs):
        messages.append((room, json.loads(text)))
        received.set()
        return 1

    monkeypatch.setattr(notification_ws_manager.registry, "broadcast_text", broadcast)
    now = datetime(2026, 11, 7, 2, 0, 0)
    analysis = SddSkillAnalysis(
        id="analysis",
        workspace_id="workspace",
        skill_id="skill",
        created_by_id="user",
        ref_kind=SkillAnalysisRefKind.WORKTREE,
        status=SkillAnalysisStatus.RUNNING,
        progress=60,
        created_at=now,
        updated_at=now,
        started_at=now,
        file_stats_json={"domain_milestones": [{"stage": "started", "sequence": 1}]},
    )
    token = service._notification_loop.set(asyncio.get_running_loop())
    try:
        service._publish_analysis(analysis)
        await asyncio.wait_for(received.wait(), timeout=5)
    finally:
        service._notification_loop.reset(token)

    room, message = messages[0]
    assert room == "notification:user"
    payload = message["payload"]["analysis"]
    assert payload["started_at"] == "2026-11-07T02:00:00"
    assert payload["created_at"] == "2026-11-07T02:00:00"
    assert payload["file_stats"]["domain_milestones"] == [{"stage": "started", "sequence": 1}]


@pytest.mark.asyncio
async def test_sync_route_worker_publishes_milestones_on_application_loop(monkeypatch):
    import anyio

    from app.domains.notification.ws.notification_manager import notification_ws_manager

    expected_loop = asyncio.get_running_loop()
    received = asyncio.Event()
    messages = []

    async def send(user_id, payload):
        assert asyncio.get_running_loop() is expected_loop
        messages.append((user_id, payload))
        received.set()

    def run(analysis_id):
        assert service._notification_loop.get() is expected_loop
        service._publish_analysis(SimpleNamespace(id=analysis_id, created_by_id="user"))

    monkeypatch.setattr(service, "run_analysis_job", run)
    monkeypatch.setattr(service, "serialize_analysis", lambda value: {"id": value.id, "status": "RUNNING"})
    monkeypatch.setattr(notification_ws_manager, "send_message_to_user", send)
    await anyio.to_thread.run_sync(service.schedule_analysis_job, "analysis")
    await asyncio.wait_for(received.wait(), timeout=5)
    assert messages == [
        ("user", {"type": "skill_analysis_updated", "analysis": {"id": "analysis", "status": "RUNNING"}})
    ]


def test_semantic_review_uses_selected_backend_and_typed_submission(monkeypatch, tmp_path):
    selected = []

    async def provider(prompt, project_path, **kwargs):
        selected.append(kwargs["backend_name"])
        assert project_path == str(tmp_path)
        run = active_domain_run.get()
        assert not (
            await run.invoke(
                run.tool.name,
                {
                    "risk_level": "LOW",
                    "complexity": "LOW",
                    "review_priority": "LOW",
                    "risk_items": [],
                    "review_suggestions": [],
                },
                "one",
            )
        ).is_error
        return {"session_id": "provider-session"}

    monkeypatch.setattr(provider_turn, "run_cli_single_turn", provider)
    result = asyncio.run(service._run_semantic_analysis(str(tmp_path), backend_name="opencode"))
    assert selected == ["opencode"]
    assert result["_provider_session_id"] == "provider-session"
    assert result["risk_level"] == "LOW"


def test_semantic_failure_is_not_retried_or_filled_from_prose(monkeypatch, tmp_path):
    calls = []

    async def provider(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("Stopped")

    monkeypatch.setattr(provider_turn, "run_cli_single_turn", provider)
    with pytest.raises(TimeoutError):
        asyncio.run(service._run_semantic_analysis(str(tmp_path), backend_name="opencode"))
    assert len(calls) == 1


def test_snapshot_is_under_shared_skill_storage_and_preserves_content(monkeypatch, tmp_path):
    monkeypatch.setattr(service.storage_service, "_skills_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        service, "_copy_worktree_snapshot", lambda _, target: Path(target, "SKILL.md").write_text("check")
    )
    root = Path(service._make_snapshot(SimpleNamespace(), SimpleNamespace(commit_sha=None)))
    assert root.is_relative_to(tmp_path / ".analysis-snapshots")
    assert (root / "package/SKILL.md").read_text() == "check"
