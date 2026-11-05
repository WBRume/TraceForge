"""A Windows checkout keeps CRLF while the repository keeps LF; identity must not care."""

from pathlib import Path

from app.domains.task.services import task_session_snapshot_service as snapshots
from app.domains.workspace_collaboration import content, delta, identity, review, service, session
from tests.workspace_collaboration.test_service import environment as repository_environment
from tests.workspace_collaboration.test_service import git

environment = repository_environment


def test_content_identity_ignores_line_endings_but_not_content():
    assert identity.content_digest(b"a\r\nb\r\n") == identity.content_digest(b"a\nb\n")
    assert identity.content_digest(b"a\rb") == identity.content_digest(b"a\nb")
    assert identity.content_digest(b"a\r\nb") != identity.content_digest(b"a\nc")
    # Binaries keep their exact bytes even when they contain CR/LF sequences.
    binary = bytes([0, 255, 13, 10])
    assert identity.content_digest(binary) == identity.content_digest(binary)
    assert identity.content_digest(binary) != identity.content_digest(bytes([0, 255, 10, 10]))


def test_same_file_compares_content_and_mode_only():
    left = {"path": "a.txt", "sha256": "1" * 64, "content_sha256": "c" * 64, "size": 10, "mode": "100644"}
    right = {"path": "a.txt", "sha256": "2" * 64, "content_sha256": "c" * 64, "size": 12, "mode": "100644"}
    assert identity.same_file(left, right)
    assert not identity.same_file(left, {**right, "mode": "100755"})
    assert not identity.same_file(left, {**right, "content_sha256": "d" * 64})
    assert identity.same_file(None, None) and not identity.same_file(left, None)


def test_crlf_checkout_is_not_a_cumulative_change(environment):
    db, task, root = environment
    repo = root / "api"
    (repo / "same.txt").write_bytes(b"api baseline\n")
    git(repo, "commit", "-am", "repository keeps LF")
    sha = git(repo, "rev-parse", "HEAD")
    task.task_meta_json = {**(task.task_meta_json or {}), "repository_baselines": {"api": sha}}
    db.commit()
    # A Windows checkout of the same commit keeps CRLF on disk.
    (repo / "same.txt").write_bytes(b"api baseline\r\n")

    baseline = review.committed_baseline(db, task, "viewer")
    cloud = session.latest_snapshot(db, task, "viewer", None)
    # The checkout form is not a change, so the review payload stays empty.
    assert review.diff(db, task, "viewer")["files"] == []
    old = next(
        file
        for repo in baseline["repositories"]
        if repo["repo_slug"] == "api"
        for file in repo["files"]
        if file["path"] == "same.txt"
    )
    new = next(
        file
        for repo in cloud["repositories"]
        if repo["repo_slug"] == "api"
        for file in repo["files"]
        if file["path"] == "same.txt"
    )
    assert old["sha256"] != new["sha256"]
    assert old["content_sha256"] == new["content_sha256"]
    assert identity.same_file(old, new)


def test_same_repositories_ignores_order_and_checkout_form():
    repository = {"task_repository_id": "r", "rel_path": "r"}
    lf = {
        **repository,
        "files": [{"path": "a.txt", "sha256": "1" * 64, "content_sha256": "c" * 64, "mode": "100644", "size": 3}],
    }
    crlf = {
        **repository,
        "files": [{"path": "a.txt", "sha256": "2" * 64, "content_sha256": "c" * 64, "mode": "100644", "size": 4}],
    }
    other = {"task_repository_id": "z", "rel_path": "z", "files": []}
    assert identity.same_repositories([lf, other], [other, crlf])
    assert not identity.same_repositories([lf], [other])
    edited = {**crlf, "files": [{**crlf["files"][0], "content_sha256": "d" * 64}]}
    assert not identity.same_repositories([lf], [edited])
    assert identity.repositories_digest([lf, other]) == identity.repositories_digest([crlf, other])


def test_delta_omits_line_ending_only_changes():
    base = {
        "task_id": "t",
        "snapshot_id": "s1",
        "repository_set_digest": "d",
        "repositories": [
            {
                "task_repository_id": "r",
                "files": [
                    {"path": "a.txt", "sha256": "1" * 64, "content_sha256": "c" * 64, "size": 3, "mode": "100644"}
                ],
            }
        ],
    }
    target = {
        **base,
        "snapshot_id": "s2",
        "repositories": [
            {
                "task_repository_id": "r",
                "files": [
                    {"path": "a.txt", "sha256": "2" * 64, "content_sha256": "c" * 64, "size": 4, "mode": "100644"},
                    {"path": "b.txt", "sha256": "3" * 64, "content_sha256": "e" * 64, "size": 1, "mode": "100644"},
                ],
            }
        ],
    }
    repositories = delta.between(base, target)["repositories"]
    assert [file["path"] for file in repositories[0]["files"]] == ["b.txt"]


def test_apply_manifest_installs_the_server_checkout_form(environment):
    db, task, root = environment
    api, web = root / "api", root / "web"
    (api / "same.txt").write_bytes(b"api baseline\n")
    git(api, "commit", "-am", "repository keeps LF")
    # Simulate the Windows host that produced the false "modified" list.
    git(api, "config", "core.autocrlf", "true")
    git(web, "config", "core.autocrlf", "true")
    (api / "same.txt").write_bytes(b"api baseline\r\n")
    service._ensure_store(db, task)
    repositories = service.repository_metadata(db, task)
    baseline = {"repositories": service._inventory(task.id, task.project_path, repositories, stable=True)}
    store = content.ObjectStore(task)
    raw = b"human input\n"
    target = {
        "repositories": [
            {
                **repositories[0],
                "files": [
                    {
                        "path": "same.txt",
                        "sha256": store.put(raw),
                        "content_sha256": identity.content_digest(raw),
                        "size": len(raw),
                        "mode": "100644",
                    },
                    *[file for file in baseline["repositories"][0]["files"] if file["path"] != "same.txt"],
                ],
            },
            {**repositories[1], "files": baseline["repositories"][1]["files"]},
        ]
    }
    content.apply_manifest(root, baseline, target, store, "operation-line-endings")
    assert (api / "same.txt").read_bytes() == b"human input\r\n"
    assert identity.content_digest((api / "same.txt").read_bytes()) == identity.content_digest(raw)
    # The install is idempotent because identity ignores the checkout form.
    content.apply_manifest(root, baseline, target, store, "operation-line-endings")
    assert (api / "same.txt").read_bytes() == b"human input\r\n"


def test_checkpoint_inventory_exposes_content_digest(environment):
    db, task, root = environment
    (root / "api" / "same.txt").write_bytes(b"api baseline\r\n")
    service._ensure_store(db, task)
    repositories = service.repository_metadata(db, task)
    checkpoint = snapshots._create_checkpoint_sync(
        task.project_path,
        ["api", "web"],
        "none",
        None,
        task.workspace_id,
        "Multi repo",
        task.id,
        task.name,
        initial_checkpoint=task.task_meta_json["initial_workspace_checkpoint"],
    )
    inventory = review._checkpoint_inventory(
        Path(checkpoint["root"]) / "worktree.json", task, repositories, content.ObjectStore(task)
    )
    entry = next(
        file for repo in inventory if repo["repo_slug"] == "api" for file in repo["files"] if file["path"] == "same.txt"
    )
    assert entry["content_sha256"] == identity.content_digest(b"api baseline\r\n")
    assert entry["content_sha256"] == identity.content_digest(b"api baseline\n")
