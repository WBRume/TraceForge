"""Live assistant text, keyed by provider segment until the final message is saved."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.domains.ai.schemas.websocket import WSChatStreamPayload


@dataclass
class Draft:
    id: str
    created_at: str
    provider_message_id: str | None
    content: str = ""
    flush_task: asyncio.Task | None = None

    def cancel_flush(self) -> None:
        if self.flush_task is not None:
            self.flush_task.cancel()
            self.flush_task = None


class AssistantTextStream:
    def __init__(self, owner):
        self._owner = owner
        self._drafts: dict[str, Draft] = {}
        self._closed: set[str] = set()

    async def append(self, payload: dict) -> None:
        delta = payload.get("delta")
        if not delta:
            return
        key = payload.get("segment_id") or ""
        if key in self._closed:
            return
        draft = self._drafts.get(key)
        if draft is None:
            draft = Draft(
                str(uuid4()), datetime.now(timezone.utc).isoformat(), payload.get("provider_message_id"), delta
            )
            self._drafts[key] = draft
            await self._publish(draft, draft.content)
        else:
            draft.content += delta
            if draft.flush_task is None:
                draft.flush_task = asyncio.create_task(self._flush(draft))

    async def _flush(self, draft: Draft) -> None:
        await asyncio.sleep(0.1)
        draft.flush_task = None
        if self._owner.is_current():
            await self._publish(draft, draft.content)

    async def _publish(self, draft: Draft, content: str | None) -> None:
        # A coalesced prefix also lets a reconnected viewer resume from the next frame.
        await self._owner.frontend.push(
            "chat_message_stream",
            WSChatStreamPayload(
                task_id=self._owner.task_id,
                id=draft.id,
                content=content,
                created_at=draft.created_at,
                session_generation=self._owner.session_generation,
                session_revision=self._owner.session_revision,
            ).model_dump(),
        )

    def take(self, payload: dict) -> Draft | None:
        key = payload.get("segment_id")
        provider_message_id = payload.get("provider_message_id")
        if key is None and provider_message_id:
            # OpenCode's durable history can reconstruct a message without SSE text IDs.
            text = payload["text"].strip()
            key = next(
                (
                    key
                    for key, draft in self._drafts.items()
                    if draft.provider_message_id == provider_message_id and text.startswith(draft.content.strip())
                ),
                None,
            )
            if key is None:
                return None
        key = key or ""
        if key:
            self._closed.add(key)
        draft = self._drafts.pop(key, None)
        if draft is not None:
            draft.cancel_flush()
        return draft

    async def discard(self, draft: Draft) -> None:
        draft.cancel_flush()
        await self._publish(draft, None)

    async def discard_segments(self, keys: list[str]) -> None:
        for key in keys:
            draft = self._drafts.pop(key, None)
            if draft is not None:
                await self.discard(draft)

    async def finish(self) -> None:
        await self.discard_segments(list(self._drafts))
        self._closed.clear()
