"""
GitHub import helpers for skill package onboarding.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, List
from urllib.parse import urlparse

import yaml

from app.config import settings


class GithubImportError(ValueError):
    pass


@dataclass(frozen=True)
class GithubRepoRef:
    owner: str
    repo: str
    clone_url: str

    @property
    def public_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


_GITHUB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_FRONTMATTER_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)


def parse_public_repo_url(repo_url: str) -> GithubRepoRef:
    raw_url = str(repo_url or "").strip()
    if not raw_url:
        raise GithubImportError("repo_url is required")

    parsed = urlparse(raw_url)
    if parsed.scheme.lower() != "https":
        raise GithubImportError("Only HTTPS GitHub URLs are supported")
    if parsed.netloc.lower() != "github.com":
        raise GithubImportError("Only github.com public repositories are supported in v1")
    if parsed.query or parsed.fragment:
        raise GithubImportError("GitHub repository URL must not contain query or fragment")

    path = str(parsed.path or "").strip("/")
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) != 2:
        raise GithubImportError("GitHub repository URL must be https://github.com/<owner>/<repo>")

    owner = segments[0].strip()
    repo = segments[1].strip()
    if repo.lower().endswith(".git"):
        repo = repo[:-4].strip()

    if not owner or not repo:
        raise GithubImportError("GitHub repository owner and repo are required")

    if not _GITHUB_NAME_PATTERN.fullmatch(owner) or not _GITHUB_NAME_PATTERN.fullmatch(repo):
        raise GithubImportError("GitHub repository URL contains invalid owner/repo name")

    clone_url = f"https://github.com/{owner}/{repo}.git"
    return GithubRepoRef(owner=owner, repo=repo, clone_url=clone_url)


def _git_timeout_seconds() -> int:
    return max(1, int(getattr(settings, "SKILL_GITHUB_IMPORT_GIT_TIMEOUT_SECONDS", 240) or 240))


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_ASKPASS": "echo",
            "SSH_ASKPASS": "echo",
        }
    )
    return env


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        process.kill()


def _run_git_checked(args: List[str], *, cwd: str | None = None) -> str:
    command = ["git", *args]
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_env(),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError as exc:
        raise GithubImportError("Git executable not found in PATH") from exc

    try:
        stdout, stderr = process.communicate(timeout=_git_timeout_seconds())
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        raise GithubImportError(f"Git command timed out: git {' '.join(args)}") from exc

    if process.returncode != 0:
        message = (stderr or "").strip() or (stdout or "").strip() or f"exit code {process.returncode}"
        raise GithubImportError(f"Git command failed: git {' '.join(args)} | {message}")

    return (stdout or "").strip()


@contextmanager
def cloned_public_repo(
    repo_url: str,
    *,
    skill_name: str | None = None,
    source_subdir: str | None = None,
) -> Iterator[str]:
    repo_ref = parse_public_repo_url(repo_url)
    with tempfile.TemporaryDirectory(prefix="sdd_skill_import_") as temp_dir:
        repo_root = os.path.join(temp_dir, "repo")
        try:
            if skill_name:
                _sparse_checkout_skill_dir(
                    repo_ref=repo_ref,
                    repo_root=repo_root,
                    skill_name=skill_name,
                    source_subdir=source_subdir,
                )
            else:
                _run_git_checked(["clone", "--depth", "1", repo_ref.clone_url, repo_root])
        except GithubImportError as exc:
            raise GithubImportError(
                f"Failed to clone GitHub repository '{repo_ref.owner}/{repo_ref.repo}'. "
                "Ensure the repository is public and accessible."
            ) from exc
        yield repo_root


def get_repo_head_commit(repo_root: str) -> str | None:
    repo_abs = os.path.abspath(str(repo_root or "").strip())
    if not repo_abs or not os.path.isdir(repo_abs):
        return None
    try:
        return _run_git_checked(["rev-parse", "HEAD"], cwd=repo_abs)
    except GithubImportError:
        return None


def _has_root_skill_md(path: str) -> bool:
    candidate = os.path.join(path, "SKILL.md")
    return os.path.isfile(candidate)


def _normalize_skill_name(skill_name: str) -> str:
    normalized = str(skill_name or "").strip()
    if not normalized:
        raise GithubImportError("skill_name is required")
    if "/" in normalized or "\\" in normalized:
        raise GithubImportError("skill_name must be a directory name, not a path")
    return normalized


def _normalize_repo_relative_dir(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        raise GithubImportError("source_subdir is required")
    parts = [part for part in normalized.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise GithubImportError("source_subdir must stay inside the GitHub repository")
    return "/".join(parts)


def _repo_path_exists(repo_root: str, relative_path: str) -> bool:
    rel = str(relative_path or "").strip().replace("\\", "/").strip("/")
    if not rel:
        return False
    try:
        _run_git_checked(["cat-file", "-e", f"HEAD:{rel}"], cwd=repo_root)
        return True
    except GithubImportError:
        return False


def _repo_dir_has_skill_md(repo_root: str, relative_dir: str) -> bool:
    rel_dir = _normalize_repo_relative_dir(relative_dir)
    return _repo_path_exists(repo_root, f"{rel_dir}/SKILL.md")


def _resolve_sparse_skill_subdir(
    repo_root: str,
    *,
    skill_name: str,
    source_subdir: str | None = None,
) -> str:
    if source_subdir:
        normalized_subdir = _normalize_repo_relative_dir(source_subdir)
        if not _repo_dir_has_skill_md(repo_root, normalized_subdir):
            raise GithubImportError(f"GitHub source directory is missing root SKILL.md: {normalized_subdir}")
        return normalized_subdir

    target_name = _normalize_skill_name(skill_name)
    missing_skill_md_matches: List[str] = []
    preferred_candidates = [f"skills/{target_name}", target_name]
    for candidate in preferred_candidates:
        if _repo_dir_has_skill_md(repo_root, candidate):
            return candidate
        if _repo_path_exists(repo_root, candidate):
            missing_skill_md_matches.append(candidate)

    try:
        raw_dirs = _run_git_checked(["ls-tree", "-d", "-r", "--name-only", "HEAD"], cwd=repo_root)
    except GithubImportError as exc:
        raise GithubImportError("Failed to inspect GitHub repository tree") from exc

    recursive_matches: List[str] = []
    seen = set()
    for line in raw_dirs.splitlines():
        rel_dir = line.strip().replace("\\", "/").strip("/")
        if not rel_dir:
            continue
        if rel_dir in seen:
            continue
        seen.add(rel_dir)
        if rel_dir.split("/")[-1] == target_name:
            recursive_matches.append(rel_dir)

    valid_candidates: List[str] = []
    for item in recursive_matches:
        if item in preferred_candidates:
            continue
        if _repo_dir_has_skill_md(repo_root, item):
            valid_candidates.append(item)
        else:
            missing_skill_md_matches.append(item)

    if len(valid_candidates) == 1:
        return valid_candidates[0]
    if len(valid_candidates) > 1:
        raise GithubImportError(
            f"Multiple skill directories matched '{target_name}': {', '.join(valid_candidates)}"
        )

    if missing_skill_md_matches:
        rel_missing = sorted(list(dict.fromkeys(missing_skill_md_matches)))
        raise GithubImportError(
            f"Found matching directory but missing root SKILL.md: {', '.join(rel_missing)}"
        )

    raise GithubImportError(f"Skill directory '{target_name}' not found in repository")


def _sparse_checkout_skill_dir(
    *,
    repo_ref: GithubRepoRef,
    repo_root: str,
    skill_name: str,
    source_subdir: str | None = None,
) -> str:
    _run_git_checked(
        [
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            "--no-checkout",
            repo_ref.clone_url,
            repo_root,
        ]
    )
    relative_source = _resolve_sparse_skill_subdir(
        repo_root,
        skill_name=skill_name,
        source_subdir=source_subdir,
    )
    _run_git_checked(["sparse-checkout", "init", "--cone"], cwd=repo_root)
    _run_git_checked(["sparse-checkout", "set", relative_source], cwd=repo_root)
    _run_git_checked(["checkout", "--force", "HEAD"], cwd=repo_root)

    checked_out_dir = os.path.join(repo_root, *relative_source.split("/"))
    if not _has_root_skill_md(checked_out_dir):
        raise GithubImportError(f"Checked out skill directory is missing root SKILL.md: {relative_source}")
    return relative_source


def locate_skill_directory(repo_root: str, skill_name: str) -> str:
    repo_abs = os.path.abspath(str(repo_root or "").strip())
    if not repo_abs or not os.path.isdir(repo_abs):
        raise GithubImportError("Repository root does not exist")

    target_name = _normalize_skill_name(skill_name)
    missing_skill_md_matches: List[str] = []

    preferred_candidates = [
        os.path.join(repo_abs, "skills", target_name),
        os.path.join(repo_abs, target_name),
    ]
    for candidate in preferred_candidates:
        if not os.path.isdir(candidate):
            continue
        if _has_root_skill_md(candidate):
            return os.path.abspath(candidate)
        missing_skill_md_matches.append(os.path.abspath(candidate))

    recursive_matches: List[str] = []
    for walk_root, dir_names, _ in os.walk(repo_abs, topdown=True, followlinks=False):
        filtered_dirs: List[str] = []
        for dir_name in dir_names:
            abs_dir = os.path.join(walk_root, dir_name)
            if dir_name == ".git":
                continue
            if os.path.islink(abs_dir):
                continue
            filtered_dirs.append(dir_name)
            if dir_name == target_name:
                recursive_matches.append(os.path.abspath(abs_dir))
        dir_names[:] = filtered_dirs

    unique_matches: List[str] = []
    seen = set()
    for item in recursive_matches:
        if item in seen:
            continue
        seen.add(item)
        unique_matches.append(item)

    valid_candidates = [item for item in unique_matches if _has_root_skill_md(item)]
    for item in unique_matches:
        if item not in valid_candidates:
            missing_skill_md_matches.append(item)

    if len(valid_candidates) == 1:
        return valid_candidates[0]
    if len(valid_candidates) > 1:
        relative_paths = [
            os.path.relpath(item, repo_abs).replace("\\", "/")
            for item in valid_candidates
        ]
        raise GithubImportError(
            f"Multiple skill directories matched '{target_name}': {', '.join(relative_paths)}"
        )

    if missing_skill_md_matches:
        rel_missing = [
            os.path.relpath(item, repo_abs).replace("\\", "/")
            for item in missing_skill_md_matches
        ]
        rel_missing = sorted(list(dict.fromkeys(rel_missing)))
        raise GithubImportError(
            f"Found matching directory but missing root SKILL.md: {', '.join(rel_missing)}"
        )

    raise GithubImportError(f"Skill directory '{target_name}' not found in repository")


def resolve_skill_directory(
    repo_root: str,
    *,
    skill_name: str,
    source_subdir: str | None = None,
) -> str:
    repo_abs = os.path.abspath(str(repo_root or "").strip())
    if not repo_abs or not os.path.isdir(repo_abs):
        raise GithubImportError("Repository root does not exist")

    normalized_subdir = str(source_subdir or "").replace("\\", "/").strip().strip("/")
    if normalized_subdir:
        if normalized_subdir.startswith("../") or "/../" in normalized_subdir or normalized_subdir == "..":
            raise GithubImportError("Stored GitHub skill source path is invalid")
        candidate = os.path.abspath(os.path.join(repo_abs, *normalized_subdir.split("/")))
        if os.path.commonpath([repo_abs, candidate]) != repo_abs:
            raise GithubImportError("Stored GitHub skill source path escapes repository root")
        if os.path.isdir(candidate) and _has_root_skill_md(candidate):
            return candidate

    return locate_skill_directory(repo_abs, skill_name)


def read_skill_description(skill_dir: str) -> str | None:
    skill_root = os.path.abspath(str(skill_dir or "").strip())
    if not skill_root:
        return None
    markdown_path = os.path.join(skill_root, "SKILL.md")
    if not os.path.isfile(markdown_path):
        return None

    try:
        with open(markdown_path, "r", encoding="utf-8", errors="replace") as file:
            content = file.read()
    except Exception:
        return None

    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        return None

    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

    if not isinstance(metadata, dict):
        return None
    description = metadata.get("description")
    if description is None:
        return None
    normalized = str(description).strip()
    return normalized or None
