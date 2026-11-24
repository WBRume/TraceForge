"""Read and reuse repository data for the dashboard's activity windows."""

from __future__ import annotations

import os
import posixpath
import re
import stat
import time
import zlib
from collections import OrderedDict, defaultdict
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock

from pydantic import TypeAdapter, ValidationError
from redis.exceptions import RedisError

from app.config import settings
from app.core.logging import get_logger
from app.core.redis_client import get_sync_redis_cache_client
from app.core.subprocess_runner import GIT_REPOSITORY_ENV_VARS, ProcessTimeoutError, run_git

logger = get_logger(__name__)

_SOURCE_EXTS = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++",
    ".css": "CSS",
    ".scss": "CSS",
    ".less": "CSS",
    ".html": "HTML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".yml": "Config",
    ".yaml": "Config",
    ".toml": "Config",
    ".json": "JSON",
}
_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "venv",
        ".venv",
        "__pycache__",
        "dist",
        "dist-electron",
        "dist-desktop-host",
        "build",
        "target",
        "release",
        ".vite",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        "backups",
        "uploads",
        "tmp",
        "output",
        "vendor",
    }
)
_CONTAINER_DIRS = frozenset(
    {"src", "app", "lib", "pkg", "internal", "packages", "apps", "services", "modules", "domains", "components"}
)
_MAX_FILES_PER_REPO = 4000
_MAX_FILE_BYTES = 1_500_000
_MAX_COMMITS_PER_REPO = 180
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_REPOS = 32
_REDIS_TTL_SECONDS = 30 * 24 * 60 * 60
_REDIS_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_cache_lock = Lock()
_scan_locks = tuple(Lock() for _ in range(32))
_cache_generation = 0
_scan_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dashboard-repo")


@dataclass(frozen=True, slots=True)
class ScannedFile:
    path: str
    name: str
    module: str
    loc: int
    lang: str
    stamp: tuple[int, int, int]


@dataclass(slots=True)
class ParsedCommit:
    hash: str
    timestamp: int
    date: str
    subject: str
    files: list[tuple[str, int, int]]


@dataclass(frozen=True, slots=True)
class GitRevision:
    head: str
    shallow: str = ""


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    revision: GitRevision | None
    files: list[ScannedFile]
    is_git: bool
    commits: list[ParsedCommit] | None
    since: int
    scanned_at: float
    expires_at: float
    persisted: bool = False


@dataclass(frozen=True, slots=True)
class _CachedRepositoryData:
    files: list[ScannedFile]
    commits: list[ParsedCommit]
    since: int


_snapshot_codec = TypeAdapter(_CachedRepositoryData)
_cache: OrderedDict[tuple[str, Path], RepositorySnapshot] = OrderedDict()


def invalidate_diorama_cache(workspace_id: str | None = None) -> None:
    global _cache_generation
    with _cache_lock:
        _cache_generation += 1
        if workspace_id is None:
            _cache.clear()
        else:
            for key in [key for key in _cache if key[0] == workspace_id]:
                del _cache[key]


def _fresh_snapshot(
    key: tuple[str, Path], *, revision: GitRevision | None, now: float, refresh_started_at: float | None
) -> RepositorySnapshot | None:
    """Look up a worktree snapshot while holding the cache lock."""
    cached = _cache.get(key)
    if (
        cached
        and cached.revision == revision
        and cached.expires_at > now
        and (revision is None or cached.is_git)
        and (refresh_started_at is None or cached.scanned_at >= refresh_started_at)
    ):
        _cache.move_to_end(key)
        return cached
    return None


def _read_git_revision(repo_dir: Path) -> GitRevision | None:
    try:
        result = run_git(
            ["rev-parse", "--path-format=absolute", "--git-path", "shallow", "--verify", "HEAD^{commit}"],
            cwd=str(repo_dir),
            timeout_seconds=2,
            unset_env=GIT_REPOSITORY_ENV_VARS,
        )
        lines = result.stdout.splitlines()
        if result.returncode or len(lines) != 2 or not _OBJECT_ID.fullmatch(lines[1]):
            return None
        shallow_file, revision = lines
        try:
            shallow = sha256(Path(shallow_file).read_bytes()).hexdigest()
        except FileNotFoundError:
            shallow = ""
        return GitRevision(revision, shallow)
    except (OSError, ProcessTimeoutError):
        return None


