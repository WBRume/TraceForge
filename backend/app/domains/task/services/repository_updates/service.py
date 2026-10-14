"""Preview, resolve and apply all task repositories as one recoverable operation."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.session_turn import TaskSessionOperation, TaskSessionOperationStatus
from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.task.services import task_session_snapshot_service as snapshots
from app.domains.task.services.task_attempt_recovery_service import BLOCKING
from app.domains.workspace_collaboration.models import CollaborationState

from . import git, storage
from .git import UpdateError


def repositories(db, task):
    rows = db.query(SddTaskRepository).filter_by(task_id=task.id).order_by(SddTaskRepository.id).all()
    if not rows or any(str(getattr(r.state, "value", r.state)) != "READY" or not r.base_commit_sha for r in rows):
        raise UpdateError("请先完成任务仓库准备。")
    roots = []
    for row in rows:
        root = source(task, row.rel_path)
        if any(root == old or root.is_relative_to(old) or old.is_relative_to(root) for old in roots):
            raise UpdateError("任务仓库目录重叠，无法更新。")
        roots.append(root)
    return rows


def source(task, relative):
    root = Path(task.project_path).resolve()
    result = git.safe_file(root, relative).resolve() if relative != "." else root
    if not result.is_relative_to(root) or not result.is_dir():
        raise UpdateError("任务仓库目录不存在或已越过工作区边界。")
    return result


def idle(db, task, *, ignore_job_id=None):
    if task.execution_location != "SERVER" or str(getattr(task.task_type, "value", task.task_type)) != "DEVELOPMENT":
        raise UpdateError("仅云端开发任务支持更新任务代码。")
    if str(getattr(task.status, "value", task.status)) in {"PROVISIONING", "BASELINED"}:
        raise UpdateError("当前任务状态不能更新代码。")
    query = db.query(SddAiJob.id).filter(SddAiJob.task_id == task.id, SddAiJob.status.in_(BLOCKING))
    if ignore_job_id:
        query = query.filter(SddAiJob.id != ignore_job_id)
    if query.first() or db.query(TaskChatSubmission.id).filter_by(active_task_id=task.id).first():
        raise UpdateError("请等待当前消息准备和 Agent 执行结束后更新代码。", "WRITER_ACTIVE")
    if (
        db.query(TaskSessionOperation.id)
        .filter_by(task_id=task.id, status=TaskSessionOperationStatus.REVERTING)
        .first()
    ):
        raise UpdateError("请先完成当前会话撤销。")
    state = db.get(CollaborationState, task.id)
    if state and state.enabled:
        if state.lease_expires_at > datetime.utcnow():
            raise UpdateError("请先断开本地协同，再更新任务代码；本地修改请自行提交或暂存。", "DISCONNECT_REQUIRED")
        if state.sync_phase not in {"READY", "DELIVERY_PENDING", "CONFLICT_PENDING"}:
            raise UpdateError("请先恢复尚未完成的代码交接。", "COLLABORATION_RECOVERY_REQUIRED")


def stage(task, plan, repo):
    base = storage.directory(task, plan["id"])
    root = Path(plan.get("candidate_directory") or base / "candidate").resolve()
    if not root.is_relative_to(base.resolve()):
        raise UpdateError("候选代码目录越过更新记录边界。")
    result = (root / repo["rel_path"]).resolve()
    if not result.is_relative_to(root):
        raise UpdateError("仓库目录越过候选工作区边界。")
    return result


def summary(db, task):
    rows = repositories(db, task)
    result = {
        "repositories": [
            {
                "id": r.id,
                "name": r.repo_slug,
                "branch": r.branch_name,
                "creation_baseline": r.base_commit_sha,
                "baseline": storage.baseline(task, r),
            }
            for r in rows
        ],
        "plan": None,
    }
    try:
        plan = storage.load(task)
        if plan and plan["state"] == "ADAPTING":
            from .adaptation import settle

            settle(db, plan["job_id"])
            plan = storage.load(task)
        if plan:
            result["plan"] = view(task, plan)
    except UpdateError as exc:
        pointer = (task.task_meta_json or {}).get("repository_update", {})
        result["plan"] = {**pointer, "error": str(exc), "repositories": [], "storage_missing": True}
    return result


def view(task, plan):
    result = {
        key: plan.get(key) for key in ("id", "state", "version", "error", "created_at", "job_id", "agent_summary")
    }
    result["repositories"] = []
    for repo in plan["repositories"]:
        item = {key: repo[key] for key in ("id", "name", "branch", "baseline", "base", "target", "has_output", "mode")}
        item["files"] = (
            git.file_list(stage(task, plan, repo), repo) if plan["state"] not in {"PREPARING", "FAILED"} else []
        )
        result["repositories"].append(item)
    return result


def prepare(db, task, actor_id):
    storage.require_available(task)
    idle(db, task)
    rows = repositories(db, task)
    plan = {
        "id": str(uuid4()),
        "task_id": task.id,
        "actor_id": actor_id,
        "state": "PREPARING",
        "version": 0,
        "created_at": datetime.utcnow().isoformat(),
        "session_generation": task.session_generation,
        "session_revision": task.session_revision,
        "repositories": [],
        "error": None,
    }
    storage.save(db, task, plan)
    db.commit()
    try:
        for row in rows:
            data = {
                "id": row.id,
                "name": row.repo_slug,
                "branch": row.branch_name,
                "url": row.repo_url,
                "rel_path": row.rel_path,
            }
            data.update(
                git.prepare(
                    source(task, row.rel_path),
                    stage(task, plan, data),
                    url=row.repo_url,
                    branch=row.branch_name,
                    baseline=storage.baseline(task, row),
                )
            )
            plan["repositories"].append(data)
        plan["state"] = "CONFLICTS" if any(r["conflicts"] for r in plan["repositories"]) else "READY"
    except Exception as exc:
        plan["state"], plan["error"] = (
            "FAILED",
            str(exc) if isinstance(exc, UpdateError) else "生成代码预览失败，原任务代码保持不变。",
        )
        storage.save(db, task, plan)
        db.commit()
        raise
    storage.save(db, task, plan)
    return view(task, plan)


def current(task, operation_id, version, states=("READY", "CONFLICTS")):
    plan = storage.load(task, operation_id)
    if not plan:
        raise UpdateError("请先检查远端更新。")
    storage.require_version(plan, version)
    if plan["state"] not in states:
        raise UpdateError("当前代码预览状态不允许此操作。")
    return plan


def get_repo(plan, repo_id):
    repo = next((r for r in plan["repositories"] if r["id"] == repo_id), None)
    if not repo:
        raise UpdateError("仓库不属于本次代码更新。")
    return repo


def file_detail(task, operation_id, repo_id, path):
    plan = storage.load(task, operation_id)
    repo = get_repo(plan, repo_id)
    root = stage(task, plan, repo)
    file = next((f for f in git.file_list(root, repo) if f["path"] == path), None)
    if not file:
        raise UpdateError("文件不在本次变更中。")
    versions = {key: git.read_blob(root, entry) for key, entry in file["versions"].items()}
    if file["conflict"]:
        candidate = git.safe_file(root, path)
        if candidate.is_file() and not candidate.is_symlink() and candidate.stat().st_size <= 2 * 1024 * 1024:
            try:
                text = candidate.read_bytes().decode("utf-8")
                if "\0" not in text:
                    versions["result"] = {"exists": True, "text": text, "binary": False, "mode": "100644"}
            except UnicodeDecodeError:
                pass
    return {**file, "versions": versions, "version": plan["version"]}


def resolve(db, task, actor_id, operation_id, version, repo_id, path, choice, text=None):
    plan = current(task, operation_id, version)
    repo = get_repo(plan, repo_id)
    git.resolve(stage(task, plan, repo), repo, path, choice, text)
    plan["state"] = "CONFLICTS" if any(git.conflicts(stage(task, plan, r)) for r in plan["repositories"]) else "READY"
    plan["reviewer_id"] = actor_id
    storage.save(db, task, plan)
    return view(task, plan)


def validate_source(db, task, plan):
    if (task.session_generation, task.session_revision) != (plan["session_generation"], plan["session_revision"]):
        raise UpdateError("任务会话已变化，请重新检查远端更新。", "SOURCE_CHANGED")
    rows = {r.id: r for r in repositories(db, task)}
    if set(rows) != {r["id"] for r in plan["repositories"]}:
        raise UpdateError("任务仓库绑定已变化，请重新检查。", "SOURCE_CHANGED")
    for repo in plan["repositories"]:
        row = rows[repo["id"]]
        if (row.repo_url, row.branch_name, row.rel_path, storage.baseline(task, row)) != (
            repo["url"],
            repo["branch"],
            repo["rel_path"],
            repo["baseline"],
        ):
            raise UpdateError("任务仓库绑定已变化，请重新检查。", "SOURCE_CHANGED")
        root = source(task, repo["rel_path"])
        if git.git(root, "rev-parse", "HEAD") != repo["source_head"] or git.tree(root) != repo["source_tree"]:
            raise UpdateError("任务代码在预览后发生变化，请重新检查远端更新。", "SOURCE_CHANGED")


def checkpoint(task, plan):
    from app.domains.task.services.task_snapshot_anchor import current_anchor

    paths = [r["rel_path"] for r in plan["repositories"]]
    workspace_name = getattr(task.workspace, "name", task.workspace_id)
    anchor = current_anchor(task, paths, workspace_name)
    return snapshots._create_checkpoint_sync(
        task.project_path,
        paths,
        "none",
        None,
        task.workspace_id,
        workspace_name,
        task.id,
        task.name,
        initial_checkpoint=anchor,
    )["root"]


def apply(db, task, actor_id, operation_id, version):
    previous = storage.load(task, operation_id)
    if (
        previous
        and previous["state"] == "APPLIED"
        and version in {previous["version"], previous.get("applied_from_version")}
    ):
        return view(task, previous)
    plan = current(task, operation_id, version, states=("READY", "APPLIED"))
    if plan["state"] == "APPLIED":
        return view(task, plan)
    idle(db, task)
    validate_source(db, task, plan)
    if all(repo["target"] == repo["baseline"] for repo in plan["repositories"]):
        raise UpdateError("远端分支没有新提交，无需更新任务基线。", "UP_TO_DATE")
    for repo in plan["repositories"]:
        root = stage(task, plan, repo)
        repo["candidate"] = git.finish_candidate(root, repo)
        # Ignored local build files/secrets must not be overwritten when the
        # incoming remote newly tracks a previously ignored path.
        before = git.entries(root, repo["task_commit"])
        after = git.entries(root, repo["candidate"])
        original = source(task, repo["rel_path"])
        for path in after.keys() - before.keys():
            destination = git.safe_file(original, path)
            obstructed = any(
                p.is_file() or p.is_symlink()
                for p in destination.parents
                if p != original and p.is_relative_to(original)
            )
            if destination.exists() or destination.is_symlink() or obstructed:
                raise UpdateError(f"远端新增文件与任务目录中的未纳管文件重名：{repo['name']}/{path}")
    plan["checkpoint"] = checkpoint(task, plan)
    # Snapshot creation is a read; recheck before crossing the write boundary.
    validate_source(db, task, plan)
    plan["state"], plan["applied_from_version"] = "APPLYING", version
    storage.save(db, task, plan)
    db.commit()
    try:
        for repo in plan["repositories"]:
            git.install(source(task, repo["rel_path"]), stage(task, plan, repo), repo, repo["candidate"])
        task.task_meta_json = {
            **(task.task_meta_json or {}),
            "repository_update_history": [
                *(task.task_meta_json or {}).get("repository_update_history", []),
                {
                    "id": plan["id"],
                    "checkpoint": plan["checkpoint"],
                    "applied_at": datetime.utcnow().isoformat(),
                    "repositories": [
                        {"id": r["id"], "before": r["baseline"], "after": r["target"]} for r in plan["repositories"]
                    ],
                },
            ],
            "repository_baselines": {
                **(task.task_meta_json or {}).get("repository_baselines", {}),
                **{r["id"]: r["target"] for r in plan["repositories"]},
            },
        }
        # Old provider context and undo checkpoints belong to the old baseline.
        task.session_generation = int(task.session_generation or 0) + 1
        task.session_revision = int(task.session_revision or 0) + 1
        task.session_id = None
        state = db.get(CollaborationState, task.id)
        if state:
            from app.domains.workspace_collaboration.service import _bump

            state.enabled = False
            state.lease_epoch += 1
            state.lease_expires_at = datetime.utcnow()
            state.binding_id = str(uuid4())
            state.sync_phase = "READY"
            state.snapshot_id = state.input_snapshot_id = state.progress_snapshot_id = None
            _bump(state)
        plan["state"], plan["applied_by"] = "APPLIED", actor_id
        storage.save(db, task, plan)
        db.commit()
    except Exception:
        db.rollback()
        try:
            snapshots._restore_worktree_sync(
                plan["checkpoint"], task.project_path, str(storage.directory(task, plan["id"]) / "compensation")
            )
            plan["state"], plan["error"] = "READY", "应用失败，全部仓库已恢复到更新前；可检查后重试。"
        except Exception:
            plan["state"], plan["error"] = "RECOVERY_REQUIRED", "应用中断，请恢复更新前代码后继续。"
        storage.save(db, task, plan)
        db.commit()
        raise UpdateError(plan["error"]) from None
    return view(task, plan)


def recover(db, task, actor_id, operation_id, version):
    plan = current(task, operation_id, version, states=("APPLYING", "RECOVERY_REQUIRED"))
    idle(db, task)
    if not plan.get("checkpoint"):
        raise UpdateError("恢复快照不存在，无法自动恢复。")
    snapshots._restore_worktree_sync(
        plan["checkpoint"], task.project_path, str(storage.directory(task, plan["id"]) / f"recovery-{uuid4()}")
    )
    plan["state"], plan["error"] = "READY", None
    storage.save(db, task, plan)
    return view(task, plan)


def discard(db, task, actor_id, operation_id, version):
    pointer = (task.task_meta_json or {}).get("repository_update") or {}
    if pointer.get("id") != operation_id or pointer.get("version") != version:
        raise UpdateError("代码更新记录已变化，请刷新后重试。", "UPDATE_CHANGED")
    if pointer["state"] in {"APPLYING", "RECOVERY_REQUIRED", "ADAPTING"}:
        raise UpdateError("请先完成执行或恢复，不能丢弃此记录。")
    # PREPARING can be abandoned after a process crash: the route holds the
    # task lock, and preparation never writes the source worktree.
    task.task_meta_json = {**(task.task_meta_json or {}), "repository_update": None}
    storage.publish(db, task, {"id": operation_id, "state": "DISCARDED", "version": version + 1})
    db.commit()
    if pointer["state"] != "APPLIED":
        import shutil

        from app.config import settings

        root = Path(settings.TASK_SESSION_SNAPSHOT_ROOT).resolve()
        target = storage.directory(task, operation_id).resolve()
        allowed = root / "repository-updates" / task.id
        if target.parent != allowed or target.name != operation_id:
            raise UpdateError("拒绝清理越过快照存储范围的目录。")
        if target.exists():
            shutil.rmtree(target)
    return {"discarded": True}
