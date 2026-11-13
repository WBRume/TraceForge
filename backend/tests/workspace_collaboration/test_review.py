from pathlib import Path
from zipfile import ZipFile

import pytest

from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.task.models.task import TaskType
from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.task.services import task_session_snapshot_service as snapshots
from app.domains.workspace_collaboration import content, export, review, service
from app.domains.workspace_collaboration.models import CollaborationState
from tests.workspace_collaboration.test_service import enabled, git
from tests.workspace_collaboration.test_service import environment as repository_environment

environment = repository_environment


def test_committed_review_reads_immutable_objects_without_walking_checkout_parents(environment, monkeypatch):
    db, task, _ = environment
    service._ensure_store(db, task)
    monkeypatch.setattr(
        review.snapshot_files,
        "ReadPhasePaths",
        lambda *_: pytest.fail("Immutable review must not traverse the checkout"),
    )
    baseline = review.committed_baseline(db, task, "viewer")
    assert {repo["repo_slug"] for repo in baseline["repositories"]} == {"api", "web"}


def test_provisioning_prepares_the_immutable_review_baseline(environment, monkeypatch):
    from app.domains.auth.models.user import Workspace
    from app.domains.task.services.provisioning.resources import _prepare_initial_workspace_checkpoint

    db, task, _ = environment
    _prepare_initial_workspace_checkpoint(db, db.get(Workspace, task.workspace_id), task)
    from app.domains.workspace_collaboration.models import CollaborationSnapshot

    assert db.query(CollaborationSnapshot).filter_by(task_id=task.id, source="DOWNLOAD").count() == 1
    assert db.query(CollaborationState).filter_by(task_id=task.id).first() is None
    monkeypatch.setattr(review.git_store, "tree_entries", lambda *args, **kwargs: pytest.fail("Already prepared"))
    assert len(review.committed_baseline(db, task, "viewer")["repositories"]) == 2


def test_cumulative_baseline_is_committed_code_and_cached_across_turns(environment, monkeypatch):
    db, task, root = environment
    (root / "api/same.txt").write_bytes(b"first turn output\n")
    (root / "web/second.txt").write_bytes(b"second turn output\n")
    before = {repo: git(root / repo, "status", "--porcelain") for repo in ["api", "web"]}
    baseline = review.committed_baseline(db, task, "viewer")
    db.commit()
    store = content.ObjectStore(task)
    for repo in baseline["repositories"]:
        same = next(file for file in repo["files"] if file["path"] == "same.txt")
        assert store.read(same["sha256"]) == (repo["repo_slug"] + " baseline\r\n").encode()
        assert all(file["path"] != "second.txt" for file in repo["files"])
    assert db.get(CollaborationState, task.id) is None
    assert before == {repo: git(root / repo, "status", "--porcelain") for repo in before}
    task.session_revision += 1
    monkeypatch.setattr(review.git_store, "tree_entries", lambda *args: pytest.fail("Baseline must be reused"))
    assert review.committed_baseline(db, task, "viewer")["snapshot_id"] == baseline["snapshot_id"]


def test_cumulative_baseline_moves_only_after_remote_update_is_applied(environment):
    db, task, root = environment
    first = review.committed_baseline(db, task, "viewer")
    db.commit()
    (root / "api/same.txt").write_bytes(b"new remote baseline\n")
    git(root / "api", "commit", "-am", "remote advance")
    target = git(root / "api", "rev-parse", "HEAD")
    # An advanced HEAD alone must not change the task's recorded baseline.
    assert review.committed_baseline(db, task, "viewer")["snapshot_id"] == first["snapshot_id"]
    task.task_meta_json = {**task.task_meta_json, "repository_baselines": {"api": target}}
    (root / "api/same.txt").write_bytes(b"preserved task output\n")
    latest = review.committed_baseline(db, task, "viewer")
    repo = next(repo for repo in latest["repositories"] if repo["repo_slug"] == "api")
    same = next(file for file in repo["files"] if file["path"] == "same.txt")
    assert latest["snapshot_id"] != first["snapshot_id"]
    assert content.ObjectStore(task).read(same["sha256"]) == b"new remote baseline\n"
    assert (root / "api/same.txt").read_bytes() == b"preserved task output\n"


