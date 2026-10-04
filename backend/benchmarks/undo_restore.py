"""Measure restore on an isolated copy of protected workspace files.

Run from backend: python benchmarks/undo_restore.py <source-worktree>
Never restores into the source. The copied workspace intentionally has no .git;
real source tree parsing/object validation is a separate read-only measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.task.services import task_git_snapshot_store as snapshots
from app.domains.task.services.task_session_snapshot_service import _cleanup_checkpoint_sync, _snapshot_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    temporary = Path(__file__).resolve().parents[1] / "tmp"
    temporary.mkdir(exist_ok=True)
    store = Path(tempfile.mkdtemp(prefix="undo-restore-benchmark-", dir=temporary))
    root = store / "worktree"
    root.mkdir()
    policy = _snapshot_policy()
    _, directories, leaves = snapshots.scan(str(source), policy)
    for relative in directories:
        (root / relative).mkdir(parents=True, exist_ok=True)
    for relative, info in leaves.items():
        original, copied = source / relative, root / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        if stat.S_ISLNK(info.st_mode):
            os.symlink(os.readlink(original), copied, target_is_directory=original.is_dir())
        else:
            shutil.copy2(original, copied)
    checkpoint = store / "turn-target"
    snapshots.capture(str(root), [], str(checkpoint), str(store), policy)
    changed = next(root / rel for rel, info in leaves.items() if stat.S_ISREG(info.st_mode))
    expected = hashlib.sha256(changed.read_bytes()).hexdigest()
    with changed.open("ab") as handle:
        handle.write(b"\nundo benchmark change\n")
    new_file = root / ("undo-probe-" + store.name)
    new_file.write_bytes(b"new file after checkpoint")
    started = time.perf_counter()
    snapshots.restore(str(checkpoint), str(root), str(checkpoint / "current-worktree"))
    restore_seconds = time.perf_counter() - started
    assert hashlib.sha256(changed.read_bytes()).hexdigest() == expected
    assert not new_file.exists()
    started = time.perf_counter()
    _cleanup_checkpoint_sync(str(checkpoint))
    cleanup_seconds = time.perf_counter() - started
    report = {
        "source": str(source),
        "isolated_worktree": str(root),
        "files": len(leaves),
        "changed_files": 2,
        "restore_seconds": round(restore_seconds, 3),
        "cleanup_seconds": round(cleanup_seconds, 3),
        "verified": True,
    }
    (store / "benchmark.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(store / "benchmark.json")


if __name__ == "__main__":
    main()
