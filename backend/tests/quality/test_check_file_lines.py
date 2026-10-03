"""Exercise the real gate CLI in isolated Git repositories without app services."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKER = Path(__file__).resolve().parents[2] / "check_file_lines.py"


class FileLineGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="traceforge-python-lines-")
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name)
        self.project = self.repository / "backend"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True, capture_output=True)
        self.checker = self.project / "check_file_lines.py"
        shutil.copyfile(CHECKER, self.checker)

    def run_gate(self):
        return subprocess.run(
            [sys.executable, str(self.checker)],
            cwd=self.repository,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def write_source(self, name, content):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_accepts_1500_lines_with_each_line_ending_and_optional_final_newline(self):
        for ending in (b"\n", b"\r\n", b"\r"):
            for trailing in (True, False):
                with self.subTest(ending=ending, trailing=trailing):
                    content = (b"# comment" + ending) * 1499 + b"# final"
                    self.write_source("模块 with spaces.py", content + (ending if trailing else b""))
                    result = self.run_gate()
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_1501_lines_including_blanks_and_comments(self):
        for ending in (b"\n", b"\r\n", b"\r"):
            for trailing in (True, False):
                with self.subTest(ending=ending, trailing=trailing):
                    self.write_source("oversized.py", ending * 1500 + b"# final" + (ending if trailing else b""))
                    result = self.run_gate()
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("backend/oversized.py: 1501 行", result.stderr)
                    self.assertIn("需要重构", result.stderr)

    def test_reports_tracked_and_new_files_and_honors_ignore_rules(self):
        (self.repository / ".gitignore").write_text(
            "backend/ignored/\nbackend/tracked_ignored.py\n", encoding="utf-8"
        )
        oversized = b"\n" * 1501
        self.write_source("tracked_ignored.py", oversized)
        subprocess.run(
            ["git", "add", "-f", "backend/tracked_ignored.py"],
            cwd=self.repository, check=True, capture_output=True,
        )
        self.write_source("新的模块 with spaces.py", oversized)
        self.write_source("ignored/dependency.py", oversized)
        self.write_source("notes.txt", oversized)
        frontend = self.repository / "frontend"
        frontend.mkdir()
        (frontend / "unrelated.py").write_bytes(oversized)
        result = self.run_gate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("backend/tracked_ignored.py: 1501 行", result.stderr)
        self.assertIn("backend/新的模块 with spaces.py: 1501 行", result.stderr)
        self.assertNotIn("dependency.py", result.stderr)
        self.assertNotIn("notes.txt", result.stderr)
        self.assertNotIn("unrelated.py", result.stderr)

    def test_skips_deleted_tracked_files(self):
        path = self.write_source("deleted.py", b"\n" * 1501)
        subprocess.run(
            ["git", "add", "backend/deleted.py"],
            cwd=self.repository, check=True, capture_output=True,
        )
        path.unlink()
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_files_and_unicode_line_separators_are_physical_lines(self):
        self.write_source("empty.py", b"")
        self.write_source("unicode.py", ("# 文本\u2028" * 1501).encode("utf-8"))
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_inventory_failure_blocks_the_gate(self):
        with tempfile.TemporaryDirectory(prefix="traceforge-no-git-") as directory:
            checker = Path(directory) / "check_file_lines.py"
            shutil.copyfile(CHECKER, checker)
            result = subprocess.run(
                [sys.executable, str(checker)], cwd=directory, capture_output=True,
            )
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
