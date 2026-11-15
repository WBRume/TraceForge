"""Correlate DSH's live block indexes with the completed assistant message."""

from dataclasses import replace

from app.agents.events import AgentEvent


class DshTextEvents:
    def __init__(self) -> None:
        self.completed: list[str] = []
        self.pending: dict[str, str] = {}
        self.attempt_id: str | None = None
        self.turn: int | None = None
        self.step: int | None = None
        self.message_number = 0

    def _scope(self, data: dict) -> str:
        if data.get("turn") is None or data.get("step") is None:
            return f"legacy:{self.message_number}:"
        return f"{data['turn']}:{data['step']}:"

    def live_event(self, frame: dict) -> dict | None:
        if frame.get("type") == "start":
            self.attempt_id = frame.get("attemptId")
            self.turn, self.step = frame.get("turn"), frame.get("step")
        elif self.attempt_id and frame.get("attemptId") == self.attempt_id:
            if frame.get("type") == "chunk":
                return {
                    "type": "assistant/chunk",
                    "data": {
                        "turn": self.turn,
                        "step": self.step,
                        "chunk": frame.get("chunk"),
                    },
                }
            if frame.get("type") == "end":
                self.attempt_id = None
                if (frame.get("outcome") or {}).get("eventType") != "assistant/message":
                    return {"type": "assistant/attempt"}
        return None

    def project(self, event: dict, unified: AgentEvent | None) -> list[AgentEvent]:
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "assistant/attempt":
            return self._discard_pending()
        if kind == "assistant/chunk":
            chunk = data.get("chunk")
            index = chunk.get("index", 0) if isinstance(chunk, dict) else 0
            key = f"{self._scope(data)}{index}"
            if unified is not None and unified.type == "text_delta":
                self.pending[key] = self.pending.get(key, "") + unified.payload["delta"]
                return [replace(unified, payload={**unified.payload, "segment_id": key})]
            if isinstance(chunk, dict) and chunk.get("type") == "block-start" and chunk.get("blockType") == "text":
                self.pending.setdefault(key, "")
        events = [unified] if unified is not None else []
        if kind != "assistant/message":
            return events
        prefix = self._scope(data)
        self.message_number += 1
        if unified is None or unified.type != "text":
            return events + self._discard_pending()

        message = data.get("message") if isinstance(data.get("message"), dict) else data
        blocks = [
            str(block.get("text") or "").strip()
            for block in message.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text" and str(block.get("text") or "").strip()
        ]
        candidates = [key for key, text in self.pending.items() if key.startswith(prefix) and text.strip()]
        events = []
        for index, text in enumerate(blocks):
            key = (
                candidates[index]
                if len(candidates) == len(blocks)
                else next(
                    (key for key in candidates if key in self.pending and text.startswith(self.pending[key].strip())),
                    None,
                )
            )
            if key is not None:
                self.pending.pop(key)
            events.append(replace(unified, payload={**unified.payload, "text": text, "segment_id": key}))
        self.completed.extend(blocks)
        return events + self._discard_pending()

    def _discard_pending(self) -> list[AgentEvent]:
        if not self.pending:
            return []
        keys = list(self.pending)
        self.pending.clear()
        return [AgentEvent(type="text_discarded", payload={"segment_ids": keys}, provider="dsh")]

    def finish(self) -> list[AgentEvent]:
        """Preserve legacy delta-only replies as one completed message per block."""
        events = [
            AgentEvent(type="text", payload={"text": text.strip(), "segment_id": key}, provider="dsh")
            for key, text in self.pending.items()
            if text.strip()
        ]
        self.completed.extend(event.payload["text"] for event in events)
        self.pending.clear()
        return events