def _redis_key(workspace_id: str, repo_dir: Path, revision: GitRevision) -> str:
    prefix = str(settings.DISTRIBUTED_LOCK_KEY_PREFIX or "sdd-native").strip() or "sdd-native"
    scope = os.path.normcase(os.path.abspath(repo_dir))
    repo_key = sha256(f"{scope}\0{revision.shallow}".encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"{prefix}:dashboard:diorama:v1:{workspace_id}:{repo_key}:{revision.head}"


def _load_redis_snapshot(key: str) -> _CachedRepositoryData | None:
    try:
        value = get_sync_redis_cache_client().getex(key, ex=_REDIS_TTL_SECONDS)
        if not value:
            return None
        decoder = zlib.decompressobj()
        raw = decoder.decompress(value, _REDIS_MAX_SNAPSHOT_BYTES + 1)
        if not decoder.eof or len(raw) > _REDIS_MAX_SNAPSHOT_BYTES:
            return None
        return _snapshot_codec.validate_json(raw)
    except (RedisError, ValidationError, ValueError, zlib.error) as exc:
        logger.debug("Dashboard Redis snapshot unavailable: {}", type(exc).__name__)
        return None


def _save_redis_snapshot(key: str, data: _CachedRepositoryData) -> bool:
    try:
        raw = _snapshot_codec.dump_json(data)
        if len(raw) <= _REDIS_MAX_SNAPSHOT_BYTES:
            return bool(
                get_sync_redis_cache_client().set(
                    key,
                    zlib.compress(raw, level=1),
                    ex=_REDIS_TTL_SECONDS,
                )
            )
    except (RedisError, ValueError) as exc:
        logger.debug("Dashboard Redis snapshot could not be saved: {}", type(exc).__name__)
    return False


def read_repositories(
    workspace_id: str,
    repo_dirs: list[Path],
    *,
    since: int,
    refresh_started_at: float | None,
) -> dict[Path, RepositorySnapshot]:
    snapshots: dict[Path, RepositorySnapshot] = {}
    revisions = {repo_dir: _read_git_revision(repo_dir) for repo_dir in dict.fromkeys(repo_dirs)}
    missing: dict[Path, GitRevision | None] = {}
    with _cache_lock:
        now = time.monotonic()
        for repo_dir, revision in revisions.items():
            cached = _fresh_snapshot(
                (workspace_id, repo_dir),
                revision=revision,
                now=now,
                refresh_started_at=refresh_started_at,
            )
            if cached and cached.since <= since and cached.commits is not None:
                snapshots[repo_dir] = cached
            else:
                missing[repo_dir] = revision

    # Cache hits never wait behind a cold workspace. Worktree and Git I/O
    # for all cold workspaces share the same bounded worker pool.
    jobs = {
        repo_dir: _scan_executor.submit(
            _read_repository,
            workspace_id,
            repo_dir,
            revision=revision,
            since=since,
            refresh_started_at=refresh_started_at,
        )
        for repo_dir, revision in missing.items()
    }
    snapshots.update((repo_dir, job.result()) for repo_dir, job in jobs.items())
    return snapshots


def _read_repository(
    workspace_id: str,
    repo_dir: Path,
    *,
    revision: GitRevision | None,
    since: int,
    refresh_started_at: float | None,
) -> RepositorySnapshot:
    """Share a bounded scan per repo and serialize overlapping cache misses."""
    key = (workspace_id, repo_dir)
    with _scan_locks[hash(key) % len(_scan_locks)]:
        started_at = time.monotonic()
        with _cache_lock:
            generation = _cache_generation
            cached = _fresh_snapshot(key, revision=revision, now=started_at, refresh_started_at=refresh_started_at)
            previous = _cache.get(key) if refresh_started_at is None else None

        if cached and cached.since <= since and cached.commits is not None:
            return cached

        redis_key = _redis_key(workspace_id, repo_dir, revision) if revision is not None else None
        history = None
        persisted = False
        if (
            revision is not None
            and previous
            and previous.revision == revision
            and previous.is_git
            and previous.since <= since
            and previous.commits is not None
        ):
            history = _CachedRepositoryData(previous.files, previous.commits, previous.since)
            persisted = previous.persisted
        elif redis_key is not None and refresh_started_at is None:
            history = _load_redis_snapshot(redis_key)
            persisted = history is not None

        if cached:
            files, is_git = cached.files, cached.is_git
            scanned_at, expires_at = cached.scanned_at, cached.expires_at
        else:
            seed: Sequence[ScannedFile] = history.files if history else ()
            if previous is not None:
                seed = previous.files
            files, is_git = _scan_repo_files(repo_dir, seed)
            scanned_at = started_at

        if is_git and history is not None and history.since <= since:
            commits, since = history.commits, history.since
        elif is_git:
            commits = _scan_repo_commits(repo_dir, since, revision)
            persisted = False
        else:
            commits = []
            persisted = False
        if redis_key and is_git and commits is not None and not persisted and _read_git_revision(repo_dir) == revision:
            persisted = _save_redis_snapshot(redis_key, _CachedRepositoryData(files, commits, since))
        if not cached:
            expires_at = time.monotonic() + _CACHE_TTL_SECONDS
        snapshot = RepositorySnapshot(revision, files, is_git, commits, since, scanned_at, expires_at, persisted)
        # A timed-out history can be retried on the next request without reading the worktree again.
        with _cache_lock:
            if generation == _cache_generation:
                _cache[key] = snapshot
                _cache.move_to_end(key)
                if len(_cache) > _CACHE_MAX_REPOS:
                    _cache.popitem(last=False)
        return snapshot


def normalize_rel_path(raw: str) -> str:
    return raw.replace("\\", "/").removeprefix("./")


def infer_module_name(rel_path: str) -> str:
    """Derive a readable 1-to-2 level module bucket for any repository layout."""
    parts = normalize_rel_path(rel_path).split("/")
    dirs = parts[:-1]
    if not dirs:
        return "(root)"
    if len(dirs) == 1:
        return dirs[0]
    if dirs[0] in _CONTAINER_DIRS:
        if len(dirs) >= 3 and dirs[1] in _CONTAINER_DIRS:
            return f"{dirs[1]}/{dirs[2]}"
        return f"{dirs[0]}/{dirs[1]}"
    if len(dirs) >= 3 and dirs[1] in _CONTAINER_DIRS:
        return f"{dirs[0]}/{dirs[2]}"
    return dirs[0]


def _source_language(rel_path: str) -> str | None:
    name = rel_path.lower()
    if name.endswith((".d.ts", ".min.js", ".min.css")):
        return None
    language = _SOURCE_EXTS.get(posixpath.splitext(name)[1])
    if language and not any(part.startswith(".") or part in _SKIP_DIRS for part in name.split("/")[:-1]):
        return language
    return None


def _count_source_lines(full_path: str) -> int:
    try:
        with open(full_path, "rb") as source:
            data = source.read(_MAX_FILE_BYTES + 1)
        if not data or len(data) > _MAX_FILE_BYTES or b"\x00" in data[:1024]:
            return 0
        return data.count(b"\n") + (not data.endswith(b"\n"))
    except OSError:
        return 0


def _list_repo_source_paths(repo_dir: Path) -> tuple[list[str], bool]:
    try:
        result = run_git(
            ["ls-files", "-z"],
            cwd=str(repo_dir),
            timeout_seconds=8,
            unset_env=GIT_REPOSITORY_ENV_VARS,
            decode_text=False,
        )
        if result.returncode == 0:
            paths = result.stdout.decode("utf-8", errors="replace").split("\0")[:-1]
            return list(dict.fromkeys(paths)), True
    except (OSError, ProcessTimeoutError) as exc:
        logger.warning("Unable to list Git files for dashboard in {}: {}", repo_dir, type(exc).__name__)

    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        root = Path(dirpath).relative_to(repo_dir)
        for filename in filenames:
            rel = (root / filename).as_posix()
            if _source_language(rel):
                paths.append(rel)
                if len(paths) == _MAX_FILES_PER_REPO:
                    return paths, False
    return paths, False


def _directory_file_stats(
    directory: str,
    files: dict[str, str],
) -> Iterator[tuple[str, str, os.stat_result]]:
    remaining = files.copy()
    if len(files) > 1:
        # On Windows DirEntry includes the file size and timestamps from the
        # directory listing, avoiding a separate stat for each tracked path.
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    rel = remaining.get(entry.name)
                    if rel is None:
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    del remaining[entry.name]
                    yield rel, entry.path, info
                    if not remaining:
                        return
        except OSError:
            pass

    for name, rel in remaining.items():
        path = os.path.join(directory, name)
        try:
            yield rel, path, os.lstat(path)
        except OSError:
            continue


def _scan_repo_files(
    repo_dir: Path,
    previous_files: Sequence[ScannedFile] = (),
) -> tuple[list[ScannedFile], bool]:
    rel_paths, is_git = _list_repo_source_paths(repo_dir)
    candidates: dict[str, str] = {}
    by_directory: dict[str, dict[str, str]] = defaultdict(dict)
    for rel in rel_paths:
        language = _source_language(rel)
        if language is None:
            continue
        candidates[rel] = language
        parent, _, name = rel.rpartition("/")
        by_directory[parent][name] = rel
        if len(candidates) == _MAX_FILES_PER_REPO:
            break

    previous_by_path = {file.path: file for file in previous_files}
    scanned: dict[str, ScannedFile] = {}
    for parent, files in by_directory.items():
        for rel, path, info in _directory_file_stats(os.path.join(repo_dir, parent), files):
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_FILE_BYTES:
                continue
            stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            previous = previous_by_path.get(rel)
            if previous and previous.stamp == stamp:
                scanned[rel] = previous
            elif loc := _count_source_lines(path):
                scanned[rel] = ScannedFile(
                    rel,
                    posixpath.basename(rel),
                    infer_module_name(rel),
                    loc,
                    candidates[rel],
                    stamp,
                )
    return [scanned[rel] for rel in candidates if rel in scanned], is_git


def _parse_git_numstat_log(raw_output: str) -> list[ParsedCommit]:
    commits: list[ParsedCommit] = []
    current: ParsedCommit | None = None
    # With -z, a leading NUL marks our commit header. Rename numstat records
    # carry an empty path followed by the original and destination paths.
    records = iter(raw_output.split("\0"))
    for record in records:
        if not record:
            short_hash = next(records, "")
            if not short_hash:
                continue
            timestamp, date, subject = next(records), next(records), next(records)
            current = ParsedCommit(short_hash, int(timestamp), date, subject, [])
            commits.append(current)
            continue
        if current is None:
            continue
        columns = record.lstrip("\n").split("\t", 2)
        if len(columns) != 3:
            continue
        ins, dels, rel = columns
        if not rel:
            next(records)  # original path
            rel = next(records)
        if _source_language(rel):
            current.files.append((rel, int(ins) if ins.isdigit() else 0, int(dels) if dels.isdigit() else 0))
    return sorted((commit for commit in commits if commit.files), key=lambda commit: commit.timestamp)


def _scan_repo_commits(repo_dir: Path, since: int, revision: GitRevision | None) -> list[ParsedCommit] | None:
    try:
        result = run_git(
            [
                "log",
                f"--since=@{since}",
                f"-n{_MAX_COMMITS_PER_REPO}",
                "--date=short",
                "--encoding=UTF-8",
                "--numstat",
                "-z",
                "--format=%x00%h%x00%ct%x00%ad%x00%s",
                "--no-ext-diff",
                "--no-textconv",
                "--no-notes",
                "--no-show-signature",
                "--no-color",
                revision.head if revision is not None else "HEAD",
                "--",
            ],
            cwd=str(repo_dir),
            timeout_seconds=10,
            unset_env=GIT_REPOSITORY_ENV_VARS,
            decode_text=False,
        )
        if result.returncode != 0:
            return None if revision is not None else []
        return _parse_git_numstat_log(result.stdout.decode("utf-8", errors="replace"))
    except (OSError, ProcessTimeoutError) as exc:
        logger.warning("Unable to read Git history for dashboard in {}: {}", repo_dir, type(exc).__name__)
        return None
