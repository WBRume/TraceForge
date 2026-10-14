"""Real Git repositories: remote advancement, cloud output and review/apply fences."""

from uuid import uuid4

import pytest

from app.config import settings
from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_repository import SddTaskRepository, TaskRepositoryState
from app.domains.task.services.repository_updates import git, service, storage


def write(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(text if isinstance(text, bytes) else text.encode())


def commit(root):
    git.git(root, "add", "-A")
    git.git(root, "commit", "-m", "test")
    return git.git(root, "rev-parse", "HEAD")


@pytest.fixture
def env(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    user, workspace, task_id = (str(uuid4()) for _ in range(3))
    db.add(User(id=user, email="update@test.local", display_name="Reviewer", hashed_password="x"))
    db.add(Workspace(id=workspace, name="Two repos", owner_id=user))
    root = tmp_path / "task"
    root.mkdir()
    task = SddTask(
        id=task_id,
        workspace_id=workspace,
        creator_id=user,
        name="Update test",
        project_path=str(root),
        execution_location="SERVER",
        status=TaskStatus.CODING,
        session_generation=1,
        session_revision=0,
    )
    db.add(task)
    remotes = {}
    for name, branch in [("api", "release/2.x"), ("web", "feature/ui")]:
        remote = tmp_path / f"remote-{name}"
        remote.mkdir()
        git.git(remote, "init", "-b", branch)
        git.git(remote, "config", "core.autocrlf", "false")
        write(remote, "shared.txt", "first\n" + "middle\n" * 8 + "last\n")
        write(remote, "delete.txt", "original\n")
        write(remote, "binary.bin", b"\0base")
        sha = commit(remote)
        git.git(remote, "clone", "-c", "core.autocrlf=false", str(remote), str(root / name))
        git.git(root / name, "config", "core.autocrlf", "false")
        db.add(
            SddTaskRepository(
                id=str(uuid4()),
                task_id=task.id,
                repo_url=str(remote),
                repo_name=name,
                repo_slug=name,
                branch_name=branch,
                base_commit_sha=sha,
                rel_path=name,
                state=TaskRepositoryState.READY,
            )
        )
        remotes[name] = remote
    db.commit()
    return db, task, root, remotes, user


def prepare(env):
    db, task, _, _, actor = env
    result = service.prepare(db, task, actor)
    db.commit()
    return result


def apply(env, plan):
    db, task, _, _, actor = env
    result = service.apply(db, task, actor, plan["id"], plan["version"])
    db.commit()
    return result


def test_two_repositories_merge_and_preserve_creation_metadata(env):
    db, task, root, remotes, _ = env
    original = {r.id: r.base_commit_sha for r in service.repositories(db, task)}
    write(root / "api", "task-only.txt", "task output\n")
    write(root / "web", "shared.txt", "task\n" + "middle\n" * 8 + "last\n")
    write(remotes["api"], "remote-only.txt", "upstream\n")
    write(remotes["web"], "shared.txt", "first\n" + "middle\n" * 8 + "remote\n")
    targets = {name: commit(remote) for name, remote in remotes.items()}
    plan = prepare(env)
    assert plan["state"] == "READY"
    assert all(
        file["path"] not in {"delete.txt", "binary.bin"} for repo in plan["repositories"] for file in repo["files"]
    )
    assert not (root / "api" / "remote-only.txt").exists()
    assert (root / "web" / "shared.txt").read_text().endswith("last\n")
    assert apply(env, plan)["state"] == "APPLIED"
    assert (root / "api" / "task-only.txt").read_text() == "task output\n"
    assert (root / "api" / "remote-only.txt").read_text() == "upstream\n"
    assert (root / "web" / "shared.txt").read_text() == "task\n" + "middle\n" * 8 + "remote\n"
    for repo in service.repositories(db, task):
        assert repo.base_commit_sha == original[repo.id]
        assert storage.baseline(task, repo) == targets[repo.repo_slug]
        assert git.git(root / repo.rel_path, "rev-parse", "HEAD") == targets[repo.repo_slug]
    assert task.session_generation == 2


def test_conflicts_offer_three_versions_and_explicit_delete(env):
    db, task, root, remotes, actor = env
    write(root / "api", "shared.txt", "task\n")
    write(remotes["api"], "shared.txt", "remote\n")
    (root / "web" / "delete.txt").unlink()
    write(remotes["web"], "delete.txt", "remote edit\n")
    for remote in remotes.values():
        commit(remote)
    plan = prepare(env)
    assert plan["state"] == "CONFLICTS"
    api = next(r for r in plan["repositories"] if r["name"] == "api")
    web = next(r for r in plan["repositories"] if r["name"] == "web")
    detail = service.file_detail(task, plan["id"], api["id"], "shared.txt")
    assert detail["versions"]["task"]["text"] == "task\n"
    assert detail["versions"]["remote"]["text"] == "remote\n"
    assert detail["versions"]["base"]["text"].startswith("first\n")
    with pytest.raises(git.UpdateError, match="Git 冲突标记"):
        service.resolve(
            db,
            task,
            actor,
            plan["id"],
            plan["version"],
            api["id"],
            "shared.txt",
            "edit",
            detail["versions"]["result"]["text"],
        )
    plan = service.resolve(db, task, actor, plan["id"], plan["version"], api["id"], "shared.txt", "edit", "reviewed\n")
    plan = service.resolve(db, task, actor, plan["id"], plan["version"], web["id"], "delete.txt", "task")
    db.commit()
    apply(env, plan)
    assert (root / "api" / "shared.txt").read_text() == "reviewed\n"
    assert not (root / "web" / "delete.txt").exists()


def test_stale_preview_and_ignored_collision_do_not_write(env):
    _, _, root, remotes, _ = env
    write(remotes["api"], "new.txt", "upstream\n")
    commit(remotes["api"])
    plan = prepare(env)
    write(root / "web", "later.txt", "new task edit\n")
    with pytest.raises(git.UpdateError, match="预览后发生变化"):
        apply(env, plan)
    assert not (root / "api" / "new.txt").exists()


def test_second_repository_failure_restores_both_worktrees(env, monkeypatch):
    _, task, root, remotes, _ = env
    for name, remote in remotes.items():
        write(remote, "new.txt", "remote\n")
        commit(remote)
        write(root / name, "task.txt", "preserved\n")
    heads = {name: git.git(root / name, "rev-parse", "HEAD") for name in remotes}
    plan = prepare(env)
    install, calls = git.install, []

    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("simulated second repository failure")
        install(*args)

    monkeypatch.setattr(git, "install", fail_second)
    with pytest.raises(git.UpdateError, match="全部仓库已恢复"):
        apply(env, plan)
    for name in remotes:
        assert git.git(root / name, "rev-parse", "HEAD") == heads[name]
        assert not (root / name / "new.txt").exists()
        assert (root / name / "task.txt").read_text() == "preserved\n"
    assert task.session_generation == 1


def test_binary_conflict_whole_side_and_review_version_fence(env):
    db, task, root, remotes, actor = env
    write(root / "api", "binary.bin", b"\0task")
    write(remotes["api"], "binary.bin", b"\0remote")
    commit(remotes["api"])
    plan = prepare(env)
    repo = next(r for r in plan["repositories"] if r["name"] == "api")
    detail = service.file_detail(task, plan["id"], repo["id"], "binary.bin")
    assert detail["versions"]["task"]["binary"]
    with pytest.raises(git.UpdateError, match="只能选择完整版本"):
        service.resolve(db, task, actor, plan["id"], plan["version"], repo["id"], "binary.bin", "edit", "corrupted")
    old = plan["version"]
    plan = service.resolve(db, task, actor, plan["id"], old, repo["id"], "binary.bin", "remote")
    with pytest.raises(git.UpdateError, match="其他用户"):
        service.resolve(db, task, actor, plan["id"], old, repo["id"], "binary.bin", "task")
    db.commit()
    apply(env, plan)
    assert (root / "api" / "binary.bin").read_bytes() == b"\0remote"


def test_no_task_output_updates_clean_head_and_collaboration_baseline(env):
    from app.domains.workspace_collaboration.service import repository_metadata

    db, task, root, remotes, _ = env
    write(remotes["api"], "upstream.txt", "new\n")
    target = commit(remotes["api"])
    plan = prepare(env)
    assert not any(repo["has_output"] for repo in plan["repositories"])
    apply(env, plan)
    assert git.git(root / "api", "status", "--porcelain") == ""
    assert (
        next(repo for repo in repository_metadata(db, task) if repo["repo_slug"] == "api")["base_commit_sha"] == target
    )


def test_new_remote_file_does_not_overwrite_ignored_cloud_file(env):
    _, _, root, remotes, _ = env
    # Repository-local exclude rules are metadata, not task output.
    write(root / "api", ".git/info/exclude", "secret.txt\n")
    write(root / "api", "secret.txt", "do not overwrite\n")
    write(remotes["api"], "secret.txt", "remote\n")
    commit(remotes["api"])
    plan = prepare(env)
    with pytest.raises(git.UpdateError, match="未纳管文件重名"):
        apply(env, plan)
    assert (root / "api" / "secret.txt").read_text() == "do not overwrite\n"


def test_agent_adaptation_is_reviewed_before_replacing_original(env):
    from pathlib import Path

    from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
    from app.domains.task.services.repository_updates import adaptation

    db, task, root, remotes, actor = env
    write(root / "api", "shared.txt", "old task implementation\n")
    write(remotes["api"], "shared.txt", "new architecture\n")
    commit(remotes["api"])
    plan = prepare(env)
    plan = adaptation.create(db, task, actor, plan["id"], plan["version"], "保留任务目标并适配新架构")
    db.commit()
    assert plan["state"] == "ADAPTING"
    from app.domains.workspace_collaboration.service import CollaborationError, _assert_no_writer

    _assert_no_writer(db, task.id, read_only=True)
    with pytest.raises(CollaborationError, match="任务代码正在更新"):
        _assert_no_writer(db, task.id)
    with pytest.raises(git.UpdateError, match="任务代码正在更新"):
        storage.require_available(task)
    job = db.get(SddAiJob, plan["job_id"])
    candidate = Path(job.context_json["candidate_root"])
    assert candidate.is_relative_to(Path(settings.TASK_SESSION_SNAPSHOT_ROOT))
    assert (candidate / "api" / "shared.txt").read_text() == "new architecture\n"
    write(candidate / "api", "shared.txt", "new architecture with task feature\n")
    job.status, job.result_json = AiJobStatus.SUCCESS, {"text": "verification report"}
    db.commit()
    adaptation.settle(db, job.id)
    db.commit()
    assert (root / "api" / "shared.txt").read_text() == "old task implementation\n"
    plan = service.summary(db, task)["plan"]
    assert plan["state"] == "READY"
    assert plan["agent_summary"] == "verification report"
    assert next(repo for repo in plan["repositories"] if repo["name"] == "api")["mode"] == "ADAPTED"
    apply(env, plan)
    assert (root / "api" / "shared.txt").read_text() == "new architecture with task feature\n"


def test_failed_apply_fences_new_messages_until_recovery(env, monkeypatch):
    from app.domains.task.services.chat_submission_service import SubmissionError, assert_no_preparing_submission

    db, task, root, remotes, actor = env
    write(remotes["api"], "new.txt", "remote\n")
    commit(remotes["api"])
    plan = prepare(env)
    restore = service.snapshots._restore_worktree_sync
    with monkeypatch.context() as patch:
        patch.setattr(git, "install", lambda *args: (_ for _ in ()).throw(OSError("failed install")))
        patch.setattr(
            service.snapshots, "_restore_worktree_sync", lambda *args: (_ for _ in ()).throw(OSError("failed restore"))
        )
        with pytest.raises(git.UpdateError, match="应用中断"):
            apply(env, plan)
    assert storage.load(task)["state"] == "RECOVERY_REQUIRED"
    with pytest.raises(SubmissionError, match="任务代码正在更新"):
        assert_no_preparing_submission(db, task.id)
    plan = storage.load(task)
    assert service.snapshots._restore_worktree_sync is restore
    service.recover(db, task, actor, plan["id"], plan["version"])
    db.commit()
    assert storage.load(task)["state"] == "READY"
    assert_no_preparing_submission(db, task.id)
    assert not (root / "api" / "new.txt").exists()


def test_discard_publishes_to_other_reviewers_and_preserves_original(env):
    from app.domains.task.models.task_event_outbox import TaskEventOutbox

    db, task, root, _, actor = env
    write(root / "api", "shared.txt", "keep task output\n")
    plan = prepare(env)
    candidate = storage.directory(task, plan["id"])
    generation = task.session_generation
    with pytest.raises(git.UpdateError, match="无需更新任务基线"):
        apply(env, plan)
    assert task.session_generation == generation
    service.discard(db, task, actor, plan["id"], plan["version"])
    assert storage.load(task) is None
    assert not candidate.exists()
    assert (root / "api" / "shared.txt").read_text() == "keep task output\n"
    events = [row.payload_json for row in db.query(TaskEventOutbox).filter_by(task_id=task.id).all()]
    assert any(event.get("state") == "DISCARDED" and event["id"] == plan["id"] for event in events)
