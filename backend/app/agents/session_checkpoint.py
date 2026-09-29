"""Provider session recovery strategies, independent of workspace snapshots.

OpenCode keeps its native message-revert path. These strategies describe the
file-backed Claude/DSH recovery contract used by the shared undo coordinator.
"""
from __future__ import annotations

import os
import shutil
from typing import Protocol


class SessionCheckpointAdapter(Protocol):
    kind: str
    replaces_session_id: bool

    def locate(self, project_path: str, session_id: str | None) -> str | None: ...

    def restore(self, metadata: dict, project_path: str, session_id: str | None) -> None: ...

    async def resume_restored(self, session_id: str | None, project_path: str, checkpoint: str) -> str | None: ...

    async def cleanup_restored(self, session_id: str, checkpoint: str) -> None: ...


class ClaudeSessionCheckpoint:
    kind = "claude_jsonl"
    replaces_session_id = False

    def locate(self, project_path: str, session_id: str | None) -> str | None:
        from app.domains.task.services import task_session_snapshot_service as snapshots

        if not session_id:
            return None
        return snapshots._locate_claude_file(snapshots._claude_store_dir(project_path), session_id)

    def restore(self, metadata: dict, project_path: str, session_id: str | None) -> None:
        from app.domains.task.services import task_session_snapshot_service as snapshots

        target = metadata.get("source") or self.locate(project_path, session_id)
        copied = metadata.get("copy")
        if copied:
            if not target or not os.path.isfile(copied):
                raise ValueError("Provider checkpoint is missing")
            expected = metadata.get("source_sha256")
            if expected and snapshots._sha256_file(copied) != expected:
                raise ValueError("Provider checkpoint is corrupt")
            snapshots._atomic_copy_file(copied, target)
            if snapshots._sha256_file(copied) != snapshots._sha256_file(target):
                raise ValueError("Provider restore verification failed")
        elif target and os.path.exists(target):
            os.remove(target)

    async def resume_restored(self, session_id: str | None, project_path: str, checkpoint: str) -> str | None:
        return None

    async def cleanup_restored(self, session_id: str, checkpoint: str) -> None:
        return None


class DshSessionCheckpoint:
    kind = "dsh_session_dir"
    replaces_session_id = True

    def locate(self, project_path: str, session_id: str | None) -> str | None:
        from app.agents.adapters.dsh.session_files import locate_session_log
        from app.agents.errors import SessionLogNotFoundError
        from app.domains.task.services import task_session_snapshot_service as snapshots

        if not session_id:
            return None
        try:
            log_path, _ = locate_session_log(snapshots._dsh_root(), session_id)
        except SessionLogNotFoundError:
            return None
        return os.path.dirname(log_path)

    def restore(self, metadata: dict, project_path: str, session_id: str | None) -> None:
        from app.domains.task.services import task_session_snapshot_service as snapshots

        target = metadata.get("source") or self.locate(project_path, session_id)
        copied = metadata.get("copy")
        if copied:
            if not target or not os.path.isdir(copied):
                raise ValueError("Provider checkpoint is missing")
            expected = snapshots._file_manifest(copied)
            if metadata.get("files") is not None and expected != metadata["files"]:
                raise ValueError("Provider checkpoint is corrupt")
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(copied, target)
            if snapshots._file_manifest(target) != expected:
                raise ValueError("Provider restore verification failed")
        elif target and os.path.isdir(target):
            shutil.rmtree(target)

    async def resume_restored(self, session_id: str | None, project_path: str, checkpoint: str) -> str | None:
        from app.domains.task.services import task_session_snapshot_service as snapshots

        if not session_id:
            return None
        return await snapshots.fork_dsh_session(session_id, project_path, checkpoint_root=checkpoint)

    async def cleanup_restored(self, session_id: str, checkpoint: str) -> None:
        from app.domains.task.services import task_session_snapshot_service as snapshots

        await snapshots.cleanup_dsh_session(session_id, checkpoint_root=checkpoint)


class NativeSessionCheckpoint(ClaudeSessionCheckpoint):
    kind = "none"

    def locate(self, project_path: str, session_id: str | None) -> str | None:
        return None

    def restore(self, metadata: dict, project_path: str, session_id: str | None) -> None:
        return None


_CLAUDE = ClaudeSessionCheckpoint()
_DSH = DshSessionCheckpoint()
_NATIVE = NativeSessionCheckpoint()
_ADAPTERS: dict[str, SessionCheckpointAdapter] = {
    "claude": _CLAUDE, "claude-code": _CLAUDE,
    "dsh": _DSH, "dsh-webhost": _DSH, "webhost": _DSH,
    "opencode": _NATIVE, "none": _NATIVE, "mock": _NATIVE, "": _NATIVE,
}


def session_checkpoint_adapter(provider: str) -> SessionCheckpointAdapter:
    try:
        return _ADAPTERS[provider.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported session checkpoint provider: {provider}") from exc
