"""Opt-in live prerequisites for task-session undo.

The full provider/password scenario is intentionally opt-in because it spends
model credits and must create its own temporary task/worktree in the deployed
environment.  This gate still refuses to run against the unsafe local lock
backend and verifies all three configured provider entry points first.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import shutil
import sys
import tempfile
import uuid

import pytest

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter
from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.contract import AgentRunRequest
from app.config import settings
from app.core import distributed_lock
from app.domains.task.services import task_session_snapshot_service as snapshots


pytestmark = pytest.mark.live_revert


def test_live_revert_prerequisites_use_redis_and_real_provider_endpoints():
    if os.environ.get("TRACEFORGE_LIVE_REVERT") != "1":
        pytest.skip("set TRACEFORGE_LIVE_REVERT=1 to probe live undo prerequisites")

    async def probe() -> None:
        # Reset the cached provider so this test observes the same settings
        # used by a freshly started TraceForge process.
        distributed_lock._PROVIDER = None
        lock_provider = await distributed_lock.get_lock_provider()
        assert settings.REDIS_ENABLED is True
        assert str(settings.DISTRIBUTED_LOCK_BACKEND).lower() == "redis"
        assert lock_provider.backend_name == "redis"

        adapters = (
            ("claude", ClaudeCodeAdapter()),
            ("dsh", DshServerAdapter(str(settings.DSH_SERVER_URL))),
            ("opencode", OpenCodeAdapter(str(settings.OPENCODE_SERVER_URL))),
        )
        try:
            for name, adapter in adapters:
                try:
                    await adapter.probe()
                except Exception as exc:
                    pytest.fail(f"{name} provider prerequisite failed: {type(exc).__name__}")
        finally:
            for _name, adapter in adapters:
                close = getattr(adapter, "close", None)
                if close:
                    await close()

    asyncio.run(probe())


def _secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _assert_secret_present(present: bool, secret_hash: str, *, provider: str) -> None:
    if not present:
        pytest.fail(f"{provider} did not return the expected marker hash={secret_hash}")


def _assert_secret_absent(present: bool, secret_hash: str, *, provider: str) -> None:
    if present:
        pytest.fail(f"{provider} still exposes reverted marker hash={secret_hash}")


def _git(cwd: str, *args: str) -> None:
    result = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise AssertionError(f"git command failed: {args[:2]}")


@pytest.mark.parametrize("provider_name", ["claude-code", "dsh", "opencode"])
def test_live_provider_revert_forgets_old_context_and_accepts_re_edit(provider_name: str):
    """Run the provider-level acceptance scenario against isolated temporary state."""
    if os.environ.get("TRACEFORGE_LIVE_REVERT") != "1":
        pytest.skip("set TRACEFORGE_LIVE_REVERT=1 to run provider undo acceptance")

    async def run_scenario() -> None:
        old_secret = f"TF_FORGET_{uuid.uuid4().hex}"
        new_secret = f"TF_KEEP_{uuid.uuid4().hex}"
        adapter = {
            "claude-code": ClaudeCodeAdapter(),
            "dsh": DshServerAdapter(str(settings.DSH_SERVER_URL)),
            "opencode": OpenCodeAdapter(str(settings.OPENCODE_SERVER_URL)),
        }[provider_name]
        provider_session_ids: list[str] = []
        provider_message_ids: list[str] = []
        checkpoint_root: str | None = None
        project_path: str | None = None
        forked_provider_session_id: str | None = None
        temporary_root = tempfile.mkdtemp(prefix="traceforge-live-undo-")
        first = second = reedited = None
        edited_result = ""
        try:
            project_path = os.path.join(temporary_root, "task")
            os.makedirs(project_path)
            _git(project_path, "init")
            _git(project_path, "config", "user.email", "traceforge-live@example.test")
            _git(project_path, "config", "user.name", "TraceForge Live")
            marker_path = os.path.join(project_path, "before.txt")
            with open(marker_path, "w", encoding="utf-8") as marker:
                marker.write("baseline\n")
            _git(project_path, "add", ".")
            _git(project_path, "commit", "-m", "live undo baseline")

            if provider_name in {"claude-code", "dsh"}:
                checkpoint_root = os.path.join(temporary_root, "provider-checkpoint")
                os.makedirs(checkpoint_root)
                snapshots._provider_checkpoint_sync(
                    provider_name,
                    project_path,
                    None,
                    checkpoint_root,
                )

            async def invoke(prompt: str, session_id: str | None = None):
                request = AgentRunRequest(
                    run_id=f"live-undo-{uuid.uuid4().hex}",
                    prompt=prompt,
                    project_path=project_path or ".",
                    session_id=session_id,
                    timeout_seconds=900,
                    startup_timeout_seconds=120,
                    idle_timeout_seconds=600,
                )
                return await adapter.run(request, lambda _event: asyncio.sleep(0))

            async def invoke_recall(session_id: str):
                # Some OpenCode builds publish the completion event before the
                # model text is available to the final-message endpoint.  A
                # bounded retry keeps the acceptance test about context
                # forgetting, not that transient provider race.
                latest = None
                for attempt in range(3):
                    latest = await invoke(
                        "What exact test fixture marker did I give you in the preceding turn? Reply with only that marker.",
                        session_id or None,
                    )
                    if str(latest.result_text or "").strip():
                        return latest
                    if attempt < 2:
                        await asyncio.sleep(0.5)
                return latest

            first = await invoke(
                f"Remember this test fixture marker exactly: {old_secret}. Reply with only the marker."
            )
            first_session_id = str(first.session_id or getattr(adapter, "_session_id", "")).strip()
            if first_session_id:
                provider_session_ids.append(first_session_id)
            if provider_name == "opencode":
                ids = first.metadata.get("provider_message_ids") if isinstance(first.metadata, dict) else []
                provider_message_ids.extend(str(item) for item in ids or [] if str(item).strip())

            second = await invoke_recall(first_session_id)
            _assert_secret_present(
                old_secret in str(second.result_text or ""),
                _secret_hash(old_secret),
                provider=provider_name,
            )
            second_session_id = str(second.session_id or getattr(adapter, "_session_id", "")).strip()
            if second_session_id and second_session_id not in provider_session_ids:
                provider_session_ids.append(second_session_id)
            if provider_name == "opencode":
                ids = second.metadata.get("provider_message_ids") if isinstance(second.metadata, dict) else []
                provider_message_ids.extend(str(item) for item in ids or [] if str(item).strip())

            if provider_name == "opencode":
                target_user_id = str(
                    first.metadata.get("provider_user_message_id")
                    if isinstance(first.metadata, dict)
                    else ""
                ).strip()
                assert target_user_id
                assert first_session_id
                await adapter.interrupt(session_id=first_session_id)
                await adapter.wait_until_idle(first_session_id)
                assert await adapter.revert_message(first_session_id, target_user_id)
                for message_id in reversed(list(dict.fromkeys(provider_message_ids))):
                    assert await adapter.delete_message(first_session_id, message_id)
                remaining = await adapter.list_messages(first_session_id)
                _assert_secret_absent(
                    old_secret in json.dumps(remaining, ensure_ascii=False),
                    _secret_hash(old_secret),
                    provider=provider_name,
                )
            else:
                assert checkpoint_root
                await snapshots.restore_provider(
                    checkpoint_root,
                    provider_name,
                    project_path,
                    first_session_id or None,
                )
                if provider_name == "dsh":
                    # The deployed Web Host has no unload endpoint.  Validate
                    # the same TraceForge isolation path used by task undo:
                    # restore the prefix, fork it to a cold identity, then
                    # reconnect with a fresh adapter so the old live Agent is
                    # never reused.
                    forked_provider_session_id = await snapshots.fork_dsh_session(
                        first_session_id or "",
                        project_path,
                    )
                    await adapter.close()
                    adapter = DshServerAdapter(str(settings.DSH_SERVER_URL))

            reedited = await invoke(
                f"This is the replacement test fixture marker: {new_secret}. Reply with only the marker.",
                forked_provider_session_id if provider_name == "dsh" else None,
            )
            reedited_session_id = str(
                reedited.session_id or getattr(adapter, "_session_id", "")
            ).strip()
            if reedited_session_id and reedited_session_id not in provider_session_ids:
                provider_session_ids.append(reedited_session_id)
            if provider_name == "opencode":
                ids = reedited.metadata.get("provider_message_ids") if isinstance(reedited.metadata, dict) else []
                provider_message_ids.extend(str(item) for item in ids or [] if str(item).strip())
            edited_result = str(reedited.result_text or "")
            _assert_secret_present(
                new_secret in edited_result,
                _secret_hash(new_secret),
                provider=provider_name,
            )
            _assert_secret_absent(
                old_secret in edited_result,
                _secret_hash(old_secret),
                provider=provider_name,
            )
        finally:
            if provider_name == "opencode":
                if provider_session_ids:
                    for message_id in reversed(list(dict.fromkeys(provider_message_ids))):
                        try:
                            await adapter.delete_message(provider_session_ids[0], message_id)
                        except Exception:
                            pass
                    try:
                        await adapter.delete_session(provider_session_ids[0])
                    except Exception:
                        pass
            elif checkpoint_root and project_path:
                for session_id in provider_session_ids:
                    try:
                        await snapshots.restore_provider(
                            checkpoint_root,
                            provider_name,
                            project_path,
                            session_id,
                        )
                    except Exception:
                        pass
                if forked_provider_session_id:
                    try:
                        await snapshots.cleanup_dsh_session(forked_provider_session_id)
                    except Exception:
                        pass
            await adapter.close()
            shutil.rmtree(temporary_root, ignore_errors=True)
            # Do not leave generated markers in pytest's traceback locals when
            # a provider assertion fails.  Failure output may contain hashes,
            # but must never contain the marker itself.
            old_secret = "<redacted>"
            new_secret = "<redacted>"
            edited_result = ""
            first = second = reedited = None

    asyncio.run(run_scenario())
