"""Explicit acceptance against the running full HTTP service and configured MySQL.

This restarts port 8000. Run only in an authorized local maintenance window:
python -m tests.live_opencode.verify_http_recovery --run-live --restart-http
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import time
import uuid

import httpx
import websockets

from tests.live_opencode.http_support import (
    BASE_URL, FullService, baseline, cleanup_fixture, load_models, read_state, seed_task, seed_workspace, until,
)
from tests.live_opencode.transport import record
from tests.live_opencode.verify_recovery import (
    BACKEND, CASES, emit, prepare, provider_state, read_jsonl,
)

HTTP_CASES = {
    "http_graceful_running": {"tool_seconds": 65, "hard_seconds": 210, "graceful": True},
    "http_crash_running": {"tool_seconds": 55, "hard_seconds": 180},
    "http_crash_finished": {"tool_seconds": 15, "hard_seconds": 65, "offline_completion": True},
}


class Observer:
    def __init__(self, root, task_id, token, name, workspace_id):
        self.root, self.task_id, self.token, self.name = root, task_id, token, name
        self.websocket = None
        self.reader = None
        self.frames = []
        self.workspace_id = workspace_id
        self.synced = asyncio.Event()

    async def connect(self):
        self.websocket = await websockets.connect(
            f"ws://127.0.0.1:8000/ws/task/{self.task_id}?token={self.token}&client_id={uuid.uuid4()}",
            open_timeout=20,
        )
        record(self.root / "observers.jsonl", "connected", observer=self.name)

        async def consume():
            try:
                async for raw in self.websocket:
                    frame = json.loads(raw)
                    if frame.get("type") == "resync_required":
                        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                            snapshot = await client.get(
                                f"{BASE_URL}/api/workspaces/{self.workspace_id}/tasks/{self.task_id}/session-state",
                                headers={"Authorization": "Bearer " + self.token})
                            snapshot.raise_for_status()
                        await self.websocket.send(json.dumps({"type": "resync_complete", "payload": {
                            "epoch": frame["epoch"], "barrier_sequence": frame["barrier_sequence"]}}))
                    if frame.get("type") in {"resync_ok", "resume_ok"}:
                        self.synced.set()
                    if frame.get("type") == "event":
                        frame = {"type": frame["event_type"], "payload": frame["payload"]}
                    self.frames.append(frame)
                    payload = frame.get("payload") or {}
                    record(self.root / "observers.jsonl", "event", observer=self.name,
                           event_type=frame.get("type"), job_status=(payload.get("job") or {}).get("status"))
            except websockets.ConnectionClosed:
                record(self.root / "observers.jsonl", "disconnected", observer=self.name)

        self.reader = asyncio.create_task(consume())
        await asyncio.wait_for(self.synced.wait(), 25)

    async def close(self):
        if self.websocket:
            await self.websocket.close()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def job_matching(task_id, predicate):
    state = await asyncio.to_thread(read_state, task_id)
    return state if predicate(state) else None


async def check_stale_owner(original):
    """The real MySQL fence must reject a previous process's late checkpoint."""
    from types import SimpleNamespace
    from app.agents.errors import AgentExecutionDetached
    from app.domains.ai.services.jobs.remote_recovery import save_checkpoint_sync
    attempt = SimpleNamespace(task_id=original["task_id"], job_id=original["job_id"],
                              run_token=original["run_token"], worker_boot_id=original["worker_boot_id"])
    try:
        await asyncio.to_thread(save_checkpoint_sync, attempt, original["checkpoint"])
    except AgentExecutionDetached:
        return True
    raise AssertionError("The old owner was allowed to write a checkpoint")


