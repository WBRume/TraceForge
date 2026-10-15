"""Raw-byte content store and deterministic, complete Git worktree inventories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath
from time import perf_counter
from uuid import uuid4

from loguru import logger

from app.config import settings
from app.core.subprocess_runner import GIT_REPOSITORY_ENV_VARS, run_git

MAX_OBJECT_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 512 * 1024 * 1024
HASH = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
PRIVATE = {".git", ".sdd", ".traceforge-collaboration"}
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _private_part(value: str) -> bool:
    lower = value.lower()
    return lower in PRIVATE or lower.startswith(".traceforge-sync")


def validate_path(value: str) -> str:
    parts = PurePosixPath(value).parts
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or any(
            p in {"", ".", ".."} or _private_part(p) or p.endswith((".", " ")) or RESERVED.match(p)
            for p in value.split("/")
        )
        or "/".join(parts) != value
    ):
        raise ValueError(f"Unsupported collaboration path: {value}")
    return value


def safe_path(root: Path, relative: str, *, resolved_root: Path | None = None, leaf_link: bool = False) -> Path:
    """Resolve parents only when the caller handles a leaf link without following it."""
    validate_path(relative)
    root = resolved_root if resolved_root is not None else root.resolve(strict=True)
    path = root.joinpath(*relative.split("/"))
    cursor = root
    parts = relative.split("/")
    for part in parts[:-1] if leaf_link else parts:
        cursor /= part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError(f"Linked collaboration path is unsupported: {relative}")
    if not (path.parent if leaf_link else path).resolve().is_relative_to(root):
        raise ValueError("Collaboration path escapes repository")
    return path


def _file_bytes(path: Path, *, link: bool) -> bytes | None:
    """Read the directory entry itself, including dangling links, never their target."""
    try:
        value = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISLNK(value.st_mode):
        if link and os.name != "nt":
            return os.fsencode(os.readlink(path))
        raise ValueError(f"Unexpected collaboration link: {path.name}")
    if link and os.name != "nt":
        raise ValueError(f"Git link type changed: {path.name}")
    return path.read_bytes() if stat.S_ISREG(value.st_mode) else None


def validate_export_type(root: Path, relative: str, mode: str, tracked: dict, placeholders: set) -> None:
    linked = mode == "120000" or tracked.get(relative) == "120000"
    path = safe_path(root, relative, leaf_link=linked and os.name != "nt")
    if not linked:
        return
    value = path.lstat()
    native = os.name != "nt" and stat.S_ISLNK(value.st_mode)
    placeholder = (
        relative in placeholders
        and stat.S_ISREG(value.st_mode)
        and not (getattr(value, "st_file_attributes", 0) & 0x400)
    )
    if mode != "120000" or tracked.get(relative) != "120000" or not (native or placeholder):
        raise ValueError(
            f"Unsupported Git link; tracked link or Windows core.symlinks=false placeholder required: {relative}"
        )


class ObjectStore:
    def __init__(self, task_id, *, root: str | None = None):
        from .git_objects import GitObjects

        metadata = {} if isinstance(task_id, str) else task_id.task_meta_json or {}
        task_id = task_id if isinstance(task_id, str) else task_id.id
        if not SAFE_ID.fullmatch(task_id):
            raise ValueError("Invalid task identity")
        self.task_id = task_id
        legacy = Path(settings.TASK_SESSION_SNAPSHOT_ROOT) / "collaboration" / task_id
        configured = Path(settings.COLLABORATION_SNAPSHOT_ROOT or legacy.parent) / task_id
        # Prefer existing data over a new configuration, then pin this decision
        # in _ensure_store. Never move or recreate an existing task's objects.
        self.root = (
            Path(metadata["collaboration_store_path"])
            if metadata.get("collaboration_store_path")
            else (legacy if legacy.exists() else configured)
        )
        if root is not None:
            self.root = Path(root)
        self.git_objects = GitObjects(self.root)
        self._verified_input: dict[str, bytes] = {}

    def path(self, sha256: str) -> Path:
        """Legacy read-only CAS location; all new bytes are written to Git."""
        if not HASH.fullmatch(sha256):
            raise ValueError("Invalid SHA256 object identity")
        return self.root / "objects" / sha256[:2] / sha256

    def bind(self, initial_checkpoint: str, task_root: str) -> None:
        configured = Path(settings.TASK_SESSION_SNAPSHOT_ROOT).resolve()
        if not Path(initial_checkpoint).resolve().is_relative_to(configured):
            raise ValueError("Initial checkpoint escapes configured snapshot root")
        self.git_objects.bind(initial_checkpoint, task_root)

    def put(self, raw: bytes, expected: str | None = None) -> str:
        if len(raw) > MAX_OBJECT_BYTES:
            raise ValueError("Collaboration file exceeds 64 MiB limit")
        sha256 = hashlib.sha256(raw).hexdigest()
        if expected is not None and sha256 != expected:
            raise ValueError("Object digest does not match raw bytes")
        self.git_objects.put(raw, sha256)
        return sha256

    def read(self, sha256: str) -> bytes:
        if sha256 in self._verified_input:
            return self._verified_input[sha256]
        legacy = self.path(sha256)
        if sha256 not in self.git_objects.known([sha256]):
            raw = legacy.read_bytes()
            self.put(raw, sha256)
            return raw
        return self.git_objects.read(sha256)

    def has_many(self, hashes: list[str]) -> set[str]:
        for value in hashes:
            self.path(value)
        known = self.git_objects.verify(hashes)
        return set(known) | {value for value in hashes if value not in known and self.path(value).is_file()}

    def has(self, sha256: str) -> bool:
        return sha256 in self.has_many([sha256])

    def validate_objects(self, entries: list[dict]) -> None:
        hashes = list({entry["sha256"] for entry in entries})
        known = self.git_objects.known(hashes)
        missing = [value for value in hashes if value not in known]
        if missing:
            # Existing durable inputs may predate the Git-backed store. Import
            # their legacy bytes as one pack rather than spawning Git per file.
            self.git_objects.import_bytes((value, self.path(value).read_bytes()) for value in missing)
            known = self.git_objects.known(hashes)
        for entry in entries:
            size = known[entry["sha256"]][2]
            if size != entry["size"]:
                raise ValueError("Input object length does not match manifest")
        # Reuse validated immutable bytes during this operation's installation.
        # Large inputs retain streaming reads; never retain a full 512 MiB cut.
        if sum(value[2] for value in known.values()) <= 8 * 1024 * 1024:
            self._verified_input = self.git_objects.read_many(known)
        else:
            self.git_objects.verify(hashes)

    def journal(self, operation_id: str, value: dict) -> None:
        from app.domains.task.services import task_snapshot_store

        key = hashlib.sha256(operation_id.encode()).hexdigest()
        task_snapshot_store.write_json(str(self.root / "operations" / (key + ".json")), value)

    def read_journal(self, operation_id: str) -> dict | None:
        key = hashlib.sha256(operation_id.encode()).hexdigest()
        path = self.root / "operations" / (key + ".json")
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def input_journals(self, submission_id: str) -> list[dict]:
        result = []
        for path in (self.root / "operations").glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("target", {}).get("submission_id") == submission_id:
                result.append(value)
        return result


def git(root: Path, arguments: list[str]) -> bytes:
    result = run_git(arguments, cwd=str(root), decode_text=False, timeout_seconds=30, unset_env=GIT_REPOSITORY_ENV_VARS)
    if result.returncode:
        raise ValueError("Unable to inventory collaboration Git worktree")
    return result.stdout


def _tracked_modes(root: Path, paths: list[str] | None = None) -> dict[str, str]:
    tracked: dict[str, str] = {}
    for item in git(
        root, ["--literal-pathspecs", "ls-files", "--stage", "-z", *(["--", *paths] if paths is not None else [])]
    ).split(b"\0"):
        if not item:
            continue
        header, name = item.split(b"\t", 1)
        mode, _sha, stage = header.decode().split()
        relative = name.decode("utf-8")
        if mode not in {"100644", "100755", "120000"} or stage != "0":
            raise ValueError(f"Unsupported submodule, link or unmerged file: {relative}")
        tracked[relative] = mode
    return tracked


def windows_link_placeholder_paths(root: Path, tracked: dict[str, str] | None = None) -> set[str]:
    """Allow existing Git links checked out as plain files, never live links."""
    if os.name != "nt":
        return set()
    tracked = tracked if tracked is not None else _tracked_modes(root)
    candidates = {path for path, mode in tracked.items() if mode == "120000"}
    if not candidates:
        return set()
    configured = run_git(
        ["config", "--bool", "--get", "core.symlinks"],
        cwd=str(root),
        decode_text=False,
        unset_env=GIT_REPOSITORY_ENV_VARS,
    )
    if configured.returncode or configured.stdout.strip() != b"false":
        return set()
    anchored = set()
    for item in git(root, ["ls-tree", "-r", "-z", "HEAD"]).split(b"\0"):
        if item:
            header, name = item.split(b"\t", 1)
            if header.split(b" ", 1)[0] == b"120000":
                anchored.add(name.decode("utf-8"))
    return candidates & anchored


def _excluded_export(relative: str, tracked: dict, nested: list[str]) -> bool:
    return (
        any(_private_part(part) for part in relative.split("/"))
        or any(relative == value or relative.startswith(value + "/") for value in nested)
        or (relative not in tracked and (Path(relative).name == ".env" or Path(relative).name.startswith(".env.")))
    )


def capture_task(task_root: Path, store: ObjectStore, repositories: list[dict], *, stable: bool) -> list[dict]:
    """Project the existing private Git checkpoint into the public wire scope."""
    from app.domains.task.services import task_git_snapshot_store as git_store
    from app.domains.task.services import task_session_snapshot_service as snapshots
    from app.domains.task.services import task_snapshot_store as files

    from . import change_journal, incremental_capture

    started = perf_counter()
    shared = store.git_objects.shared_root()
    checkpoint = shared / ("collaboration-" + str(uuid4()) if stable else "collaboration-preview-" + store.task_id)
    with files.store_lock(str(shared)):
        cached = change_journal.get(task_root, digest([str(shared), repositories, snapshots._snapshot_policy()]))
        changed = cached.journal.drain()
        try:
            incremental = incremental_capture.capture_changed(
                task_root, checkpoint, cached, changed, store, stable=stable
            )
        except Exception:
            cached.payload = None
            raise
        if incremental is not None:
            payload, result, metrics = incremental
            _retain_capture(store, checkpoint, payload, result, stable=stable)
            cached.payload, cached.repositories = payload, result
            logger.info(
                "Collaboration Git delta: task={} stable={} paths_checked={} hashed_blobs={} hashed_bytes={} total_ms={:.1f}",
                store.task_id,
                stable,
                metrics["paths_checked"],
                metrics["hashed_blobs"],
                metrics["hashed_bytes"],
                (perf_counter() - started) * 1000,
            )
            return result
        logger.info(
            "Collaboration full inventory fallback: task={} warm={} paths={}",
            store.task_id,
            cached.payload is not None,
            sorted(changed)[:20] if changed is not None else "watcher-unavailable",
        )
        cached.payload = None
        payload = git_store.capture(
            str(task_root),
            [repo["rel_path"] for repo in repositories],
            str(checkpoint),
            str(shared),
            snapshots._snapshot_policy(),
            capture_controls=stable,
        )
        # The Git tree is the immutable cut. Changed blobs are checked while
        # importing; stable publication does not require re-reading the worktree.
        entries = git_store.entries(payload)
        exported, public_entries = [], []
        total = 0
        for repo in repositories:
            root = safe_path(task_root, repo["rel_path"])
            tracked = _tracked_modes(root)
            placeholders = windows_link_placeholder_paths(root, tracked)
            allowed = set(tracked) | {
                item.decode("utf-8")
                for item in git(root, ["ls-files", "--others", "--exclude-standard", "-z"]).split(b"\0")
                if item
            }
            nested = [
                r["rel_path"][len(repo["rel_path"]) + 1 :]
                for r in repositories
                if r["rel_path"].startswith(repo["rel_path"] + "/")
            ]
            scoped = []
            folded = set()
            for relative in sorted(allowed):
                if _excluded_export(relative, tracked, nested):
                    continue
                validate_path(relative)
                if relative.casefold() in folded:
                    raise ValueError(f"Case-colliding collaboration path: {relative}")
                folded.add(relative.casefold())
                item = entries.get(repo["rel_path"] + "/" + relative)
                if item is None:
                    continue
                if item["mode"] == "120000" or tracked.get(relative) == "120000":
                    validate_export_type(root, relative, item["mode"], tracked, placeholders)
                if item["size"] > MAX_OBJECT_BYTES:
                    raise ValueError(f"Collaboration file exceeds 64 MiB: {relative}")
                total += item["size"]
                scoped.append((relative, item))
                public_entries.append(item)
            exported.append((repo, scoped))
        if total > MAX_MANIFEST_BYTES or len(public_entries) > 100000:
            raise ValueError("Collaboration snapshot exceeds snapshot limits")
        mapped, metrics = store.git_objects.export(public_entries)
        result = [
            {
                **repo,
                "files": [
                    {
                        "path": name,
                        "sha256": mapped[item["git_dir"], item["oid"]][0],
                        "size": item["size"],
                        "mode": item["mode"],
                    }
                    for name, item in scoped
                ],
            }
            for repo, scoped in exported
        ]
        _retain_capture(store, checkpoint, payload, result, stable=stable)
        cached.payload, cached.repositories = payload, result
        logger.info(
            "Collaboration Git capture: task={} stable={} hashed_blobs={} hashed_bytes={} total_ms={:.1f}",
            store.task_id,
            stable,
            metrics["hashed_blobs"],
            metrics["hashed_bytes"],
            (perf_counter() - started) * 1000,
        )
        return result


def _retain_capture(store: ObjectStore, checkpoint: Path, payload: dict, result: list[dict], *, stable: bool):
    from app.domains.task.services import task_git_snapshot_store as git_store
    from app.domains.task.services import task_snapshot_store as files

    content_key = digest(result)
    for part in payload["partitions"]:
        refs = [part["ref"], "refs/traceforge-collaboration/" + content_key]
        git_store.shadow_git(
            part["git_dir"],
            ["update-ref", "--stdin"],
            "".join(f"update {ref} {part['tree']}\n" for ref in refs).encode(),
        )
    if stable:
        files.write_json(
            str(store.root / "captures" / (content_key + ".json")), {"checkpoint": str(checkpoint), "worktree": payload}
        )


def _build_plan(task_root: Path, baseline: dict, target: dict, store: ObjectStore) -> list[dict]:
    old_repos = {r["task_repository_id"]: r for r in baseline["repositories"]}
    plan: list[dict] = []
    for repo in target["repositories"]:
        root = task_root / repo["rel_path"]
        old = {f["path"]: f for f in old_repos[repo["task_repository_id"]]["files"]}
        new = {f["path"]: f for f in repo["files"]}
        changed = [name for name in sorted(set(old) | set(new)) if old.get(name) != new.get(name)]
        placeholders = (
            windows_link_placeholder_paths(root)
            if any("120000" in {old.get(name, {}).get("mode"), new.get(name, {}).get("mode")} for name in changed)
            else set()
        )
        for relative in changed:
            if (
                relative in new
                and "120000" in {old.get(relative, {}).get("mode"), new[relative]["mode"]}
                and (
                    (os.name == "nt" and relative not in placeholders)
                    or old.get(relative, {}).get("mode") != new[relative]["mode"]
                )
            ):
                raise ValueError(f"Git link placeholder creation or type conversion is unsupported: {relative}")
            linked = old.get(relative, {}).get("mode") == "120000"
            path = safe_path(root, relative, leaf_link=linked and os.name != "nt")
            raw = _file_bytes(path, link=linked)
            actual = store.put(raw) if raw is not None else None
            expected = old.get(relative, {}).get("sha256")
            if actual != expected:
                raise ValueError(f"Server file changed outside authorized run: {relative}")
            if new.get(relative, {}).get("mode") == "120000":
                target_bytes = store.read(new[relative]["sha256"])
                if not target_bytes or b"\0" in target_bytes:
                    raise ValueError(f"Invalid Git link target: {relative}")
            if (
                os.name == "nt"
                and relative in new
                and new[relative]["mode"] != old.get(relative, {}).get("mode", "100644")
            ):
                raise ValueError(f"Executable mode changes are unsupported on this Windows server: {relative}")
            if relative in new and not path.is_symlink() and path.is_dir():
                for child in path.rglob("*"):
                    nested = child.relative_to(root).as_posix()
                    safe_path(root, nested)
                    if child.is_file() and (nested not in old or nested in new):
                        raise ValueError(f"Local server file blocks directory replacement: {nested}")
            plan.append(
                {
                    "repo": repo["rel_path"],
                    "path": relative,
                    "old": old.get(relative),
                    "new": new.get(relative),
                    "status": "PENDING",
                }
            )
    return plan


def _prune_empty_parents(path: Path, repository_root: Path) -> None:
    parent = path.parent
    while parent != repository_root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _install_item(task_root: Path, item: dict, store: ObjectStore, *, recover: bool) -> None:
    linked = (item["old"] or {}).get("mode") == "120000"
    path = safe_path(task_root / item["repo"], item["path"], leaf_link=linked and os.name != "nt")
    current = _file_bytes(path, link=linked)
    actual = hashlib.sha256(current).hexdigest() if current is not None else None
    if recover and actual == (item["new"] or {}).get("sha256"):
        if item["new"] is not None and os.name != "nt" and not linked:
            os.chmod(path, 0o755 if item["new"]["mode"] == "100755" else 0o644)
        return
    if actual != (item["old"] or {}).get("sha256"):
        raise ValueError(f"Server file changed during input install: {item['path']}")
    if item["new"] is None:
        path.unlink()
        _prune_empty_parents(path, (task_root / item["repo"]).resolve())
        return
    raw = store.read(item["new"]["sha256"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if item["new"]["mode"] == "120000" and os.name != "nt":
            # Replace the link entry atomically. chmod/read_bytes would follow it.
            os.unlink(temporary)
            os.symlink(os.fsdecode(raw), temporary)
        else:
            os.chmod(temporary, 0o755 if item["new"]["mode"] == "100755" else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def apply_manifest(
    task_root: Path, baseline: dict, target: dict, store: ObjectStore, operation_id: str, *, recover: bool = False
) -> None:
    """Install pinned input while the caller excludes server execution writers.

    The durable plan retains old bytes before writes and is resumed unchanged.
    Delete children before replacing directories; never remove extra local files.
    """
    existing = store.read_journal(operation_id)
    if existing and existing.get("status") != "COMPLETED" and not recover:
        raise ValueError("Incomplete collaboration input requires recovery")
    if existing:
        if existing["target_digest"] != digest(target["repositories"]):
            raise ValueError("Operation was reused with different input")
        if existing["status"] == "COMPLETED":
            return
    journal = existing or {
        "status": "APPLYING",
        "operation_id": operation_id,
        "target_digest": digest(target["repositories"]),
        "target": target,
        "files": _build_plan(task_root, baseline, target, store),
    }
    plan = sorted(
        journal["files"],
        key=lambda item: (
            0 if item["new"] is None else 1,
            -item["path"].count("/") if item["new"] is None else item["path"].count("/"),
            item["repo"],
            item["path"],
        ),
    )
    store.journal(operation_id, journal)
    for item in plan:
        _install_item(task_root, item, store, recover=recover)
        item["status"] = "APPLIED"
        # Recovery compares actual old/new bytes for every file; per-file status
        # is advisory and does not require rewriting the complete durable plan.
    journal["status"] = "COMPLETED"
    store.journal(operation_id, journal)