def test_committed_review_uses_pinned_crlf_attributes_without_running_filters(environment):
    db, task, root = environment
    repo = root / "api"
    (repo / ".gitattributes").write_bytes(b"*.cmd text eol=crlf\n*.dat -text eol=crlf\n")
    (repo / "start.cmd").write_bytes(b"@echo off\nexit /b 0\n")
    (repo / "binary.dat").write_bytes(b"\x00\nkeep\n")
    git(repo, "add", ".gitattributes", "start.cmd", "binary.dat")
    git(repo, "commit", "-m", "explicit checkout line endings")
    sha = git(repo, "rev-parse", "HEAD")
    task.task_meta_json = {**(task.task_meta_json or {}), "repository_baselines": {"api": sha}}
    # Neither current attributes nor current output may redefine the baseline.
    (repo / ".gitattributes").write_bytes(b"*.cmd text eol=lf filter=forbidden\n")
    git(repo, "config", "filter.forbidden.smudge", "a-command-that-must-never-execute")
    git(repo, "config", "filter.forbidden.required", "true")
    (repo / "start.cmd").write_bytes(b"real agent change\r\n")
    before = (repo / ".git" / "index").read_bytes()

    baseline = review.committed_baseline(db, task, "viewer")
    files = next(item for item in baseline["repositories"] if item["repo_slug"] == "api")["files"]
    store = content.ObjectStore(task)
    data = {item["path"]: store.read(item["sha256"]) for item in files}
    assert data["start.cmd"] == b"@echo off\r\nexit /b 0\r\n"
    assert data["binary.dat"] == b"\x00\nkeep\n"
    assert (repo / "start.cmd").read_bytes() == b"real agent change\r\n"
    assert (repo / ".git" / "index").read_bytes() == before


def test_remote_update_without_a_new_turn_is_not_reported_as_round_edits(environment, monkeypatch):
    db, task, root = environment
    service._ensure_store(db, task)
    db.add(
        TaskSessionTurn(
            task_id=task.id,
            workspace_id=task.workspace_id,
            session_generation=1,
            session_revision=0,
            turn_index=1,
            provider="test",
            worktree_snapshot_path="old-generation-must-not-be-read.json",
        )
    )
    baselines = {}
    for name in ["api", "web"]:
        (root / name / "same.txt").write_bytes(b"remote v2\n")
        git(root / name, "commit", "-am", "remote advance")
        baselines[name] = git(root / name, "rev-parse", "HEAD")
        (root / name / "same.txt").write_bytes(b"remote v2\npreserved task output\n")
    task.task_meta_json = {**task.task_meta_json, "repository_baselines": baselines}
    task.session_generation = 2
    task.session_revision = 1
    db.commit()
    monkeypatch.setattr(review, "_checkpoint_inventory", lambda *args: pytest.fail("No round in this generation"))
    round_diff = review.diff(db, task, "viewer", "round")
    assert round_diff["scope"] == "round"
    assert round_diff["files"] == []
    assert round_diff["running"] is False
    assert round_diff["baseline_snapshot_id"] == round_diff["cloud_snapshot_id"]
    assert db.get(CollaborationState, task.id) is None
    baseline = review.committed_baseline(db, task, "viewer")
    entry = next(file for file in review.diff(db, task, "viewer")["files"] if file["path"] == "same.txt")
    committed = next(
        file
        for repo in baseline["repositories"]
        if repo["repo_slug"] == "api"
        for file in repo["files"]
        if file["path"] == "same.txt"
    )
    assert entry["left"] == committed
    assert content.ObjectStore(task).read(entry["right"]["sha256"]) == b"remote v2\npreserved task output\n"


