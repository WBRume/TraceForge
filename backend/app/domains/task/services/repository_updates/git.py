"""Git owns discovery, three-way merging and conflict stages.

The source index/HEAD are never changed while preparing a candidate. Each
candidate is an independent clone; no linked worktree shares mutable refs.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath

from app.core.subprocess_runner import GIT_REPOSITORY_ENV_VARS, run_git


class UpdateError(ValueError):
    def __init__(self, message: str, code: str = "REPOSITORY_UPDATE_FAILED"):
        super().__init__(message)
        self.code = code
        self.status_code = 409


def command(root: Path, *args: str, data: bytes | None = None, env=None, allowed=(0,)):
    result = run_git(
        [
            "-c",
            "core.longpaths=true",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "user.name=TraceForge",
            "-c",
            "user.email=traceforge@localhost",
            *args,
        ],
        cwd=str(root),
        timeout_seconds=120,
        decode_text=False,
        input_data=data,
        env_extra=env,
        unset_env=GIT_REPOSITORY_ENV_VARS,
    )
    if result.returncode not in allowed:
        # Git output can include credential-bearing remote URLs. Keep API errors
        # actionable without reflecting them or the entire local command line.
        raise UpdateError(f"Git {args[0]} 执行失败（退出码 {result.returncode}），请检查远端访问权限和仓库状态。")
    return result


def git(root: Path, *args: str, **kwargs) -> str:
    return command(root, *args, **kwargs).stdout.decode("utf-8").strip()


def safe_file(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or "\\" in relative
        or ":" in relative
        or relative.startswith("/")
        or any(p in {"", ".", ".."} or p.casefold() == ".git" for p in parts)
    ):
        raise UpdateError("无效的仓库文件路径", "INVALID_PATH")
    path = root.joinpath(*parts)
    # The leaf may be a versioned symlink, but its parents must stay in the repo.
    if not path.parent.resolve().is_relative_to(root.resolve()):
        raise UpdateError("文件路径越过仓库边界", "INVALID_PATH")
    return path


def tree(root: Path) -> str:
    """Include committed, staged, unstaged and untracked, non-ignored output."""
    with tempfile.TemporaryDirectory(prefix="traceforge-update-index-") as directory:
        env = {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        git(root, "read-tree", "HEAD", env=env)
        git(root, "add", "-A", "--", ".", env=env)
        return git(root, "write-tree", env=env)


def entries(root: Path, revision: str) -> dict[str, dict]:
    result = {}
    for record in command(root, "ls-tree", "-r", "-z", revision).stdout.split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        result[path.decode("utf-8")] = {"mode": mode, "kind": kind, "oid": oid}
    return result


def conflicts(root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for record in command(root, "ls-files", "-u", "-z").stdout.split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, oid, stage = header.decode().split()
        # The staging checkout starts at remote; MERGE_HEAD is task output.
        side = {"1": "base", "2": "remote", "3": "task"}[stage]
        result.setdefault(path.decode("utf-8"), {})[side] = {"mode": mode, "oid": oid, "kind": "blob"}
    return result


def fetch_target(root: Path, url: str, branch: str) -> str:
    if not url or url.startswith("-") or not branch or branch.startswith("-"):
        raise UpdateError("任务未配置有效的远端仓库和分支")
    ref = branch if branch.startswith("refs/heads/") else f"refs/heads/{branch}"
    git(root, "check-ref-format", ref)
    git(root, "fetch", "--no-tags", "--no-recurse-submodules", "--", url, f"+{ref}:refs/traceforge/remote")
    return git(root, "rev-parse", "refs/traceforge/remote^{commit}")


def prepare(source: Path, destination: Path, *, url: str, branch: str, baseline: str) -> dict:
    head, source_tree = git(source, "rev-parse", "HEAD"), tree(source)
    # A synthetic child of the actual HEAD retains the full task history for
    # merge-base selection, including commits made by the Agent.
    commit = git(source, "commit-tree", source_tree, "-p", head, data=b"TraceForge task output\n")
    destination.parent.mkdir(parents=True, exist_ok=True)
    git(source, "clone", "--no-hardlinks", "--no-checkout", "--", str(source), str(destination))
    git(destination, "config", "core.longpaths", "true")
    git(destination, "fetch", "--no-tags", str(source), commit)
    target = fetch_target(destination, url, branch)
    if any(entry["mode"] == "160000" for entry in entries(destination, commit).values()) or any(
        entry["mode"] == "160000" for entry in entries(destination, target).values()
    ):
        raise UpdateError("包含 Git 子模块的仓库暂不支持任务代码更新，请先在 Git 中完成整合。", "SUBMODULE_UNSUPPORTED")
    base_result = command(destination, "merge-base", commit, target, allowed=(0, 1))
    if not base_result.stdout.strip():
        raise UpdateError("远端与任务没有共同 Git 基线，请检查任务绑定的分支和仓库。", "NO_COMMON_BASE")
    base = base_result.stdout.decode().strip()
    git(destination, "checkout", "--detach", target)
    result = command(destination, "merge", "--no-commit", "--no-ff", commit, allowed=(0, 1))
    unresolved = conflicts(destination)
    if result.returncode and not unresolved:
        raise UpdateError("Git 无法生成合并结果，原任务代码保持不变。")
    # Pin all inputs, even when the merge has no changes and Git drops MERGE_HEAD.
    git(destination, "update-ref", "refs/traceforge/task", commit)
    git(destination, "update-ref", "refs/traceforge/base", base)
    return {
        "source_head": head,
        "source_tree": source_tree,
        "task_commit": commit,
        "target": target,
        "base": base,
        "baseline": baseline,
        "has_output": source_tree != git(source, "rev-parse", f"{baseline}^{{tree}}"),
        "conflicts": unresolved,
        "resolved": [],
        "mode": "MERGE",
    }


def file_list(root: Path, repo: dict) -> list[dict]:
    sides = {
        name: entries(root, repo[ref])
        for name, ref in (
            ("base", "base"),
            ("task", "task_commit"),
            ("remote", "target"),
        )
    }
    pending = conflicts(root)
    current = {}
    for record in command(root, "ls-files", "-s", "-z").stdout.split(b"\0"):
        if record:
            header, path = record.split(b"\t", 1)
            mode, oid, stage = header.decode().split()
            if stage == "0":
                current[path.decode()] = {"mode": mode, "oid": oid, "kind": "commit" if mode == "160000" else "blob"}
    sides["result"] = current
    paths = sorted(set().union(*(set(v) for v in sides.values()), repo["conflicts"], pending))
    result = []
    for path in paths:
        versions = {side: items.get(path) for side, items in sides.items()}
        # Conflict stages capture rename/delete locations more accurately than
        # looking up the common tree using the current filename alone.
        for side, entry in repo["conflicts"].get(path, {}).items():
            versions[side] = entry
        if path not in repo["conflicts"] and all(v == versions["base"] for v in versions.values()):
            continue
        result.append(
            {
                "path": path,
                "conflict": path in pending,
                "was_conflict": path in repo["conflicts"],
                "resolved": path in repo["resolved"],
                "versions": versions,
            }
        )
    return sorted(result, key=lambda file: (not file["conflict"], file["path"]))


def read_blob(root: Path, entry: dict | None) -> dict:
    if entry is None:
        return {"exists": False, "text": "", "binary": False, "mode": None}
    if entry["mode"] == "160000":
        return {"exists": True, "text": entry["oid"], "binary": True, "mode": entry["mode"]}
    size = int(git(root, "cat-file", "-s", entry["oid"]))
    if size > 2 * 1024 * 1024:
        return {"exists": True, "text": "", "binary": True, "mode": entry["mode"]}
    data = command(root, "cat-file", "blob", entry["oid"]).stdout
    try:
        text = data.decode("utf-8")
        binary = b"\0" in data
    except UnicodeDecodeError:
        text, binary = "", True
    return {"exists": True, "text": "" if binary else text, "binary": binary, "mode": entry["mode"]}


def resolve(root: Path, repo: dict, path: str, choice: str, text: str | None):
    known = next((f for f in file_list(root, repo) if f["path"] == path), None)
    if not known or not known["was_conflict"]:
        raise UpdateError("文件不在冲突清单中，请刷新后重试。")
    destination = safe_file(root, path)
    entry = known["versions"].get(choice)
    if choice == "edit":
        if text is None or any(
            v and (v["mode"] in {"120000", "160000"} or read_blob(root, v)["binary"])
            for v in known["versions"].values()
        ):
            raise UpdateError("此文件只能选择完整版本，不能编辑文本。")
        if re.search(r"^<<<<<<< .+", text, re.MULTILINE) and re.search(r"^>>>>>>> .+", text, re.MULTILINE):
            raise UpdateError("请先处理合并结果中的 Git 冲突标记，再确认此文件。")
        oid = git(root, "hash-object", "-w", "--stdin", data=text.encode())
        entry = {
            "mode": (known["versions"]["task"] or known["versions"]["remote"] or {}).get("mode", "100644"),
            "oid": oid,
        }
    if destination.is_dir() and not destination.is_symlink():
        raise UpdateError("文件与目录发生冲突，请先处理目录中的冲突文件。")
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    git(root, "update-index", "--force-remove", "--", path)
    if entry:
        git(root, "update-index", "--add", "--cacheinfo", entry["mode"], entry["oid"], path)
        git(root, "checkout-index", "-f", "--", path)
    if path not in repo["resolved"]:
        repo["resolved"].append(path)


def finish_candidate(root: Path, repo: dict) -> str:
    if conflicts(root):
        raise UpdateError("请先处理全部仓库的冲突。", "CONFLICTS_REMAIN")
    result_tree = git(root, "write-tree")
    commit = git(root, "commit-tree", result_tree, "-p", repo["target"], data=b"TraceForge reviewed candidate\n")
    git(root, "update-ref", "refs/traceforge/result", commit)
    return commit


def install(source: Path, staging: Path, repo: dict, candidate: str):
    # Preflight verified the complete input tree before any repo is changed.
    # A checkpoint covers compensation; hidden refs retain committed history.
    git(source, "fetch", "--no-tags", str(staging), candidate)
    git(source, "update-ref", f"refs/traceforge/updates/{candidate}/before", repo["source_head"])
    git(source, "update-ref", f"refs/traceforge/updates/{candidate}/result", candidate)
    git(source, "read-tree", "--reset", "-u", candidate)
    git(source, "update-ref", "HEAD", repo["target"], repo["source_head"])
    git(source, "read-tree", repo["target"])
