import os
import subprocess
import sys
import tempfile
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.services.skill.github_import_service import (  # noqa: E402
    GithubImportError,
    _run_git_checked,
    _resolve_sparse_skill_subdir,
    locate_skill_directory,
    parse_public_repo_url,
    read_skill_description,
)
from app.domains.skill.services.skill import github_import_service  # noqa: E402


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


class GithubImportUrlTest(unittest.TestCase):
    def test_parse_public_repo_url_accepts_https_github_repo(self):
        parsed = parse_public_repo_url("https://github.com/openai/skills-repo")
        self.assertEqual(parsed.owner, "openai")
        self.assertEqual(parsed.repo, "skills-repo")
        self.assertEqual(parsed.clone_url, "https://github.com/openai/skills-repo.git")

        parsed_git = parse_public_repo_url("https://github.com/openai/skills-repo.git/")
        self.assertEqual(parsed_git.owner, "openai")
        self.assertEqual(parsed_git.repo, "skills-repo")
        self.assertEqual(parsed_git.clone_url, "https://github.com/openai/skills-repo.git")

    def test_parse_public_repo_url_rejects_invalid_inputs(self):
        invalid_urls = [
            "",
            "http://github.com/openai/skills-repo",
            "git@github.com:openai/skills-repo.git",
            "https://github.enterprise.local/openai/skills-repo",
            "https://github.com/openai",
            "https://github.com/openai/skills-repo/tree/main",
            "https://github.com/openai/skills-repo?tab=readme",
            "https://github.com/openai/skills-repo#readme",
        ]
        for raw_url in invalid_urls:
            with self.assertRaises(GithubImportError):
                parse_public_repo_url(raw_url)


class GithubImportGitCommandTest(unittest.TestCase):
    def test_run_git_checked_terminates_process_tree_on_timeout(self):
        class FakeProcess:
            pid = 12345
            returncode = None

            def __init__(self):
                self.communicate_calls = 0

            def poll(self):
                return None

            def communicate(self, timeout=None):
                self.communicate_calls += 1
                if self.communicate_calls == 1:
                    raise subprocess.TimeoutExpired(["git", "clone"], timeout)
                self.returncode = -9
                return "", ""

        fake_process = FakeProcess()
        terminated = []

        def _fake_popen(*_args, **_kwargs):
            return fake_process

        original_popen = github_import_service.subprocess.Popen
        original_timeout = github_import_service._git_timeout_seconds
        original_terminate = github_import_service._terminate_process_tree
        try:
            github_import_service.subprocess.Popen = _fake_popen
            github_import_service._git_timeout_seconds = lambda: 1
            github_import_service._terminate_process_tree = lambda process: terminated.append(process.pid)

            with self.assertRaises(GithubImportError) as ctx:
                _run_git_checked(["clone", "https://github.com/example/repo.git", "repo"])

            self.assertIn("timed out", str(ctx.exception))
            self.assertEqual(terminated, [12345])
            self.assertEqual(fake_process.communicate_calls, 2)
        finally:
            github_import_service.subprocess.Popen = original_popen
            github_import_service._git_timeout_seconds = original_timeout
            github_import_service._terminate_process_tree = original_terminate


