"""Real Git conflicts remain deliverable without changing the real merge index."""

from pathlib import Path

import pytest
from workspace_collaboration import test_service as fixtures
from workspace_collaboration.test_service import acknowledge, git, input_request, preparing

from app.core.subprocess_runner import run_git
from app.domains.workspace_collaboration import content, service

environment = fixtures.environment


def create_conflict(root: Path, kind: str) -> None:
    branch = git(root, "branch", "--show-current")
    name = "new.txt" if kind == "add-add" else "same.txt"
    git(root, "switch", "-c", "other")
    (root / name).write_bytes(b"other side\n")
    git(root, "add", name)
    git(root, "commit", "-m", "other")
    git(root, "switch", branch)
    if kind == "delete-modify":
        git(root, "rm", name)
    else:
        (root / name).write_bytes(b"task side\n")
        git(root, "add", name)
    git(root, "commit", "-m", "task")
    result = run_git(["merge", "--no-edit", "other"], cwd=str(root), decode_text=True)
    assert result.returncode == 1 and git(root, "ls-files", "-u")


@pytest.mark.parametrize("kind", ["modify-modify", "delete-modify", "add-add"])
def test_dual_repo_unmerged_output_delivered_without_touching_git_state(environment, kind):
    db, task, root = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    service.authorize_execution(db, task, "submission", "job")
    db.commit()
    original = {}
    name = "new.txt" if kind == "add-add" else "same.txt"
    for slug in ("api", "web"):
        repo = root / slug
        create_conflict(repo, kind)
        original[slug] = {
            "index": (repo / ".git/index").read_bytes(),
            "merge_head": git(repo, "rev-parse", "MERGE_HEAD"),
            "head": git(repo, "rev-parse", "HEAD"),
            "bytes": (repo / name).read_bytes(),
        }
        assert content._tracked_modes(repo, [name]) == {name: "100644"}
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
        file = next(f for f in item["files"] if f["path"] == name)
        assert store.read(file["sha256"]) == before["bytes"]
        assert (repo / ".git/index").read_bytes() == before["index"]
        assert git(repo, "rev-parse", "MERGE_HEAD") == before["merge_head"]
        assert git(repo, "rev-parse", "HEAD") == before["head"]
        assert (repo / name).read_bytes() == before["bytes"]
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