async def run_case(root, case, model, adapter, service, ids, tokens):
    spec = HTTP_CASES[case]
    CASES[case] = spec
    config = prepare(root, case, model)
    seed_task(config, ids, root)
    task_id = config["task_id"]
    prefix = f'/api/workspaces/{ids["workspace_id"]}/tasks/{task_id}'
    evidence = {"case": case, "task_id": task_id, "thresholds": {
        "idle_seconds": 6, "reconcile_seconds": 1, "hard_seconds": spec["hard_seconds"],
        "heartbeat_seconds": 1, "lease_seconds": 5}, "tool_seconds": spec["tool_seconds"]}
    observers = []
    sid = None
    try:
        await service.start(root, spec["hard_seconds"])
        first_pid = service.process.pid
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=45, trust_env=False) as client:
            owner_headers = {"Authorization": "Bearer " + tokens[0]}
            reader_headers = {"Authorization": "Bearer " + tokens[1]}
            for index, token in enumerate(tokens):
                observer = Observer(root, task_id, token, f"before-{index}", ids["workspace_id"])
                observers.append(observer)
                await observer.connect()
            payload = {"client_message_id": config["request_id"], "content": config["prompt"],
                       "metadata": {"agent_model": {"backend": "opencode", "model": model}}}
            # Real concurrent retries must resolve to one durable submission/job.
            submitted = await asyncio.gather(*[
                client.post(prefix + "/chat-submissions", json=payload, headers=owner_headers)
                for _ in range(2)
            ])
            for response in submitted:
                response.raise_for_status()
            assert submitted[0].json()["id"] == submitted[1].json()["id"]
            evidence["concurrent_duplicate_receipt_id"] = submitted[0].json()["id"]
            write_json(root / "accepted.json", [r.json() for r in submitted])

            async def started():
                state = await asyncio.to_thread(read_state, task_id)
                if state.get("receipt_status") == "FAILED":
                    raise AssertionError(f"Submission failed: {state}")
                if state.get("status") in {"FAILED", "INTERRUPTED", "CANCELLED", "ORPHANED"}:
                    raise AssertionError(f"Job failed before tool start: {state}")
                if state.get("checkpoint") and any(r["kind"] == "started" for r in read_jsonl(root / "work/tool-trace.jsonl")):
                    return state
                return None

            original = await until(started, seconds=150, label="HTTP submitted real tool running")
            cp, sid = original["checkpoint"], original["session_id"]
            evidence.update(job_id=original["job_id"], session_id=sid, original_checkpoint=cp,
                            original_worker_boot_id=original["worker_boot_id"], original_pid=first_pid)
            write_json(root / "before-restart.json", original)
            emit("http_tool_running", case=case, session_id=sid, job_id=original["job_id"])
            assert original["receipt_status"] == "EXECUTING"
            # All readers can leave without stopping the remote run.
            for observer in observers:
                await observer.close()
            await asyncio.sleep(8)  # Exceed idle timeout with zero frontend connections.
            live = await asyncio.to_thread(read_state, task_id)
            assert live["status"] == "RUNNING", live
            assert (await provider_state(adapter, sid))["active"]
            evidence["survived_no_observers_past_idle"] = True
            snapshot = await client.get(prefix + "/session-state", headers=reader_headers)
            snapshot.raise_for_status()
            assert any(j["id"] == original["job_id"] for j in snapshot.json()["jobs"])
            evidence["other_authorized_user_read_active_job"] = True

            await service.stop(graceful=spec.get("graceful", False))
            assert not await http_ready()
            offline = await asyncio.to_thread(read_state, task_id)
            write_json(root / "offline.json", offline)
            remote = await provider_state(adapter, sid)
            assert offline["status"] == "RUNNING", offline
            assert remote["active"], "Stopping the HTTP server interrupted the remote tool"
            evidence["remote_active_after_http_exit"] = True
            if spec.get("offline_completion"):
                async def completed():
                    from app.agents.adapters.opencode.execution import turn_messages
                    state = await provider_state(adapter, sid)
                    turns = turn_messages(state["messages"], cp["prompt_id"])
                    return state if not state["active"] and turns and turns[-1].get("outcome") == "succeeded" else None
                await until(completed, seconds=90, label="provider completed while HTTP offline")
                while time.time() < cp["deadline"] + 0.3:
                    await asyncio.sleep(0.5)
                evidence["completed_offline_and_original_deadline_expired"] = True
            await service.start(root, spec["hard_seconds"])
            evidence["restarted_pid"] = service.process.pid
            recovered = await until(
                lambda: job_matching(task_id, lambda row: row.get("attempt_count", 0) >= 2),
                seconds=60, label="MySQL job claimed by new HTTP process")
            assert recovered["checkpoint"] == cp
            assert recovered["worker_boot_id"] != original["worker_boot_id"]
            if recovered["status"] == "RUNNING":
                assert recovered["run_token"] != original["run_token"]
            evidence.update(recovered_attempt_count=recovered["attempt_count"],
                            recovered_worker_boot_id=recovered["worker_boot_id"],
                            stale_owner_fenced=await check_stale_owner(original))
            write_json(root / "recovered.json", recovered)
            for index, token in enumerate(tokens):
                observer = Observer(root, task_id, token, f"after-{index}", ids["workspace_id"])
                observers.append(observer)
                await observer.connect()
            final = await until(
                lambda: job_matching(task_id, lambda row: row.get("status") in {"SUCCESS", "FAILED", "INTERRUPTED", "ORPHANED", "CANCELLED"}),
                seconds=spec["hard_seconds"] + 30, label="terminal MySQL job and receipt")
            assert final["status"] == "SUCCESS", final
            assert final["receipt_status"] == "SUCCEEDED", final
            assert final["checkpoint"] == cp
            replies = [m for m in final["messages"] if m["role"] == "assistant" and m["content"].strip() == config["marker"]]
            assert len(replies) == 1
            assert sum(m["role"] == "user" for m in final["messages"]) == 1
            snapshot = await client.get(prefix + "/session-state", headers=owner_headers,
                                        params={"client_message_ids": config["request_id"]})
            snapshot.raise_for_status()
            assert snapshot.json()["receipts"][0]["status"] == "SUCCEEDED"
            for headers in (owner_headers, reader_headers):
                jobs = await client.get(prefix + "/ai-jobs", headers=headers, params={"active_only": "false"})
                jobs.raise_for_status()
                assert len(jobs.json()["items"]) == 1 and jobs.json()["items"][0]["status"] == "SUCCESS"
            await asyncio.sleep(2)  # Allow the event outbox to reach both real sockets.
            if not spec.get("offline_completion"):
                for observer in observers[-2:]:
                    assert any(f.get("type") == "chat_job_done" and ((f.get("payload") or {}).get("job") or {}).get("status") == "SUCCESS"
                               for f in observer.frames), f"{observer.name} missed terminal WS event"
            write_json(root / "final.json", final)
            write_json(root / "final-api-snapshot.json", snapshot.json())
            tool_trace = read_jsonl(root / "work/tool-trace.jsonl")
            assert [r["kind"] for r in tool_trace] == ["started", "finished"]
            traces = [r for path in root.glob("http-*.jsonl") for r in read_jsonl(path)]
            prompts = [r for r in traces if r.get("path") == f"/api/session/{sid}/prompt" and r.get("method") == "POST"]
            stops = [r for r in traces if r.get("path") == f"/api/session/{sid}/interrupt"]
            assert len(prompts) == 1 and not stops, {"prompts": prompts, "stops": stops}
            remote = await provider_state(adapter, sid)
            assert not remote["active"]
            assert sum(m.get("type") == "user" for m in remote["messages"]) == 1
            evidence.update(passed=True, final_status=final["status"], receipt_status=final["receipt_status"],
                            prompt_posts=len(prompts), interrupt_requests=len(stops), final_reply_count=len(replies),
                            tool_trace=tool_trace, authorized_users=2,
                            terminal_ws_received_by_both=not spec.get("offline_completion"),
                            terminal_http_snapshot_verified=True)
            emit("http_case_passed", **evidence)
            return evidence
    finally:
        for observer in observers:
            await observer.close()
        state = await asyncio.to_thread(read_state, task_id)
        sid = sid or state.get("session_id")
        if sid:
            remote = await provider_state(adapter, sid)
            if remote["active"]:
                await adapter.cancel_persisted_session(sid)
            assert await adapter.delete_session(sid)
            evidence["session_deleted"] = True
        write_json(root / "evidence.json", evidence)
        await service.stop(graceful=True)


