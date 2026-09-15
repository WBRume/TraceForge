"""Task-local immutable byte objects and scoped filesystem manifests.

Callers hold ``store_lock`` through capture/publication, restoration or GC.
Objects are never linked into a live worktree (in-place writes must not mutate
history). Every capture reads protected bytes; stat timestamps are not trusted
as a content cache.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time


DEFAULT_EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".class")


def is_junction(path: str) -> bool:
    if os.name != "nt" or not os.path.lexists(path):
        return False
    info = os.lstat(path)
    return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) and not stat.S_ISLNK(info.st_mode)


@contextmanager
def store_lock(root: str):
    """OS lock shared by processes; released automatically on process exit."""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, ".store.lock"), "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 180
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Task snapshot store is busy")
                    time.sleep(0.05)
        else:
            import fcntl
            deadline = time.monotonic() + 180
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Task snapshot store is busy")
                    time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def safe_path(root: str, relative: str) -> str:
    if not relative or "\\" in relative or ":" in relative or any(p.lower() in {"", ".", "..", ".git"} for p in relative.split("/")):
        raise ValueError(f"Invalid snapshot path: {relative!r}")
    target = os.path.abspath(os.path.join(root, relative))
    if os.path.commonpath([os.path.abspath(root), target]) != os.path.abspath(root):
        raise ValueError("Snapshot path escapes root")
    # Do not traverse a link/junction in a parent directory.
    parent = os.path.dirname(target)
    while parent != os.path.abspath(root):
        if os.path.islink(parent) or is_junction(parent):
            raise ValueError("Snapshot path traverses a link")
        parent = os.path.dirname(parent)
    return target


def excluded(relative: str, policy: dict) -> bool:
    parts = relative.split("/")
    return any(p in policy["excluded_dirs"] for p in parts) or parts[-1].endswith(tuple(policy["excluded_suffixes"]))


def paths(root: str, policy: dict, tracked: set[str]) -> list[str]:
    """Prune generated directories before traversal; tracked files override."""
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Task worktree does not exist: {root}")

    def fail_scan(error: OSError) -> None:
        raise error

    result = set()
    for current, dirs, files in os.walk(root, followlinks=False, onerror=fail_scan):
        rel = os.path.relpath(current, root).replace("\\", "/")
        prefix = "" if rel == "." else rel + "/"
        keep = []
        for name in dirs:
            path = prefix + name
            if name.lower() == ".git" or excluded(path, policy):
                continue
            full = os.path.join(current, name)
            if is_junction(full):
                raise ValueError(f"Protected junction is unsupported: {path}")
            if os.path.islink(full):
                result.add(path)
            else:
                keep.append(name)
        dirs[:] = keep
        for name in files:
            path = prefix + name
            if name.lower() != ".git" and not excluded(path, policy):
                result.add(path)
    for path in tracked:
        full = safe_path(root, path)
        if os.path.lexists(full) and not (os.path.isdir(full) and not os.path.islink(full)):
            result.add(path)
    return sorted(result)


def object_path(store: str, digest: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid snapshot object id")
    return os.path.join(store, "objects", digest[:2], digest[2:])


def capture_file(path: str, store: str | None) -> dict:
    info = os.lstat(path)
    if is_junction(path):
        raise ValueError(f"Protected junction is unsupported: {path}")
    if stat.S_ISLNK(info.st_mode):
        return {"kind": "symlink", "target": os.readlink(path), "directory": os.path.isdir(path)}
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Unsupported snapshot file: {path}")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    key = digest.hexdigest()
    if store:
        target = object_path(store, key)
        if not os.path.exists(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".object-", dir=os.path.dirname(target))
            try:
                copied_hash = hashlib.sha256()
                with os.fdopen(fd, "wb") as output, open(path, "rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        copied_hash.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if copied_hash.hexdigest() != key:
                    raise ValueError(f"File changed during snapshot: {path}")
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)
    after = os.lstat(path)
    if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError(f"File changed during snapshot: {path}")
    return {"kind": "file", "sha256": key, "size": info.st_size, "mode": stat.S_IMODE(info.st_mode)}


def capture(root: str, policy: dict, tracked: set[str], store: str | None) -> dict:
    return {rel: capture_file(safe_path(root, rel), store) for rel in paths(root, policy, tracked)}


def validate_objects(store: str, manifest: dict) -> None:
    checked = set()
    for entry in manifest.values():
        if entry["kind"] == "file" and entry["sha256"] not in checked:
            digest = entry["sha256"]
            actual = capture_file(object_path(store, digest), None)
            if actual["sha256"] != digest or actual["size"] != entry["size"]:
                raise ValueError("Snapshot object is corrupt")
            checked.add(digest)


def restore(root: str, store: str, before: dict, desired: dict) -> None:
    # Remove only protected leaves. Never recursively delete an excluded tree.
    changed = {p for p in before.keys() | desired.keys() if before.get(p) != desired.get(p)}
    for rel in sorted(changed, key=lambda p: (p.count("/"), p), reverse=True):
        path = safe_path(root, rel)
        if rel in before and os.path.lexists(path):
            os.remove(path)
            parent = os.path.dirname(path)
            while parent != root:
                try:
                    os.rmdir(parent)  # only empty directories; .git/caches survive
                except OSError:
                    break
                parent = os.path.dirname(parent)
    for rel in sorted(changed & desired.keys()):
        path = safe_path(root, rel)
        entry = desired[rel]
        if os.path.isdir(path):
            os.rmdir(path)  # fail safely if excluded data blocks a type change
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if entry["kind"] == "symlink":
            os.symlink(entry["target"], path, target_is_directory=entry["directory"])
        else:
            fd, temporary = tempfile.mkstemp(prefix=".restore-", dir=os.path.dirname(path))
            os.close(fd)
            try:
                shutil.copyfile(object_path(store, entry["sha256"]), temporary)
                os.chmod(temporary, entry["mode"])
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)


def collect(store: str) -> None:
    """Mark/sweep includes compensation manifests. Malformed manifests abort GC."""
    live = set()
    for manifest_path in Path(store).glob("turn-*/**/worktree.json"):
        with manifest_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("version") != 2:
            raise ValueError("Unsupported snapshot manifest")
        live.update(e["sha256"] for e in payload["manifest"].values() if e["kind"] == "file")
    objects = Path(store) / "objects"
    if objects.exists():
        for shard in objects.iterdir():
            if not shard.is_dir() or shard.is_symlink():
                continue
            for obj in shard.iterdir():
                if shard.name + obj.name not in live:
                    obj.unlink()
            if not any(shard.iterdir()):
                shard.rmdir()
