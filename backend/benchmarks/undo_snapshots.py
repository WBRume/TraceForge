"""Measure first/hot worktree captures without running an Agent or restoring files.

Run from backend: python benchmarks/undo_snapshots.py <task-root>
Only temporary snapshots are written. Immutable source Git objects may gain a
hardlink; source working files, index, refs and configuration remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.task.services import task_git_snapshot_store as snapshots
from app.domains.task.services.task_session_snapshot_service import _snapshot_policy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_root")
    parser.add_argument("--turns", type=int, default=3)
    args = parser.parse_args()
    root = Path(args.task_root).resolve()
    Path(__file__).resolve().parents[1].joinpath("tmp").mkdir(exist_ok=True)
    store = Path(tempfile.mkdtemp(prefix="undo-benchmark-", dir=Path(__file__).resolve().parents[1] / "tmp"))
    policy = _snapshot_policy()
    repos, _, _ = snapshots.scan(str(root), policy)
    indexes = [
        Path(snapshots.git(repo, ["rev-parse", "--path-format=absolute", "--git-path", "index"]).decode().strip())
        for repo in repos
    ]

    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in indexes}

    before = hashes()
    results = []
    for index in range(args.turns):
        started = time.perf_counter()
        payload = snapshots.capture(str(root), [], str(store / f"turn-{index}"), str(store), policy)
        result = {
            "turn": index,
            "seconds": round(time.perf_counter() - started, 3),
            "files": len(payload["modes"]),
            "repositories": len(payload["repositories"]),
        }
        results.append(result)
        print(json.dumps(result), flush=True)
    if hashes() != before:
        raise ValueError("Source Git indexes changed during benchmark")
    report = {"task_root": str(root), "source_indexes_unchanged": True, "results": results}
    destination = store / "benchmark.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination, flush=True)


if __name__ == "__main__":
    main()
