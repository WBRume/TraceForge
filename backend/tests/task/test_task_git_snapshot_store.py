"""Real filesystem and Git round trips for persistent snapshot indexes."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domains.task.services import task_git_snapshot_store as snapshots
from app.domains.task.services import task_session_snapshot_service as service
from app.domains.task.services import task_snapshot_store as files

POLICY = {"excluded_dirs": ["node_modules", "dist"], "excluded_suffixes": [".pyc"]}


def write(root, relative, data=b"initial\r\n\x00\xff"):
    p = root / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def git(root, *args):
    return snapshots.git(str(root), list(args))


def init(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.test")
    git(root, "config", "core.autocrlf", "false")


def capture(tmp, name="turn-a"):
    return snapshots.capture(str(tmp / "task"), [], str(tmp / name), str(tmp), POLICY)


def restore(tmp, name="turn-a"):
    service._restore_worktree_sync(str(tmp / name), str(tmp / "task"), str(tmp / name / "current-worktree"))


def test_non_git_initial_state_untracked_files_empty_dirs_and_multiple_turns(tmp_path):
    root = tmp_path / "task"
    write(root, "init.txt", b"first round initialization")
    write(root, "manual.txt", b"user edit before second message")
    (root / "empty").mkdir()
    first = capture(tmp_path)
    write(root, "manual.txt", b"second turn")
    write(root, "new/never-added.txt")
    capture(tmp_path, "turn-b")
    (root / "init.txt").unlink()
    restore(tmp_path, "turn-b")
    assert (root / "init.txt").read_bytes() == b"first round initialization"
    restore(tmp_path)
    assert (root / "manual.txt").read_bytes() == b"user edit before second message"
    assert not (root / "new").exists()
    assert (root / "empty").is_dir()
    assert not (root / ".git").exists()
    assert first["version"] == 4


def test_seed_preserves_staged_unstaged_and_source_independence(tmp_path):
    root = tmp_path / "task"
    init(root)
    write(root, "a", b"committed")
    git(root, "add", ".")
    git(root, "commit", "-m", "seed")
    write(root, "a", b"staged")
    git(root, "add", "a")
    write(root, "a", b"unstaged")
    write(root, "untracked")
    write(root, ".gitignore", b".env\n")
    write(root, ".env", b"secret-local")
    index = (root / ".git/index").read_bytes()
    first = capture(tmp_path)
    assert (root / ".git/index").read_bytes() == index
    assert not Path(first["partitions"][0]["git_dir"], "objects/info/alternates").exists()
    write(root, "a", b"changed")
    (root / "untracked").unlink()
    write(root, "new")
    git(root, "add", ".")
    restore(tmp_path)
    assert (root / "a").read_bytes() == b"unstaged"
    assert (root / "untracked").read_bytes() == b"initial\r\n\x00\xff"
    assert (root / ".git/index").read_bytes() == index
    assert not (root / "new").exists()
    assert (root / ".env").read_bytes() == b"secret-local"


def test_empty_non_git_and_git_init_can_be_undone_and_compensated(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    capture(tmp_path)
    init(root)
    write(root, "new")
    git(root, "add", ".")
    git(root, "commit", "-m", "created")
    head = git(root, "rev-parse", "HEAD")
    restore(tmp_path)
    assert list(root.iterdir()) == []
    service._restore_worktree_sync(
        str(tmp_path / "turn-a/current-worktree"), str(root), str(tmp_path / "turn-a/recovery")
    )
    assert git(root, "rev-parse", "HEAD") == head
    assert (root / "new").is_file()


def test_unborn_and_nested_repositories(tmp_path):
    root = tmp_path / "task"
    init(root)
    init(root / "nested")
    write(root, "root.txt")
    write(root, "nested/local.txt")
    first = capture(tmp_path)
    assert len(first["repositories"]) == 2
    assert len(snapshots.entries(first)) == 2
    git(root / "nested", "add", ".")
    git(root / "nested", "commit", "-m", "later")
    write(root, "nested/local.txt", b"later")
    restore(tmp_path)
    assert (root / "nested/local.txt").read_bytes() == b"initial\r\n\x00\xff"
    assert not (root / "nested/.git/index").exists()


def test_raw_bytes_with_attributes_and_autocrlf(tmp_path):
    root = tmp_path / "task"
    init(root)
    git(root, "config", "core.autocrlf", "true")
    write(root, ".gitattributes", b"*.txt text\n")
    write(root, "a.txt", b"a\r\nb\r\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "seed")
    capture(tmp_path)
    write(root, "a.txt", b"later")
    restore(tmp_path)
    assert (root / "a.txt").read_bytes() == b"a\r\nb\r\n"


def test_corrupt_index_fails_without_reinitialization(tmp_path):
    write(tmp_path / "task", "a")
    first = capture(tmp_path)
    index = Path(first["partitions"][0]["git_dir"], "index")
    index.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Git"):
        capture(tmp_path, "turn-b")
    assert index.read_bytes() == b"corrupt"
    assert not (tmp_path / "turn-b/worktree.json").exists()


def test_hot_capture_does_not_use_full_content_cas(tmp_path, monkeypatch):
    write(tmp_path / "task", "a")
    first = capture(tmp_path)
    monkeypatch.setattr(files, "capture_file", lambda *args: pytest.fail("full-file CAS capture invoked"))
    second = capture(tmp_path, "turn-b")
    assert first["partitions"][0]["tree"] == second["partitions"][0]["tree"]


def test_file_directory_transitions_and_excluded_files(tmp_path):
    root = tmp_path / "task"
    write(root, "file")
    write(root, "directory/a")
    write(root, "node_modules/keep", b"before")
    capture(tmp_path)
    (root / "file").unlink()
    write(root, "file/a")
    (root / "directory/a").unlink()
    (root / "directory").rmdir()
    write(root, "directory")
    write(root, "node_modules/keep", b"after")
    restore(tmp_path)
    assert (root / "file").is_file()
    assert (root / "directory/a").is_file()
    assert (root / "node_modules/keep").read_bytes() == b"after"


def test_gc_preserves_other_checkpoint_and_hot_index(tmp_path):
    root = tmp_path / "task"
    write(root, "a", b"first")
    capture(tmp_path)
    write(root, "a", b"second")
    capture(tmp_path, "turn-b")
    service._cleanup_checkpoint_sync(str(tmp_path / "turn-b"))
    restore(tmp_path)
    assert (root / "a").read_bytes() == b"first"
    capture(tmp_path, "turn-c")


@pytest.mark.parametrize("seeded", [False, True], ids=["non-git", "seeded-git"])
def test_long_snapshot_path_creates_reuses_restores_and_collects(tmp_path_factory, monkeypatch, seeded):
    # Git for Windows also limits cwd to MAX_PATH; reproduce the separate
    # UTF-8 GIT_DIR limit with the same Unicode task name in a short temp root.
    tmp_path = tmp_path_factory.mktemp("snap")
    root = tmp_path / "task"
    original = b"original\r\n\x00\xff"
    if seeded:
        init(root)
    write(root, "shared/a.txt", original)
    if seeded:
        git(root, "add", ".")
        git(root, "commit", "-m", "seed")
        source_index = (root / ".git/index").read_bytes()
    snapshot_root = tmp_path / "snapshots"
    monkeypatch.setattr(service.settings, "TASK_SESSION_SNAPSHOT_ROOT", str(snapshot_root))
    identity = (
        "86c8697d-ccea-4a6e-b494-5bbec15f1726",
        "test",
        "0040c159-98fa-4437-b428-b7c70a0eaab8",
        "系统层：用户权限、Claude Runtime 节点管理、MCP 服务网关与操作",
    )
    first = service._create_checkpoint_sync(str(root), [], "none", None, *identity)
    directory = first["worktree"]["partitions"][0]["git_dir"]
    assert len(directory.encode("utf-8")) > 220
    write(root, "shared/a.txt", b"second turn")
    second = service._create_checkpoint_sync(str(root), [], "none", None, *identity, initial_checkpoint=first["root"])
    assert second["worktree"]["partitions"][0]["git_dir"] == directory
    write(root, "new.txt", b"created later")
    service._restore_worktree_sync(first["root"], str(root), str(Path(first["root"], "current-worktree")))
    assert (root / "shared/a.txt").read_bytes() == original
    assert not (root / "new.txt").exists()
    if seeded:
        assert (root / ".git/index").read_bytes() == source_index
    service._cleanup_checkpoint_sync(second["root"])
    assert snapshots.validate(first["worktree"])["shared/a.txt"]["git_dir"] == directory
    service._create_checkpoint_sync(str(root), [], "none", None, *identity, initial_checkpoint=first["root"])


@pytest.mark.parametrize("packed", [False, True])
def test_seed_objects_survive_source_object_store_replacement(tmp_path, packed):
    root = tmp_path / "task"
    init(root)
    write(root, "a", b"independent source blob")
    git(root, "add", ".")
    git(root, "commit", "-m", "seed")
    if packed:
        git(root, "gc")
    saved = capture(tmp_path)
    # Simulate source GC/unlink: the independent shadow must retain its bytes.
    (root / ".git/objects").rename(root / ".git/detached-objects")
    (root / ".git/objects").mkdir()
    entries = snapshots.validate(saved)
    item = entries["a"]
    assert git(root, "--git-dir=" + item["git_dir"], "cat-file", "blob", item["oid"]) == b"independent source blob"


def test_linked_worktree_uses_own_index(tmp_path):
    source = tmp_path / "source"
    init(source)
    write(source, "a", b"source")
    git(source, "add", ".")
    git(source, "commit", "-m", "seed")
    root = tmp_path / "task"
    git(source, "worktree", "add", "-b", "task", str(root))
    write(root, "a", b"task staged")
    git(root, "add", "a")
    write(root, "a", b"task unstaged")
    source_index = (source / ".git/index").read_bytes()
    capture(tmp_path)
    write(root, "a", b"later")
    restore(tmp_path)
    assert (root / "a").read_bytes() == b"task unstaged"
    assert git(root, "show", ":a") == b"task staged"
    assert (source / ".git/index").read_bytes() == source_index


def test_dsh_ambiguous_session_is_not_treated_as_missing(tmp_path, monkeypatch):
    from app.agents.errors import SessionForkError
    from app.agents.session_checkpoint import session_checkpoint_adapter

    for project in ("project-one", "project-two"):
        write(tmp_path, project + "/session-test/session.jsonl", b"{}\n")
    monkeypatch.setattr(service, "_dsh_root", lambda: str(tmp_path))
    with pytest.raises(SessionForkError):
        session_checkpoint_adapter("dsh").locate("", "session-test")
    with pytest.raises(SessionForkError):
        service._fork_dsh_session_sync("session-test", str(tmp_path))


def test_tree_enumeration_checks_shared_parents_once_per_read_phase(tmp_path, monkeypatch):
    root = tmp_path / "task"
    write(root, "shared/deep/a")
    real_stat = os.lstat
    calls = []

    def counted(path, *args, **kwargs):
        calls.append(str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", counted)
    paths = files.ReadPhasePaths(str(root))
    for index in range(1000):
        paths(f"shared/deep/file-{index}")
    assert len(calls) == 2
    files.ReadPhasePaths(str(root))("shared/deep/a")
    assert len(calls) == 4  # New phase must not reuse stale filesystem state.


@pytest.mark.parametrize("junction", [False, True])
def test_read_phase_paths_still_reject_link_parents(tmp_path, monkeypatch, junction):
    real_stat = os.lstat

    def linked(path, *args, **kwargs):
        if Path(path).name == "link":
            return SimpleNamespace(
                st_mode=stat.S_IFDIR if junction else stat.S_IFLNK, st_file_attributes=0x400 if junction else 0
            )
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", linked)
    monkeypatch.setattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400, raising=False)
    with pytest.raises(ValueError, match="traverses a link"):
        files.ReadPhasePaths(str(tmp_path))("link/child")
    with pytest.raises(ValueError, match="Invalid snapshot path"):
        files.ReadPhasePaths(str(tmp_path))("../outside")
