"""Live OpenCode acceptance: real tools, severed SSE, and killed backend workers.

Run from backend: python -m tests.live_opencode.verify_recovery --run-live
Only this script's isolated sessions, worker processes, and SQLite files are used.
No production database writes, global threshold edits, or webhook deliveries.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
CASES = {
    "sse_disconnect": {"tool_seconds": 25, "hard_seconds": 180},
    "missing_terminal_sse": {"tool_seconds": 15, "hard_seconds": 180, "mute_sse": True},
    "restart_running": {"tool_seconds": 35, "hard_seconds": 180},
    "restart_finished": {"tool_seconds": 15, "hard_seconds": 75},
    "hard_timeout": {"tool_seconds": 90, "hard_seconds": 45},
}


def emit(kind, **values):
    print(json.dumps({"kind": kind, **values}, ensure_ascii=True), flush=True)


def read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # Last line may still be being appended by the other process.
    return rows


def read_job(root):
    path = root / "state.sqlite"
    if not path.exists():
        return None
    try:
        with sqlite3.connect(path, timeout=2) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM sdd_ai_jobs").fetchone()
            if not row:
                return None
            data = dict(row)
            data["checkpoint"] = (
                json.loads(data["provider_execution_json"]) if data["provider_execution_json"] else None
            )
            return data
    except sqlite3.OperationalError:
        return None


async def wait_for(check, *, seconds, label, process=None):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        if process and process.poll() is not None:
            raise AssertionError(f"Worker exited ({process.returncode}) before {label}; inspect worker console log")
        await asyncio.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {label}")


def start_worker(root, number):
    output = (root / f"console-{number}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.live_opencode.worker", str(root)],
        cwd=BACKEND,
        stdout=output,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    output.close()
    return process


def prepare(root, case, model):
    work = root / "work"
    work.mkdir(parents=True)
    marker = "LIVE_RECOVERY_" + uuid.uuid4().hex[:12].upper()
    spec = CASES[case]
    script = (
        "import json, os, time\nfrom pathlib import Path\n"
        "trace = Path(__file__).with_name('tool-trace.jsonl')\n"
        "def record(kind):\n"
        "    with trace.open('a', encoding='utf-8') as f:\n"
        "        f.write(json.dumps({'kind': kind, 'at': time.time(), 'pid': os.getpid()}) + '\\n')\n"
        "record('started')\n"
        f"time.sleep({spec['tool_seconds']})\n"
        "record('finished')\n"
        f"print('{marker}', flush=True)\n"
    )
    (work / "tool-probe.py").write_text(script, encoding="utf-8")
    command = f'python "{(work / "tool-probe.py").as_posix()}"'
    prompt = (
        "This is an authorized isolated infrastructure acceptance test. "
        "Use the shell tool to execute the following command exactly ONCE, in the foreground, "
        "with a timeout of at least 180000 milliseconds. The script deliberately sleeps silently; "
        "wait for it to finish. Do not repeat or detach the command, do not modify any files, "
        "and do not inspect the repository or environment. Then reply with only the marker printed by it.\n"
        f"Command: {command}\n"
    )
    config = {"case": case, "model": model, "marker": marker, "prompt": prompt, "idle_seconds": 6, **spec}
    for name in ("job_id", "task_id", "workspace_id", "user_id", "request_id"):
        config[name] = str(uuid.uuid4())
    (root / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


async def provider_state(adapter, sid):
    client = await adapter._ensure_client()
    active = await client.get(adapter.server_url + "/api/session/active")
    active.raise_for_status()
    messages = await adapter.list_messages(sid)
    return {"active": sid in active.json()["data"], "messages": messages}


async def run_case(root, case, model, adapter):
    from app.agents.adapters.opencode.execution import turn_messages

    config = prepare(root, case, model)
    process = start_worker(root, 1)
    processes = [process]
    evidence = {
        "case": case,
        "thresholds": {"idle_seconds": 6, "reconcile_seconds": 1, "hard_seconds": config["hard_seconds"]},
        "tool_seconds": config["tool_seconds"],
    }
    sid = None
    try:
        await wait_for(
            lambda: any(row["kind"] == "started" for row in read_jsonl(root / "work/tool-trace.jsonl")),
            seconds=150,
            label="real tool start",
            process=process,
        )
        original = await wait_for(
            lambda: row if (row := read_job(root)) and row["checkpoint"] else None,
            seconds=15,
            label="durable checkpoint",
            process=process,
        )
        checkpoint = original["checkpoint"]
        sid = checkpoint["session_id"]
        evidence.update(
            session_id=sid,
            job_id=config["job_id"],
            checkpoint=checkpoint,
            first_worker_pid=process.pid,
            original_run_token=original["run_token"],
            original_worker_boot_id=original["worker_boot_id"],
        )
        emit("tool_started", case=case, session_id=sid, pid=process.pid)
        if case == "sse_disconnect":
            for token in ("1", "2"):
                await asyncio.sleep(2)
                (root / "cut-sse").write_text(token, encoding="utf-8")
                await wait_for(
                    lambda *, token=token: any(
                        row.get("kind") == "sse_cut" and row.get("token") == token
                        for path in root.glob("worker-*.jsonl")
                        for row in read_jsonl(path)
                    ),
                    seconds=10,
                    label=f"SSE cut {token}",
                    process=process,
                )
                await asyncio.sleep(2)
            assert read_job(root)["status"] == "RUNNING"
            evidence["running_after_multiple_idle_windows"] = True
        if case in {"restart_running", "restart_finished"}:
            await asyncio.sleep(2)
            process.kill()
            await asyncio.to_thread(process.wait, 10)
            state = await provider_state(adapter, sid)
            assert state["active"], "Provider must still run after observer process is killed"
            assert read_job(root)["status"] == "RUNNING"
            evidence["remote_active_after_backend_kill"] = True
            if case == "restart_finished":
                limit = time.monotonic() + 150
                while time.monotonic() < limit:
                    state = await provider_state(adapter, sid)
                    turn = turn_messages(state["messages"], checkpoint["prompt_id"])
                    if turn and turn[-1].get("type") == "idle":
                        assert turn[-1]["outcome"] == "succeeded"
                        evidence["completed_while_backend_offline"] = True
                        break
                    await asyncio.sleep(0.5)
                assert evidence.get("completed_while_backend_offline")
                # Completion must win over an already expired original deadline on restart.
                while time.time() <= checkpoint["deadline"] + 0.3:
                    await asyncio.sleep(0.5)
                evidence["deadline_expired_before_restart"] = True
            else:
                await asyncio.sleep(3)
            process = start_worker(root, 2)
            processes.append(process)
            emit("backend_restarted", case=case, old_pid=processes[0].pid, new_pid=process.pid)
            state = await wait_for(
                lambda: row if (row := read_job(root)) and row["attempt_count"] >= 2 else None,
                seconds=30,
                label="new owner claim",
                process=process,
            )
            evidence.update(
                second_worker_pid=process.pid,
                recovered_checkpoint=state["checkpoint"],
                recovered_attempt_count=state["attempt_count"],
            )
            assert state["checkpoint"] == checkpoint, "Recovery must retain session, prompt and deadline"
            if state["status"] == "RUNNING":
                assert state["run_token"] != original["run_token"]
                assert state["worker_boot_id"] != original["worker_boot_id"]
                evidence["owner_changed"] = True
        await wait_for(
            lambda: process.poll() is not None, seconds=config["hard_seconds"] + 60, label="worker completion"
        )
        assert process.returncode == 0, f"Worker failed: {process.returncode}; inspect console log"
        results = sorted(root.glob("result-*.json"))
        assert results
        final = json.loads(results[-1].read_text(encoding="utf-8"))
        evidence["final_status"] = final["status"]
        traces = [row for path in root.glob("worker-*.jsonl") for row in read_jsonl(path)]
        posts = [
            row
            for row in traces
            if row.get("kind") == "http" and row.get("method") == "POST" and row["path"].endswith("/prompt")
        ]
        stops = [row for row in traces if row.get("kind") == "http" and row["path"].endswith("/interrupt")]
        tool_trace = read_jsonl(root / "work/tool-trace.jsonl")
        evidence.update(
            prompt_posts=len(posts),
            interrupt_requests=len(stops),
            sse_opens=sum(row["kind"] == "sse_open" for row in traces),
            sse_cuts=sum(row["kind"] == "sse_cut" for row in traces),
            dropped_sse_frames=sum(row["kind"] == "sse_drop" for row in traces),
            tool_trace=tool_trace,
        )
        assert len(posts) == 1 and posts[0]["prompt_id"] == checkpoint["prompt_id"]
        assert sum(row["kind"] == "started" for row in tool_trace) == 1
        state = await provider_state(adapter, sid)
        current_turn = turn_messages(state["messages"], checkpoint["prompt_id"])
        evidence["provider_outcome"] = current_turn[-1].get("outcome") if current_turn else None
        evidence["provider_user_messages"] = sum(row.get("type") == "user" for row in state["messages"])
        assert evidence["provider_user_messages"] == 1
        if case == "hard_timeout":
            assert final["status"] == "INTERRUPTED" and len(stops) == 1
            assert final["checkpoint"]["phase"] == "stopping"
            assert not state["active"]
        else:
            assert final["status"] == "SUCCESS" and not stops
            assert evidence["provider_outcome"] == "succeeded"
            assert sum(row["kind"] == "finished" for row in tool_trace) == 1
            replies = [
                row
                for row in final["messages"]
                if row["role"] == "assistant" and row["content"].strip() == config["marker"]
            ]
            assert len(replies) == 1, "Final reply must persist once through the real engine"
            evidence["final_reply_count"] = len(replies)
        if case == "sse_disconnect":
            assert evidence["sse_cuts"] == 2 and evidence["sse_opens"] >= 3
        if case == "missing_terminal_sse":
            assert evidence["dropped_sse_frames"] > 0
        evidence["passed"] = True
        emit("passed", **evidence)
        return evidence
    finally:
        for child in processes:
            if child.poll() is None:
                child.kill()
                await asyncio.to_thread(child.wait, 10)
        row = read_job(root)
        sid = sid or (row or {}).get("session_id")
        if sid:
            state = await provider_state(adapter, sid)
            if state["active"]:
                await adapter.cancel_persisted_session(sid)
            assert await adapter.delete_session(sid), "Failed to remove this test's session"
            evidence["session_deleted"] = True
        (root / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


async def main(args):
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.selection import opencode_server_kwargs

    adapter = OpenCodeAdapter(**opencode_server_kwargs())
    root = BACKEND / "tmp/opencode-live" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    root.mkdir(parents=True)
    emit("evidence_directory", path=str(root))
    results = []
    try:
        await adapter.probe()
        catalog = await adapter.model_catalog(project_path=str(root))
        model = args.model or catalog["default_model"]
        emit("model", value=model)
        for case in args.cases:
            results.append(await run_case(root / case, case, model, adapter))
        (root / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        emit("complete", passed=len(results), report=str(root / "report.json"))
    finally:
        await adapter.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Explicitly authorize real model/tool execution")
    parser.add_argument("--model", help="Uses the server's configured default when omitted")
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Real model execution requires --run-live")
    asyncio.run(main(args))