class GithubImportLocateTest(unittest.TestCase):
    def test_resolve_sparse_skill_subdir_prefers_skills_folder_without_blob_checkout(self):
        calls = []

        def _fake_run(args, *, cwd=None):
            calls.append((tuple(args), cwd))
            if args[:2] == ["cat-file", "-e"]:
                if args[2] == "HEAD:skills/alpha/SKILL.md":
                    return ""
                raise GithubImportError("missing")
            raise AssertionError(f"unexpected git command: {args}")

        original_run = github_import_service._run_git_checked
        try:
            github_import_service._run_git_checked = _fake_run
            resolved = _resolve_sparse_skill_subdir("repo", skill_name="alpha")
        finally:
            github_import_service._run_git_checked = original_run

        self.assertEqual(resolved, "skills/alpha")
        self.assertEqual(calls[0][0], ("cat-file", "-e", "HEAD:skills/alpha/SKILL.md"))

    def test_resolve_sparse_skill_subdir_supports_unique_recursive_match(self):
        def _fake_run(args, *, cwd=None):
            if args[:2] == ["cat-file", "-e"]:
                if args[2] == "HEAD:packages/skills/gamma/SKILL.md":
                    return ""
                raise GithubImportError("missing")
            if args == ["ls-tree", "-d", "-r", "--name-only", "HEAD"]:
                return "packages\npackages/skills\npackages/skills/gamma\n"
            raise AssertionError(f"unexpected git command: {args}")

        original_run = github_import_service._run_git_checked
        try:
            github_import_service._run_git_checked = _fake_run
            resolved = _resolve_sparse_skill_subdir("repo", skill_name="gamma")
        finally:
            github_import_service._run_git_checked = original_run

        self.assertEqual(resolved, "packages/skills/gamma")

    def test_locate_skill_directory_prefers_skills_folder(self):
        with tempfile.TemporaryDirectory() as repo_root:
            _write_text(os.path.join(repo_root, "skills", "alpha", "SKILL.md"), "# A")
            _write_text(os.path.join(repo_root, "alpha", "SKILL.md"), "# B")

            located = locate_skill_directory(repo_root, "alpha")
            expected = os.path.abspath(os.path.join(repo_root, "skills", "alpha"))
            self.assertEqual(os.path.abspath(located), expected)

    def test_locate_skill_directory_falls_back_to_root_folder(self):
        with tempfile.TemporaryDirectory() as repo_root:
            _write_text(os.path.join(repo_root, "beta", "SKILL.md"), "# B")

            located = locate_skill_directory(repo_root, "beta")
            expected = os.path.abspath(os.path.join(repo_root, "beta"))
            self.assertEqual(os.path.abspath(located), expected)

    def test_locate_skill_directory_supports_unique_recursive_match(self):
        with tempfile.TemporaryDirectory() as repo_root:
            _write_text(os.path.join(repo_root, "packages", "skills", "gamma", "SKILL.md"), "# G")

            located = locate_skill_directory(repo_root, "gamma")
            expected = os.path.abspath(os.path.join(repo_root, "packages", "skills", "gamma"))
            self.assertEqual(os.path.abspath(located), expected)

    def test_locate_skill_directory_reports_multiple_matches(self):
        with tempfile.TemporaryDirectory() as repo_root:
            _write_text(os.path.join(repo_root, "a", "delta", "SKILL.md"), "# D1")
            _write_text(os.path.join(repo_root, "b", "delta", "SKILL.md"), "# D2")

            with self.assertRaises(GithubImportError) as ctx:
                locate_skill_directory(repo_root, "delta")
            self.assertIn("Multiple skill directories matched", str(ctx.exception))

    def test_locate_skill_directory_reports_missing_root_skill_file(self):
        with tempfile.TemporaryDirectory() as repo_root:
            _write_text(os.path.join(repo_root, "skills", "epsilon", "README.md"), "x")

            with self.assertRaises(GithubImportError) as ctx:
                locate_skill_directory(repo_root, "epsilon")
            self.assertIn("missing root SKILL.md", str(ctx.exception))

    def test_locate_skill_directory_reports_not_found(self):
        with tempfile.TemporaryDirectory() as repo_root:
            with self.assertRaises(GithubImportError) as ctx:
                locate_skill_directory(repo_root, "zeta")
            self.assertIn("not found in repository", str(ctx.exception))


class GithubImportDescriptionTest(unittest.TestCase):
    def test_read_skill_description_from_frontmatter(self):
        with tempfile.TemporaryDirectory() as skill_dir:
            _write_text(
                os.path.join(skill_dir, "SKILL.md"),
                "---\nname: demo\ndescription: imported from github\n---\n# Skill\n",
            )
            self.assertEqual(read_skill_description(skill_dir), "imported from github")

    def test_read_skill_description_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as skill_dir:
            _write_text(os.path.join(skill_dir, "SKILL.md"), "# Skill\n")
            self.assertIsNone(read_skill_description(skill_dir))


if __name__ == "__main__":
    unittest.main()
