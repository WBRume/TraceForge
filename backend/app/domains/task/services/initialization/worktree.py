"""Incremental Git checkout and output cleanup; no clone or compensation copy."""

import shutil
import time
from hashlib import sha256
from pathlib import Path

from app.domains.task.services.repository_updates import git

from .state import InitializationError


def repository_root(task_root, relative):
    root = Path(task_root).resolve()
    if root.parent == root or not root.is_dir():
        raise InitializationError("任务目录不存在或路径无效。")
    candidate = root if relative == "." else git.safe_file(root, relative)
    if candidate.is_symlink() or candidate.resolve() != candidate.absolute():
        raise InitializationError("任务仓库不能通过符号链接越过目录边界。")
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root) or not candidate.is_dir():
        raise InitializationError("任务仓库目录不可用。")
    actual = Path(git.git(candidate, "rev-parse", "--show-toplevel")).resolve()
    if actual != candidate:
        raise InitializationError("任务仓库路径与 Git 工作树不一致。")
    return candidate


def fetch(task_root, repo):
    root = repository_root(task_root, repo["rel_path"])
    started = time.monotonic()
    branch = "refs/heads/" + repo["branch"].removeprefix("refs/heads/")
    git.git(root, "check-ref-format", branch)
    ref = "refs/traceforge/initialize/" + sha256(str(root).encode()).hexdigest()
    git.git(root, "fetch", "--no-tags", "--no-recurse-submodules", "--", repo["url"], f"+{branch}:{ref}")
    target = git.git(root, "rev-parse", ref + "^{commit}")
    # Submodules are separate worktrees and cannot be silently left at old heads.
    if any(item["mode"] == "160000" for item in git.entries(root, target).values()):
        raise InitializationError("包含子模块的仓库暂不支持初始化重置。")
    return {"target": target, "fetch_seconds": round(time.monotonic() - started, 3)}


def reset(task_root, repo):
    root = repository_root(task_root, repo["rel_path"])
    started = time.monotonic()
    target = repo["target"]
    if git.git(root, "rev-parse", "--verify", target + "^{commit}") != target:
        raise InitializationError("已固定的远端提交不可用。")
    # reset updates changed paths using the existing index/object database.
    # clean also removes ignored build output and generated nested repositories.
    git.git(root, "reset", "--hard", target)
    git.git(root, "clean", "-ffdx", "--", ".")
    if (
        git.git(root, "rev-parse", "HEAD") != target
        or git.command(root, "status", "--porcelain", "--untracked-files=all", "--ignored").stdout
    ):
        raise InitializationError("仓库未完全恢复到远端提交，请继续初始化。")
    return {"reset_seconds": round(time.monotonic() - started, 3), "completed": True}


def clean_root(task_root, repositories, protected):
    """Delete generated root files while retaining repository roots and task inputs."""
    root = Path(task_root).resolve()
    if root.parent == root or not root.is_dir():
        raise InitializationError("任务目录无效。")
    if any(repo["rel_path"] == "." for repo in repositories):
        return
    keep = {str(name).replace("\\", "/").strip("/") for name in protected}
    keep.update(repo["rel_path"] for repo in repositories)
    keep.add(".git")
    if any(not name or name.startswith("/") or ".." in name.split("/") for name in keep):
        raise InitializationError("任务输入路径无效。")

    def visit(directory, prefix=""):
        for child in directory.iterdir():
            relative = prefix + child.name
            if relative in keep:
                continue
            parents_of_input = any(name.startswith(relative + "/") for name in keep)
            if parents_of_input:
                if child.is_symlink():
                    raise InitializationError("任务输入父目录不能是符号链接。")
                if child.is_dir():
                    visit(child, relative + "/")
                continue
            # Verify the resolved parent; unlink a leaf symlink without following it.
            if not child.parent.resolve().is_relative_to(root):
                raise InitializationError("拒绝清理任务目录外的文件。")
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)

    visit(root)
