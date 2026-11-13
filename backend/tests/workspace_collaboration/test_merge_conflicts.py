"""Real Git conflicts remain deliverable without changing the real merge index."""

from pathlib import Path

import pytest
from workspace_collaboration import test_service as fixtures
from workspace_collaboration.test_service import acknowledge, git, input_request, preparing

from app.core.subprocess_runner import run_git
from app.domains.workspace_collaboration import content, service

environment = fixtures.environment


CONFLICT_PATHS = ("same.txt", "binary.bin", "new.txt")


def create_conflicts(root: Path) -> None:
    branch = git(root, "branch", "--show-current")
    git(root, "switch", "-c", "other")
    for name in CONFLICT_PATHS:
        (root / name).write_bytes(b"other side\n")
    git(root, "add", "--", *CONFLICT_PATHS)
    git(root, "commit", "-m", "other")
    git(root, "switch", branch)
    git(root, "rm", "binary.bin")
    for name in ("same.txt", "new.txt"):
        (root / name).write_bytes(b"task side\n")
    git(root, "add", "--", "same.txt", "new.txt")
    git(root, "commit", "-m", "task")
    result = run_git(["merge", "--no-edit", "other"], cwd=str(root), decode_text=True)
    assert result.returncode == 1
    assert set(git(root, "diff", "--name-only", "--diff-filter=U").splitlines()) == set(CONFLICT_PATHS)


def test_dual_repo_unmerged_output_delivered_without_touching_git_state(environment):
    db, task, root = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    service.authorize_execution(db, task, "submission", "job")
    db.commit()
    original = {}
    for slug in ("api", "web"):
        repo = root / slug
        create_conflicts(repo)
        original[slug] = {
            "index": (repo / ".git/index").read_bytes(),
            "merge_head": git(repo, "rev-parse", "MERGE_HEAD"),
            "head": git(repo, "rev-parse", "HEAD"),
            "files": {name: (repo / name).read_bytes() for name in CONFLICT_PATHS},
        }
        assert content._tracked_modes(repo, list(CONFLICT_PATHS)) == dict.fromkeys(CONFLICT_PATHS, "100644")
    assert service.capture_progress(db, task, "job") is not None
    db.commit()
    state = service.finish_execution(db, task, "job", confirmed_stopped=True)
    db.commit()
    assert state["sync_phase"] == "DELIVERY_PENDING"
    snapshot = service.get_snapshot(db, task.id, state["snapshot_id"])
    store = content.ObjectStore(task)
    for item in snapshot["repositories"]:
        repo = root / item["rel_path"]
        before = original[item["rel_path"]]
        files = {file["path"]: file for file in item["files"]}
        for name, data in before["files"].items():
            assert store.read(files[name]["sha256"]) == data
            assert (repo / name).read_bytes() == data
        assert (repo / ".git/index").read_bytes() == before["index"]
        assert git(repo, "rev-parse", "MERGE_HEAD") == before["merge_head"]
        assert git(repo, "rev-parse", "HEAD") == before["head"]
    assert acknowledge(environment, state)["sync_phase"] == "READY"


def test_conflicted_link_index_is_still_rejected(environment):
    _db, _task, root = environment
    repo = root / "api"
    oid = git(repo, "rev-parse", "HEAD:same.txt")
    git(repo, "update-index", "--force-remove", "same.txt")
    result = run_git(
        ["update-index", "-z", "--index-info"],
        cwd=str(repo),
        decode_text=False,
        input_data="".join(
            f"{mode} {oid} {stage}\tsame.txt\0" for mode, stage in [("120000", 1), ("100644", 2), ("100644", 3)]
        ).encode(),
    )
    assert result.returncode == 0, result.stderr
    assert "120000" in git(repo, "ls-files", "-u"), (result.stdout, result.stderr)
    with pytest.raises(ValueError, match="Unsupported submodule, link or unmerged file"):
        content._tracked_modes(repo)