def test_readonly_latest_turn_multi_repo_uses_recorded_input_without_connecting(environment, monkeypatch):
    db, task, root = environment
    generation = 2
    task.session_generation = generation
    service._ensure_store(db, task)
    (root / "api/same.txt").write_bytes(b"human input\n")
    (root / "api/.gitignore").write_text("private.log\n")
    (root / "api/private.log").write_text("private")
    (root / "api/.env").write_text("secret")
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
    db.add(
        TaskSessionTurn(
            id="turn",
            task_id=task.id,
            workspace_id=task.workspace_id,
            session_generation=generation,
            session_revision=0,
            turn_index=1,
            provider="test",
            worktree_snapshot_path=str(Path(checkpoint["root"]) / "worktree.json"),
        )
    )
    db.commit()
    # Changing ignore rules must not expose private files from the old snapshot.
    (root / "api/.gitignore").write_text("")
    (root / "api/private.log").unlink()
    (root / "api/same.txt").write_bytes(b"agent result\n")
    (root / "api/new.txt").write_text("created\n")
    (root / "web/same.txt").unlink()
    before = {repo: git(root / repo, "status", "--porcelain") for repo in ["api", "web"]}
    result = review.diff(db, task, "viewer", "round")
    db.commit()

    entries = {(file["repo_slug"], file["path"]): file for file in result["files"]}
    # The change set is exactly the human edits and the Agent work; ignored paths
    # never reach it, so private.log and .env stay invisible.
    assert set(entries) == {
        ("api", ".gitignore"),
        ("api", "same.txt"),
        ("api", "new.txt"),
        ("web", "same.txt"),
    }
    store = content.ObjectStore(task)
    assert store.read(entries["api", "same.txt"]["left"]["sha256"]) == b"human input\n"
    assert store.read(entries["api", "same.txt"]["right"]["sha256"]) == b"agent result\n"
    assert entries["api", "new.txt"]["change"] == "A" and entries["api", "new.txt"]["left"] is None
    assert entries["web", "same.txt"]["change"] == "D" and entries["web", "same.txt"]["right"] is None
    assert db.get(CollaborationState, task.id) is None
    assert before == {repo: git(root / repo, "status", "--porcelain") for repo in before}
    monkeypatch.setattr(review, "_checkpoint_inventory", lambda *args: pytest.fail("Baseline must be reused"))
    assert review.diff(db, task, "viewer", "round")["baseline_snapshot_id"] == result["baseline_snapshot_id"]


def test_active_collaboration_review_reuses_published_snapshots_without_changing_driver(environment, monkeypatch):
    db, task, _ = environment
    state = enabled(environment)
    monkeypatch.setattr(service, "_inventory", lambda *args, **kwargs: pytest.fail("No rescan for published results"))
    assert review.diff(db, task, "viewer")["cloud_snapshot_id"] == state["snapshot_id"]
    assert service.get_state(db, task) == state


def test_running_cloud_review_waits_for_final_cut_and_never_acquires_lease(environment, monkeypatch):
    db, task, _ = environment

    def writer(*_, **_kwargs):
        raise service.CollaborationError("WRITER_ACTIVE", "running")

    monkeypatch.setattr(service, "_assert_no_writer", writer)
    monkeypatch.setattr(service, "_inventory", lambda *args, **kwargs: pytest.fail("No final scan while executing"))
    assert review.diff(db, task, "viewer", "round")["running"] is True
    assert db.get(CollaborationState, task.id) is None


