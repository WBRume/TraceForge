"""Persistent raw-byte Git snapshots. Callers hold the task object-store lock.

Source indexes seed the first capture; subsequent captures reuse the private
index. Git failures never trigger a full-copy fallback. No source index, refs,
configuration, or working files are changed by capture.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

from loguru import logger

from app.core.subprocess_runner import run_git
from app.domains.task.services import task_snapshot_store as files

VERSION = 4
ATTRIBUTES = b"* -text -filter -ident -working-tree-encoding -eol\n"


def git(root: str, args: list[str], data: bytes | None = None) -> bytes:
    result = run_git(args, cwd=root, decode_text=False, input_data=data)
    if result.returncode:
        raise ValueError(f"Snapshot Git {args[0]} failed: {result.stderr.decode('utf-8', 'replace')[-500:]}")
    return result.stdout


def nul(paths) -> bytes:
    return b"".join(os.fsencode(p) + b"\0" for p in paths)


def scan(root: str, policy: dict) -> tuple[list[str], list[str], dict[str, os.stat_result]]:
    """One scandir pass; DirEntry supplies cached Windows stat information.

    Parents are inspected before recursion, so enumerated children need no
    repeated ancestry walks. Explicit tracked paths outside this walk still
    pass safe_path before access.
    """
    repos: list[str] = []
    directories: list[str] = []
    leaves: dict[str, os.stat_result] = {}

    def visit(directory: str, prefix: str = "") -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.lower() == ".git":
                    repos.append(directory)
                    continue
                relative = prefix + entry.name
                if files.excluded(relative, policy):
                    continue
                if ":" in entry.name or "\\" in entry.name:
                    raise ValueError(f"Unsupported snapshot path: {relative}")
                info = entry.stat(follow_symlinks=False)
                if (
                    getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                ) and not stat.S_ISLNK(info.st_mode):
                    raise ValueError(f"Protected junction is unsupported: {relative}")
                if stat.S_ISDIR(info.st_mode):
                    directories.append(relative)
                    visit(entry.path, relative + "/")
                elif stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    leaves[relative] = info
                else:
                    raise ValueError(f"Unsupported snapshot file: {relative}")

    visit(root)
    return repos, directories, leaves


class Shadow:
    def __init__(self, root: str, object_store: str, relative: str, source: str | None):
        self.root = root
        self.relative = relative
        self.cwd = os.path.join(root, relative) if relative != "." else root
        key = hashlib.sha256(relative.encode()).hexdigest()[:24]
        self.directory = os.path.join(object_store, "shadow", key)
        self.source = source
        self.cold = not os.path.exists(self.directory)

    def run(self, args: list[str], data: bytes | None = None) -> bytes:
        return git(
            self.cwd,
            [
                "--git-dir=" + self.directory,
                "--work-tree=" + self.cwd,
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.safecrlf=false",
                "-c",
                "core.attributesFile=",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=",
                *args,
            ],
            data,
        )

    def initialize(self) -> None:
        if not self.cold:
            # Missing/corrupt state is an error, not an invitation to initialize.
            with open(os.path.join(self.directory, "owner.json"), encoding="utf-8") as handle:
                owner = json.load(handle)
            if owner != {"root": self.root, "relative": self.relative}:
                raise ValueError("Snapshot index ownership differs")
            if not os.path.isfile(os.path.join(self.directory, "index")):
                raise ValueError("Snapshot index is missing")
            if os.path.exists(os.path.join(self.directory, "objects", "info", "alternates")):
                raise ValueError("Snapshot initialization did not finish")
            return
        fmt = git(self.source, ["rev-parse", "--show-object-format"]).decode().strip() if self.source else "sha1"
        self.run(["init", "--object-format=" + fmt, self.directory])
        for key, value in [
            ("core.bare", "false"),
            ("core.worktree", self.cwd),
            ("core.autocrlf", "false"),
            ("core.symlinks", "true"),
            ("core.longpaths", "true"),
            ("core.fsmonitor", "false"),
            ("index.version", "4"),
            ("index.threads", "true"),
            ("core.untrackedCache", "true"),
            ("gc.auto", "0"),
        ]:
            self.run(["config", key, value])
        Path(self.directory, "info", "attributes").write_bytes(ATTRIBUTES)
        if self.source:
            objects = (
                git(self.source, ["rev-parse", "--path-format=absolute", "--git-path", "objects"]).decode().strip()
            )
            Path(self.directory, "objects", "info", "alternates").write_bytes(
                (objects.replace("\\", "/") + "\n").encode("utf-8")
            )
            index = git(self.source, ["rev-parse", "--path-format=absolute", "--git-path", "index"]).decode().strip()
            if os.path.isfile(index):
                shutil.copyfile(index, os.path.join(self.directory, "index"))
                # Expand split indexes before detaching the source dependency.
                for shared in Path(index).parent.glob("sharedindex.*"):
                    shutil.copyfile(shared, Path(self.directory, shared.name))
                self.run(["update-index", "--no-split-index"])
        if not os.path.isfile(os.path.join(self.directory, "index")):
            self.run(["read-tree", "--empty"])
        files.write_json(os.path.join(self.directory, "owner.json"), {"root": self.root, "relative": self.relative})

    def _exclude_transformed_entries(self, protected, names, remove):
        # Reuse only entries whose source representation is raw bytes.
        attrs = git(
            self.source,
            ["check-attr", "-z", "--stdin", "text", "filter", "ident", "working-tree-encoding", "eol"],
            nul(protected),
        ).split(b"\0")
        conversion = set()
        for i in range(0, len(attrs) - 2, 3):
            if attrs[i + 2] not in (b"unspecified", b"unset"):
                if attrs[i + 1] in (b"text", b"eol"):
                    conversion.add(os.fsdecode(attrs[i]))
                else:
                    remove.add(os.fsdecode(attrs[i]))
        config = git(self.source, ["config", "--list", "--null"])
        if any(
            row.lower().startswith(b"core.autocrlf\n") and row.split(b"\n", 1)[1].lower() not in (b"false", b"0")
            for row in config.split(b"\0")
        ):
            conversion.update(names)
        if conversion:
            # Native Git inspects EOLs without creating new objects. LF or
            # binary bytes identical to the index need no conversion copy.
            equal_eol = set()
            for row in git(self.source, ["ls-files", "--eol", "-z"]).split(b"\0"):
                if not row:
                    continue
                fields, name = row.split(b"\t", 1)
                indexed_eol, work_eol = fields.split()[:2]
                if indexed_eol[2:] == work_eol[2:] and work_eol[2:] in (b"lf", b"none", b"-text"):
                    equal_eol.add(os.fsdecode(name))
            remove.update(conversion - equal_eol)

    def capture(self, protected: list[str], ref: str) -> dict:
        self.initialize()
        indexed = self.run(["ls-files", "--stage", "-z"])
        entries = [row.split(b"\t", 1) for row in indexed.split(b"\0") if row]
        if any(row[0].split()[2] != b"0" for row in entries):
            raise ValueError("Snapshot source index has unresolved conflicts")
        names = {os.fsdecode(row[1]) for row in entries}
        if names and self.cold:
            self.run(["update-index", "--no-assume-unchanged", "-z", "--stdin"], nul(sorted(names)))
            self.run(["update-index", "--no-skip-worktree", "-z", "--stdin"], nul(sorted(names)))
        remove = names - set(protected)
        if self.cold and self.source and protected:
            self._exclude_transformed_entries(protected, names, remove)

        if remove:
            self.run(["update-index", "--force-remove", "-z", "--stdin"], nul(sorted(remove)))
        dirty = {os.fsdecode(p) for p in self.run(["diff-files", "--name-only", "-z"]).split(b"\0") if p}
        changed = sorted(set(protected) & (dirty | (set(protected) - (names - remove))))
        if changed:
            self.import_blobs(changed)
        # Populate stat entries without creating one loose object per file.
        self.run(["update-index", "--refresh"])
        tree = self.run(["write-tree"]).decode().strip()
        if not protected:
            # Git can return its implicit empty-tree hash without storing it.
            tree = self.run(["hash-object", "-t", "tree", "-w", "--stdin"], b"").decode().strip()
        self.run(["update-ref", ref, tree])
        if self.cold and self.source:
            self.solidify(tree)
            os.remove(os.path.join(self.directory, "objects", "info", "alternates"))
            self.run(["fsck", "--connectivity-only", "--no-dangling", tree])
        return {"relative": self.relative, "git_dir": self.directory, "tree": tree, "ref": ref}

    def solidify(self, tree: str) -> None:
        """Share immutable Git objects on one volume; never link live files.

        Hardlinks own an independent directory entry, so deleting/pruning the
        source cannot invalidate a snapshot. Cross-volume stores deliberately
        use Git repack instead. A link error is fatal, never a copy fallback.
        """
        source = git(self.source, ["rev-parse", "--path-format=absolute", "--git-path", "objects"]).decode().strip()
        roots = [source]
        for line in git(self.source, ["count-objects", "-v"]).decode().splitlines():
            if line.startswith("alternate: "):
                roots.append(line[len("alternate: ") :])
        target = Path(self.directory, "objects")
        if any(os.stat(root).st_dev != target.stat().st_dev for root in roots):
            self.run(["repack", "-a", "-d", "--window=0"])
            return
        # A seeded cache-tree may reuse source tree objects as well as blobs.
        needed = set(self.run(["rev-list", "--objects", "--no-object-names", tree]).decode().splitlines())
        for root in roots:
            # Packed objects are immutable; only pack and index are necessary.
            for packed in Path(root, "pack").glob("pack-*"):
                if packed.suffix not in (".pack", ".idx"):
                    continue
                destination = target / "pack" / packed.name
                if not destination.exists():
                    os.link(packed, destination)
            for prefix in {oid[:2] for oid in needed}:
                shard = Path(root, prefix)
                if not shard.is_dir():
                    continue
                with os.scandir(shard) as objects:
                    for loose in objects:
                        if prefix + loose.name not in needed:
                            continue
                        destination = target / prefix / loose.name
                        if not destination.exists():
                            destination.parent.mkdir(exist_ok=True)
                            os.link(loose.path, destination)

    def import_blobs(self, changed: list[str]) -> None:
        """Feed raw contents to Git's pack writer, using bounded memory.

        fast-import writes a pack for the whole batch. Exported marks supply
        object IDs to update-index; user attributes/filters never run.
        """
        with tempfile.TemporaryDirectory(prefix=".import-", dir=self.directory) as temporary:
            stream_path = os.path.join(temporary, "blobs")
            marks_path = os.path.join(temporary, "marks")
            modes = []
            total_bytes = 0
            with open(stream_path, "wb") as stream:
                for number, relative in enumerate(changed, 1):
                    full = os.path.join(self.cwd, relative)
                    before = os.lstat(full)
                    if stat.S_ISLNK(before.st_mode):
                        data = os.fsencode(os.readlink(full))
                        size, mode = len(data), "120000"
                    elif stat.S_ISREG(before.st_mode):
                        data = None
                        size = before.st_size
                        mode = "100755" if os.name != "nt" and before.st_mode & 0o111 else "100644"
                    else:
                        raise ValueError(f"Unsupported snapshot file: {relative}")
                    modes.append(mode)
                    total_bytes += size
                    stream.write(f"blob\nmark :{number}\ndata {size}\n".encode())
                    if data is None:
                        with open(full, "rb") as source:
                            shutil.copyfileobj(source, stream, 1024 * 1024)
                    else:
                        stream.write(data)
                    after = os.lstat(full)
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino) != (
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                        after.st_ino,
                    ):
                        raise ValueError(f"File changed during snapshot: {relative}")
                    stream.write(b"\n")
                stream.write(b"done\n")
            with open(stream_path, "rb") as stream:
                result = run_git(
                    [
                        "--git-dir=" + self.directory,
                        "-c",
                        "core.fsync=committed",
                        "fast-import",
                        "--quiet",
                        "--done",
                        "--export-marks=" + marks_path,
                    ],
                    cwd=self.cwd,
                    decode_text=False,
                    stdin_file=stream,
                )
            if result.returncode:
                raise ValueError(f"Snapshot pack import failed: {result.stderr.decode('utf-8', 'replace')[-500:]}")
            marks = dict(line.split() for line in Path(marks_path).read_text().splitlines())
            index = b"".join(
                f"{mode} {marks[':' + str(number)]}\t".encode() + os.fsencode(relative) + b"\0"
                for number, (relative, mode) in enumerate(zip(changed, modes, strict=False), 1)
            )
            self.run(["update-index", "-z", "--index-info"], index)
            logger.info("Snapshot packed: changed_files={} bytes={}", len(changed), total_bytes)


def tree_entries(part: dict, root: str, paths: files.ReadPhasePaths | None = None) -> dict:
    paths = paths or files.ReadPhasePaths(root)
    out = git(root, ["--git-dir=" + part["git_dir"], "ls-tree", "-r", "-z", part["tree"]])
    result = {}
    for row in out.split(b"\0"):
        if not row:
            continue
        header, name = row.split(b"\t", 1)
        mode, kind, oid = header.split()
        if kind != b"blob":
            raise ValueError("Snapshot contains an unexpanded nested repository")
        relative = os.fsdecode(name)
        if part["relative"] != ".":
            relative = part["relative"] + "/" + relative
        paths(relative)
        result[relative] = {"oid": oid.decode(), "git_dir": part["git_dir"], "mode": mode.decode()}
    return result


def capture(
    root: str,
    repo_rels: list[str],
    checkpoint: str,
    object_store: str,
    policy: dict,
    extra_tracked: set[str] | None = None,
) -> dict:
    from app.domains.task.services import task_session_snapshot_service as service

    started = time.perf_counter()
    root = os.path.abspath(root)
    discovered, directories, leaves = scan(root, policy)
    repositories = service._candidate_repo_paths(root, [*repo_rels, *(os.path.relpath(p, root) for p in discovered)])
    if set(discovered) - set(repositories):
        raise ValueError("Invalid repository control entry")
    tracked = service._tracked_paths(root, repositories) | (extra_tracked or set())
    for rel in tracked - leaves.keys():
        full = files.safe_path(root, rel)
        if os.path.lexists(full):
            info = os.lstat(full)
            if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                leaves[rel] = info
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"Unsupported tracked file: {rel}")
    protected = sorted(leaves)
    scanned = time.perf_counter()
    logger.info("Snapshot scan complete: files={} scan_ms={:.1f}", len(protected), (scanned - started) * 1000)
    partition_sources = {os.path.relpath(repo, root).replace("\\", "/"): repo for repo in repositories}
    partition_sources.setdefault(".", None)
    groups: dict[str, list[str]] = {key: [] for key in partition_sources}
    ordered = sorted(partition_sources, key=len, reverse=True)
    modes = {}
    for rel in protected:
        group = next(p for p in ordered if p == "." or rel.startswith(p + "/"))
        groups[group].append(rel if group == "." else rel[len(group) + 1 :])
        modes[rel] = stat.S_IMODE(leaves[rel].st_mode)
    token = hashlib.sha256(os.path.abspath(checkpoint).encode()).hexdigest()
    parts = []
    for relative, source in partition_sources.items():
        parts.append(Shadow(root, object_store, relative, source).capture(groups[relative], "refs/traceforge/" + token))
    metadata_dir = os.path.join(checkpoint, "git")
    os.makedirs(metadata_dir, exist_ok=True)
    payload = {
        "version": VERSION,
        "task_root": root,
        "object_store": object_store,
        "policy": policy,
        "tracked": sorted(tracked),
        "partitions": parts,
        "directories": directories,
        "modes": modes,
        "directory_links": [
            rel
            for rel, info in leaves.items()
            if stat.S_ISLNK(info.st_mode)
            and getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0)
        ],
        "repositories": [service._git_state(root, repo, metadata_dir) for repo in repositories],
    }
    files.write_json(os.path.join(checkpoint, "worktree.json"), payload)
    logger.info(
        "Snapshot captured: files={} repositories={} scan_ms={:.1f} total_ms={:.1f}",
        len(protected),
        len(repositories),
        (scanned - started) * 1000,
        (time.perf_counter() - started) * 1000,
    )
    return payload


def entries(payload: dict) -> dict:
    result = {}
    paths = files.ReadPhasePaths(payload["task_root"])
    for part in payload["partitions"]:
        root = os.path.abspath(payload["object_store"])
        directory = os.path.abspath(part["git_dir"])
        if os.path.commonpath([root, directory]) != root:
            raise ValueError("Snapshot object path escapes store")
        values = tree_entries(part, payload["task_root"], paths)
        if result.keys() & values.keys():
            raise ValueError("Snapshot partitions overlap")
        result.update(values)
    return result


def validate(payload: dict) -> dict:
    result = entries(payload)
    for part in payload["partitions"]:
        git(payload["task_root"], ["--git-dir=" + part["git_dir"], "fsck", "--full", "--no-dangling", part["tree"]])
    return result


def _restore_and_validate_git_controls(checkpoint, root, saved):
    from app.domains.task.services import task_session_snapshot_service as service

    # A compensation checkpoint can own Git controls removed by an earlier restore.
    for original, parked in saved.get("quarantined_controls", {}).items():
        directory = root if original == "." else files.safe_path(root, original)
        target = os.path.join(directory, ".git")
        if not os.path.lexists(target):
            if os.path.commonpath([os.path.abspath(checkpoint), os.path.abspath(parked)]) != os.path.abspath(
                checkpoint
            ):
                raise ValueError("Invalid Git compensation path")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(parked, target)
    for repo in saved["repositories"]:
        actual = git(repo["repo_path"], ["rev-parse", "--absolute-git-dir"]).decode().strip()
        if os.path.normcase(actual) != os.path.normcase(repo["git_dir"]):
            raise ValueError("Repository identity changed")
        if repo.get("index_copy") and service._sha256_file(repo["index_copy"]) != repo["index_sha256"]:
            raise ValueError("Snapshot Git index is corrupt")


def _restore_worktree_files(root, current, saved, before, desired, changed):
    for rel in sorted(changed & before.keys(), key=lambda p: p.count("/"), reverse=True):
        os.remove(files.safe_path(root, rel))
    for rel in sorted(
        set(current["directories"]) - set(saved["directories"]), key=lambda p: p.count("/"), reverse=True
    ):
        directory = files.safe_path(root, rel)
        if os.path.isdir(directory) and not os.listdir(directory):
            os.rmdir(directory)
    for rel in sorted(set(saved["directories"]) - set(current["directories"]), key=lambda p: p.count("/")):
        os.makedirs(files.safe_path(root, rel), exist_ok=True)
    for rel in sorted(changed & desired.keys()):
        item = desired[rel]
        path = files.safe_path(root, rel)
        if os.path.isdir(path):
            os.rmdir(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = git(root, ["--git-dir=" + item["git_dir"], "cat-file", "blob", item["oid"]])
        if item["mode"] == "120000":
            os.symlink(os.fsdecode(data), path, target_is_directory=rel in saved.get("directory_links", []))
        else:
            fd, temporary = tempfile.mkstemp(prefix=".restore-", dir=os.path.dirname(path))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.chmod(temporary, saved["modes"][rel])
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)


def restore(checkpoint: str, root: str, backup: str) -> None:
    from app.domains.task.services import task_session_snapshot_service as service

    started = time.perf_counter()
    with open(os.path.join(checkpoint, "worktree.json"), encoding="utf-8") as handle:
        saved = json.load(handle)
    if saved["version"] != VERSION or os.path.normcase(saved["task_root"]) != os.path.normcase(os.path.abspath(root)):
        raise ValueError("Snapshot worktree identity differs")
    with files.store_lock(saved["object_store"]):
        desired = validate(saved)
        validated_at = time.perf_counter()
        logger.info(
            "Snapshot restore validated: root={} files={} elapsed_ms={:.1f}",
            root,
            len(desired),
            (validated_at - started) * 1000,
        )
        _restore_and_validate_git_controls(checkpoint, root, saved)

        current = capture(
            root,
            [r["repo_rel_path"] for r in saved["repositories"]],
            backup,
            saved["object_store"],
            saved["policy"],
            set(saved["tracked"]),
        )
        before = entries(current)
        backed_up_at = time.perf_counter()
        wanted_repos = {r["repo_rel_path"] for r in saved["repositories"]}
        current["quarantined_controls"] = {}
        for repo in current["repositories"]:
            rel = repo["repo_rel_path"]
            if rel not in wanted_repos:
                os.path.join(repo["repo_path"], ".git")
                parked = os.path.join(backup, "git-created", hashlib.sha256(rel.encode()).hexdigest())
                os.makedirs(os.path.dirname(parked), exist_ok=True)
                current["quarantined_controls"][rel] = parked
        files.write_json(os.path.join(backup, "worktree.json"), current)
        for rel, parked in current["quarantined_controls"].items():
            os.replace(os.path.join(root, rel, ".git"), parked)
        changed = {
            p
            for p in before.keys() | desired.keys()
            if (before.get(p, {}).get("oid"), before.get(p, {}).get("mode"), current["modes"].get(p))
            != (desired.get(p, {}).get("oid"), desired.get(p, {}).get("mode"), saved["modes"].get(p))
        }
        _restore_worktree_files(root, current, saved, before, desired, changed)

        service._restore_git_metadata(saved["repositories"])
        restored_at = time.perf_counter()
        # A new capture verifies both deletions and additions and refreshes the live index.
        verified = capture(
            root,
            [r["repo_rel_path"] for r in saved["repositories"]],
            os.path.join(backup, "verification"),
            saved["object_store"],
            saved["policy"],
            set(saved["tracked"]),
        )
        actual = entries(verified)
        if {p: (e["oid"], e["mode"]) for p, e in actual.items()} != {
            p: (e["oid"], e["mode"]) for p, e in desired.items()
        }:
            raise ValueError("Restored files differ from checkpoint")
        if verified["modes"] != saved["modes"] or not set(saved["directories"]).issubset(verified["directories"]):
            raise ValueError("Restored file modes or directories differ from checkpoint")
        logger.info(
            "Snapshot restored: root={} changed_files={} validate_ms={:.1f} backup_ms={:.1f} restore_ms={:.1f} verify_ms={:.1f} total_ms={:.1f}",
            root,
            len(changed),
            (validated_at - started) * 1000,
            (backed_up_at - validated_at) * 1000,
            (restored_at - backed_up_at) * 1000,
            (time.perf_counter() - restored_at) * 1000,
            (time.perf_counter() - started) * 1000,
        )


def collect(object_store: str) -> None:
    live: dict[str, set[str]] = {}
    for path in Path(object_store).glob("turn-*/**/worktree.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") == VERSION:
            for part in payload["partitions"]:
                live.setdefault(part["git_dir"], set()).add(part["ref"])
    for directory in Path(object_store, "shadow").glob("*"):
        refs = (
            git(
                object_store, ["--git-dir=" + str(directory), "for-each-ref", "--format=%(refname)", "refs/traceforge/"]
            )
            .decode()
            .splitlines()
        )
        for ref in set(refs) - live.get(str(directory), set()):
            git(object_store, ["--git-dir=" + str(directory), "update-ref", "-d", ref])
        # Git's index also roots the live state. Keep the index for the next turn.
        # Reclaim unreachable objects without searching the whole workspace for
        # new deltas on every undo. Existing compressed representations can be
        # reused; snapshot cleanup is not an archival compression job.
        git(object_store, ["--git-dir=" + str(directory), "-c", "pack.window=0", "gc", "--prune=now"])