async def http_ready():
    from tests.live_opencode.http_support import readiness
    return await readiness()


async def main(args):
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.selection import opencode_server_kwargs
    root = BACKEND / "tmp/opencode-http-live" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    root.mkdir(parents=True)
    emit("http_evidence_directory", path=str(root))
    load_models()
    write_json(root / "baseline.json", baseline())
    service = FullService(root)
    service.capture_original()
    ids, users = seed_workspace(root)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        tokens = []
        for user in users:
            response = await client.post("/api/auth/login", data={"username": user["email"], "password": user["password"]})
            response.raise_for_status()
            tokens.append(response.json()["access_token"])
    adapter = OpenCodeAdapter(**opencode_server_kwargs())
    stopped_original = False
    results = []
    try:
        await adapter.probe()
        model = args.model or (await adapter.model_catalog(project_path=str(root)))["default_model"]
        await service.stop_original()
        stopped_original = True
        for case in args.cases:
            results.append(await run_case(root / case, case, model, adapter, service, ids, tokens))
        write_json(root / "report.json", results)
        emit("http_complete", passed=len(results), report=str(root / "report.json"))
    finally:
        await adapter.close()
        if stopped_original:
            await service.restore()
        await cleanup_fixture(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--restart-http", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--cases", nargs="+", choices=HTTP_CASES, default=list(HTTP_CASES))
    args = parser.parse_args()
    if not (args.run_live and args.restart_http):
        parser.error("Real MySQL writes and HTTP service restarts require --run-live --restart-http")
    asyncio.run(main(args))