def test_repository_free_review_and_zip_preserve_binary_results(environment, tmp_path, monkeypatch):
    db, task, _ = environment
    db.query(SddTaskRepository).filter_by(task_id=task.id).delete()
    root = tmp_path / "standalone"
    root.mkdir()
    task.project_path = str(root)
    (root / "initial.txt").write_bytes(b"unchanged")
    (root / "code.py").write_bytes(b"original\n")
    checkpoint = snapshots._create_checkpoint_sync(
        str(root), [], "none", None, task.workspace_id, "Standalone", task.id, task.name
    )
    task.task_meta_json = {"initial_workspace_checkpoint": checkpoint["root"]}
    (root / "code.py").write_bytes(b"modified\n")
    (root / "reports").mkdir()
    report = b"PK\x00\xffbinary"
    (root / "reports/report.docx").write_bytes(report)
    (root / ".env").write_text("private")
    db.commit()

    result = review.diff(db, task, "viewer")
    entries = {entry["path"]: entry for entry in result["files"]}
    assert set(entries) == {"code.py", "reports/report.docx"}
    assert entries["code.py"]["change"] == "M"
    store = content.ObjectStore(task)
    assert store.read(entries["code.py"]["left"]["sha256"]) == b"original\n"
    assert service.get_state(db, task)["repository_configured"] is False
    assert db.get(CollaborationState, task.id) is None

    selected = [export.ExportFile(path=path, sha256=entry["right"]["sha256"]) for path, entry in entries.items()]
    with export.archive(store, selected) as output, ZipFile(output) as bundle:
        assert bundle.read("reports/report.docx") == report
        assert bundle.read("code.py") == b"modified\n"
    with pytest.raises(ValueError, match="Unsupported collaboration path"):
        export.archive(store, [export.ExportFile(path="../report.docx", sha256=selected[0].sha256)])

    (root / "reports/report.docx").write_bytes(b"still being written")

    def busy(*args, **kwargs):
        raise service.CollaborationError("WRITER_ACTIVE", "running")

    monkeypatch.setattr(service, "_assert_no_writer", busy)
    running = review.diff(db, task, "viewer")
    assert running["running"] is True
    assert running["files"] == result["files"]


def test_repository_and_task_root_results_share_the_cumulative_review(environment):
    db, task, root = environment
    baseline = review.committed_baseline(db, task, "viewer")
    db.commit()
    (root / "report.pdf").write_bytes(b"%PDF-binary\x00")
    (root / "api/report.pdf").write_bytes(b"%PDF-repository\x00")
    result = review.diff(db, task, "viewer")
    assert result["scope"] == "cumulative"
    assert result["baseline_snapshot_id"] == baseline["snapshot_id"]
    assert {(entry["repo_slug"], entry["path"]) for entry in result["files"]} == {
        ("", "report.pdf"),
        ("api", "report.pdf"),
    }
    for entry in result["files"]:
        assert entry["change"] == "A" and entry["left"] is None and entry["right"]["path"] == "report.pdf"


def test_initial_engine_output_is_reviewable_before_a_session_turn_is_recorded(environment):
    db, task, root = environment
    service._ensure_store(db, task)
    db.commit()
    (root / "api" / "same.txt").write_bytes(b"bootstrap agent edit\n")
    (root / "web" / "created.txt").write_bytes(b"bootstrap agent addition\n")
    result = review.diff(db, task, "viewer", "round")
    assert {(file["repo_slug"], file["path"], file["change"]) for file in result["files"]} == {
        ("api", "same.txt", "M"),
        ("web", "created.txt", "A"),
    }
    assert result["running"] is False
    assert db.query(TaskSessionTurn).filter_by(task_id=task.id).count() == 0
    assert db.get(CollaborationState, task.id) is None


def test_review_rejects_an_unknown_diff_scope(environment):
    db, task, _ = environment
    with pytest.raises(service.CollaborationError) as failure:
        review.diff(db, task, "viewer", "everything")
    assert failure.value.code == "REVIEW_SCOPE_INVALID"


def test_storage_root_is_configurable_and_pinned_across_configuration_changes(environment, tmp_path, monkeypatch):
    db, task, _ = environment
    configured = tmp_path / "collaboration-data"
    monkeypatch.setattr(content.settings, "COLLABORATION_SNAPSHOT_ROOT", str(configured))
    store = service._ensure_store(db, task)
    sha = store.put(b"durable input")
    db.commit()
    assert store.root == configured / task.id
    monkeypatch.setattr(content.settings, "COLLABORATION_SNAPSHOT_ROOT", str(tmp_path / "next-root"))
    assert service._ensure_store(db, task).read(sha) == b"durable input"
    assert content.ObjectStore(task).root == configured / task.id


def test_diagnosis_remains_excluded(environment):
    db, task, _ = environment
    task.task_type = TaskType.DIAGNOSIS
    with pytest.raises(service.CollaborationError) as error:
        review.diff(db, task, "viewer")
    assert error.value.code == "TASK_TYPE_UNSUPPORTED"
