"""Update the shared rollback Git checkpoint and its public projection by path."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from app.domains.task.services import task_git_snapshot_store as git_store
from app.domains.task.services import task_snapshot_store as files

from . import content
from .change_journal import CachedCut


def _changed_groups(root: Path, previous: dict, changed: dict[str, set[int]]):
    policy = previous["policy"]
    modes = dict(previous["modes"])
    groups = {part["relative"]: {"existing": [], "removed": [], "paths": []} for part in previous["partitions"]}
    ordered = sorted(groups, key=len, reverse=True)
    directories = set(previous["directories"])
    pending, directories = _expand_directories(root, previous, changed)
    if pending is None or len(pending) >= 500:
        return None
    for name in sorted(pending):
        if files.excluded(name, policy) and name not in modes:
            continue
        full = files.safe_path(str(root), name)
        try:
            info = os.lstat(full)
        except (FileNotFoundError, NotADirectoryError):
            info = None
        if info and stat.S_ISDIR(info.st_mode) and name in modes:
            # The old file must leave the index when it becomes a directory;
            # the new descendants are separate entries in this same cut.
            info = None
        if info and not stat.S_ISREG(info.st_mode):
            return None
        if info is None and name not in modes:
            # Atomic-write scratch paths that disappeared were never in the cut.
            continue
        group = next(key for key in ordered if key == "." or name.startswith(key + "/"))
        relative = name if group == "." else name[len(group) + 1 :]
        groups[group]["paths"].append(relative)
        if info:
            groups[group]["existing"].append(relative)
            modes[name] = stat.S_IMODE(info.st_mode)
        else:
            groups[group]["removed"].append(relative)
            modes.pop(name, None)
    return groups, modes, directories


def _expand_directories(root: Path, previous: dict, changed: dict[str, set[int]]):
    """Visit only a moved/created directory; ordinary parent mtime events need no walk."""
    directories = set(previous["directories"])
    pending = set()
    for name, kinds in sorted(changed.items()):
        if files.excluded(name, previous["policy"]) and name not in previous["modes"]:
            continue
        full = files.safe_path(str(root), name)
        if os.path.isdir(full) and not os.path.islink(full) and not files.is_junction(full):
            if name in directories and kinds == {2}:
                continue
            discovered, nested, leaves = git_store.scan(full, previous["policy"])
            if discovered:
                return None, directories
            pending.update(old for old in previous["modes"] if old.startswith(name + "/"))
            if name in previous["modes"]:
                pending.add(name)
            pending.update(name + "/" + child for child in leaves)
            directories = {old for old in directories if not old.startswith(name + "/")}
            directories.add(name)
            directories.update(name + "/" + child for child in nested)
        elif name in directories:
            pending.update(old for old in previous["modes"] if old.startswith(name + "/"))
            directories = {old for old in directories if old != name and not old.startswith(name + "/")}
            if os.path.lexists(full):
                pending.add(name)
        else:
            pending.add(name)
    return pending, directories


def capture_changed(
    root: Path,
    checkpoint: Path,
    cached: CachedCut,
    changed: dict[str, set[int]] | None,
    store: content.ObjectStore,
    *,
    stable: bool,
):
    previous = cached.payload
    if previous is None or cached.repositories is None or changed is None or len(changed) >= 500:
        return None
    if any(part in {".git", ".gitignore"} for name in changed for part in name.split("/")):
        return None
    grouped = _changed_groups(root, previous, changed)
    if grouped is None:
        return None
    groups, modes, directories = grouped
    token = hashlib.sha256(os.path.abspath(checkpoint).encode()).hexdigest()
    parts, changed_entries = [], {}
    for part in previous["partitions"]:
        group = groups[part["relative"]]
        ref = "refs/traceforge/" + token
        source = str(root / part["relative"]) if part["relative"] != "." or (root / ".git").exists() else None
        group["tracked"] = (
            content._tracked_modes(Path(source), group["existing"]) if source and group["existing"] else {}
        )
        if group["paths"]:
            shadow = git_store.Shadow(str(root), previous["object_store"], part["relative"], source)
            current = shadow.capture_paths(
                part, group["existing"], group["removed"], ref, source_modes=group["tracked"], retain=False
            )
            changed_entries.update(git_store.tree_entries(current, str(root), selected=group["existing"]))
        else:
            current = {**part, "ref": ref}
        parts.append(current)
    payload = {**previous, "partitions": parts, "modes": modes, "directories": sorted(directories), "repositories": []}
    if stable:
        from app.domains.task.services import task_session_snapshot_service as snapshots

        metadata = checkpoint / "git"
        metadata.mkdir(parents=True, exist_ok=True)
        payload["repositories"] = [
            snapshots._git_state(str(root), str(root / part["relative"]), str(metadata))
            for part in parts
            if part["relative"] != "." or (root / ".git").exists()
        ]
    result, metrics = _project(root, cached.repositories, groups, changed_entries, store)
    files.write_json(str(checkpoint / "worktree.json"), payload)
    return payload, result, {**metrics, "paths_checked": sum(len(group["paths"]) for group in groups.values())}


def _project(root: Path, repositories: list[dict], groups: dict, changed_entries: dict, store: content.ObjectStore):
    projected, wanted = [], []
    for repo in repositories:
        group = groups[repo["rel_path"]]
        paths = group["paths"]
        if not paths:
            projected.append((repo, {}, []))
            continue
        repository_root = root / repo["rel_path"]
        tracked = group["tracked"]
        candidates = [name for name in group["existing"] if name not in tracked]
        untracked = (
            content.git(
                repository_root,
                ["--literal-pathspecs", "ls-files", "--others", "--exclude-standard", "-z", "--", *candidates],
            )
            if candidates
            else b""
        )
        allowed = set(tracked) | {os.fsdecode(name) for name in untracked.split(b"\0") if name}
        nested = [
            other["rel_path"][len(repo["rel_path"]) + 1 :]
            for other in repositories
            if other["rel_path"].startswith(repo["rel_path"] + "/")
        ]
        entries = {}
        for name in paths:
            if name not in allowed or content._excluded_export(name, tracked, nested):
                continue
            content.validate_path(name)
            item = changed_entries.get(repo["rel_path"] + "/" + name)
            if item is None:
                continue
            content.safe_path(repository_root, name)
            if item["mode"] == "120000" and name not in content.windows_link_placeholder_paths(
                repository_root, tracked
            ):
                raise ValueError("Unsupported collaboration link")
            entries[name] = item
            wanted.append(item)
        projected.append((repo, entries, paths))
    mapped, metrics = store.git_objects.export(wanted)
    result = []
    for repo, entries, paths in projected:
        current = {file["path"]: file for file in repo["files"]}
        for name in paths:
            current.pop(name, None)
        for name, item in entries.items():
            current[name] = {
                "path": name,
                "sha256": mapped[item["git_dir"], item["oid"]][0],
                "size": item["size"],
                "mode": item["mode"],
            }
        if len({name.casefold() for name in current}) != len(current):
            raise ValueError("Case-colliding collaboration path")
        result.append({**repo, "files": sorted(current.values(), key=lambda file: file["path"])})
    all_files = [file for repo in result for file in repo["files"]]
    if len(all_files) > 100000 or sum(file["size"] for file in all_files) > content.MAX_MANIFEST_BYTES:
        raise ValueError("Collaboration snapshot exceeds snapshot limits")
    return result, metrics
