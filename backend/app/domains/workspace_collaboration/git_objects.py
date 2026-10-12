"""Protocol SHA256 identities backed by the task's immutable Git objects."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from app.domains.task.services import task_git_snapshot_store as git_store
from app.domains.task.services import task_snapshot_store as files


class GitObjects:
    def __init__(self, metadata_root: Path):
        self.root = metadata_root
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "git-objects.sqlite3"
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS objects (git_dir TEXT, oid TEXT, sha256 TEXT, size INTEGER, "
                "PRIMARY KEY (git_dir, oid))"
            )
            db.execute("CREATE INDEX IF NOT EXISTS by_sha256 ON objects(sha256)")
            db.execute("CREATE INDEX IF NOT EXISTS by_oid ON objects(oid)")

    def connect(self):
        return sqlite3.connect(self.database, timeout=30)

    def shared_root(self) -> Path:
        binding = self.root / "git-store.json"
        return Path(json.loads(binding.read_text(encoding="utf-8"))["object_store"]) if binding.exists() else self.root

    def bind(self, initial_checkpoint: str, task_root: str) -> None:
        checkpoint = Path(initial_checkpoint).resolve(strict=True)
        payload = json.loads((checkpoint / "worktree.json").read_text(encoding="utf-8"))
        shared = checkpoint.parent
        if (
            payload.get("version") != git_store.VERSION
            or Path(payload["task_root"]).resolve() != Path(task_root).resolve()
        ):
            raise ValueError("Initial snapshot identity differs")
        if Path(payload["object_store"]).resolve() != shared:
            raise ValueError("Initial snapshot store differs")
        for part in payload["partitions"]:
            directory = Path(part["git_dir"]).resolve(strict=True)
            if not directory.is_relative_to(shared) or not (directory / "index").is_file():
                raise ValueError("Initial snapshot index is unavailable")
            owner = json.loads((directory / "owner.json").read_text(encoding="utf-8"))
            if Path(owner["root"]).resolve() != Path(task_root).resolve() or owner["relative"] != part["relative"]:
                raise ValueError("Initial snapshot index ownership differs")
        target = self.root / "git-store.json"
        value = {"object_store": str(shared), "task_root": str(Path(task_root).resolve())}
        if target.exists() and json.loads(target.read_text(encoding="utf-8")) != value:
            raise ValueError("Collaboration Git store ownership changed")
        files.write_json(str(target), value)

    def known(self, hashes: list[str]) -> dict[str, tuple[str, str, int]]:
        result = {}
        with self.connect() as db:
            for offset in range(0, len(hashes), 400):
                batch = hashes[offset : offset + 400]
                if not batch:
                    continue
                sql = (
                    "SELECT sha256,git_dir,oid,size FROM objects WHERE sha256 IN (" + ",".join("?" for _ in batch) + ")"
                )
                for sha, directory, oid, size in db.execute(sql, batch):
                    result[sha] = (directory, oid, size)
        return result

    def register(self, entries: list[tuple[str, str, str, int]]) -> None:
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO objects(git_dir,oid,sha256,size) VALUES(?,?,?,?)", entries)

    def export(self, entries: list[dict]) -> tuple[dict[tuple[str, str], tuple[str, int]], dict]:
        """Batch-read only previously unseen immutable Git blobs."""
        wanted = {(item["git_dir"], item["oid"]): item for item in entries}
        mapped, known_oids = {}, {}
        with self.connect() as db:
            oids = list({oid for _, oid in wanted})
            for offset in range(0, len(oids), 400):
                batch = oids[offset : offset + 400]
                sql = "SELECT oid,sha256,size FROM objects WHERE oid IN (" + ",".join("?" for _ in batch) + ")"
                for oid, sha, size in db.execute(sql, batch):
                    known_oids[oid] = (sha, size)
        reused = []
        for (directory, oid), item in wanted.items():
            if oid in known_oids:
                sha, size = known_oids[oid]
                if size != item["size"]:
                    raise ValueError("Git object mapping size differs")
                mapped[directory, oid] = (sha, size)
                reused.append((directory, oid, sha, size))
        pending = [item for key, item in wanted.items() if key not in mapped]
        new_rows = []
        bytes_read = 0
        for directory in {item["git_dir"] for item in pending}:
            group = [item for item in pending if item["git_dir"] == directory]
            for oid, raw in git_store.read_blobs(directory, [(item["oid"], item["size"]) for item in group]):
                if raw.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                    raise ValueError("Unmaterialized Git LFS object")
                sha = hashlib.sha256(raw).hexdigest()
                mapped[directory, oid] = (sha, len(raw))
                new_rows.append((directory, oid, sha, len(raw)))
                bytes_read += len(raw)
        self.register([*reused, *new_rows])
        return mapped, {"hashed_blobs": len(new_rows), "hashed_bytes": bytes_read}

    def put(self, raw: bytes, sha256: str) -> None:
        if sha256 in self.known([sha256]):
            return
        self.import_bytes([(sha256, raw)])

    def import_bytes(self, values) -> None:
        """Pack incoming or legacy bytes in one Git operation with bounded memory."""
        shared = self.shared_root()
        with files.store_lock(str(shared)):
            directory = shared / "collaboration-transfer.git"
            if not directory.exists():
                directory.mkdir()
                git_store.git(str(directory), ["init", "--bare", "."])
            with tempfile.TemporaryDirectory(prefix="incoming-", dir=directory) as temporary:
                stream_path, marks_path = Path(temporary, "stream"), Path(temporary, "marks")
                rows = []
                with stream_path.open("wb") as stream:
                    for number, (sha256, raw) in enumerate(values, 1):
                        if len(raw) > 64 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != sha256:
                            raise ValueError("Object digest or size does not match raw bytes")
                        stream.write(f"blob\nmark :{number}\ndata {len(raw)}\n".encode())
                        stream.write(raw)
                        stream.write(b"\n")
                        rows.append((sha256, len(raw)))
                    stream.write(b"done\n")
                if not rows:
                    return
                with stream_path.open("rb") as stream:
                    git_store.shadow_git(
                        str(directory),
                        [
                            "-c",
                            "core.fsync=committed",
                            "fast-import",
                            "--quiet",
                            "--done",
                            "--export-marks=" + os.path.relpath(marks_path, directory),
                        ],
                        stdin_file=stream,
                    )
                marks = dict(line.split() for line in marks_path.read_text().splitlines())
                imported = [
                    (str(directory), marks[":" + str(number)], sha, size) for number, (sha, size) in enumerate(rows, 1)
                ]
                git_store.shadow_git(
                    str(directory),
                    ["update-ref", "--stdin"],
                    "".join(f"update refs/traceforge-transfer/{sha} {oid}\n" for _, oid, sha, _ in imported).encode(),
                )
                self.register(imported)

    def read(self, sha256: str) -> bytes:
        item = self.known([sha256]).get(sha256)
        if item is None:
            raise FileNotFoundError(sha256)
        directory, oid, size = item
        raw = next(git_store.read_blobs(directory, [(oid, size)]))[1]
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("Collaboration object checksum failed")
        return raw

    def read_many(self, known: dict[str, tuple[str, str, int]]) -> dict[str, bytes]:
        """One verified read per object directory for a bounded input batch."""
        result = {}
        groups: dict[str, dict[str, tuple[str, int]]] = {}
        for sha, (directory, oid, size) in known.items():
            groups.setdefault(directory, {})[oid] = (sha, size)
        for directory, entries in groups.items():
            for oid, raw in git_store.read_blobs(directory, [(oid, value[1]) for oid, value in entries.items()]):
                sha = entries[oid][0]
                if hashlib.sha256(raw).hexdigest() != sha:
                    raise ValueError("Collaboration object checksum failed")
                result[sha] = raw
        return result

    def verify(self, hashes: list[str]) -> dict[str, tuple[str, str, int]]:
        known = self.known(hashes)
        groups = {}
        for sha, (directory, oid, size) in known.items():
            groups.setdefault(directory, {})[oid] = (sha, size)
        for directory, objects in groups.items():
            rows = git_store.shadow_git(
                directory,
                ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                "".join(oid + "\n" for oid in objects).encode(),
            ).splitlines()
            if len(rows) != len(objects):
                raise ValueError("Git object inventory is incomplete")
            for row in rows:
                values = row.decode().split()
                if len(values) != 3 or values[1] != "blob" or values[0] not in objects:
                    raise ValueError("Collaboration Git object is unavailable")
                if int(values[2]) != objects[values[0]][1]:
                    raise ValueError("Collaboration Git object size differs")
        return known
