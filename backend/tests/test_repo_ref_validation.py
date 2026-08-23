"""
Git ref validation tests: validate_ref_exists for branches and tags.
"""

import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.management.services.git_ref_service import (  # noqa: E402
    GitRefAccessError,
    fetch_remote_refs,
    list_refs_for_picker,
    parse_ls_remote_output,
    validate_ref_exists,
    validate_repository_accessible,
)


LS_REMOTE_OUTPUT = (
    "abc123\tHEAD\n"
    "abc123\trefs/heads/main\n"
    "def456\trefs/heads/release/v8r21\n"
    "111222\trefs/tags/v8r21.0\n"
    "333444\trefs/tags/v8r21.1\n"
)


class ParseRemoteRefsTest(unittest.TestCase):
    def test_parse_output(self):
        entries = parse_ls_remote_output(LS_REMOTE_OUTPUT)
        self.assertEqual(entries, [
            ("BRANCH", "main", "abc123"),
            ("BRANCH", "release/v8r21", "def456"),
            ("TAG", "v8r21.0", "111222"),
            ("TAG", "v8r21.1", "333444"),
        ])

    def test_fetch_remote_refs_raises_on_failure(self):
        result = mock.Mock()
        result.returncode = 128
        result.stderr = "fatal: repository not found"
        result.stdout = ""
        with mock.patch(
            "app.domains.management.services.git_ref_service._run_ls_remote",
            return_value=result,
        ):
            with self.assertRaises(GitRefAccessError) as ctx:
                fetch_remote_refs("https://git.example.com/missing.git")
        self.assertEqual(ctx.exception.status_code, 400)


class ValidateRefExistsTest(unittest.TestCase):
    def _patch_ls_remote(self):
        result = mock.Mock()
        result.returncode = 0
        result.stdout = LS_REMOTE_OUTPUT
        result.stderr = ""
        return mock.patch(
            "app.domains.management.services.git_ref_service._run_ls_remote",
            return_value=result,
        )

    def test_branch_exists(self):
        with self._patch_ls_remote():
            validate_ref_exists("https://git.example.com/r.git", "BRANCH", "release/v8r21")

    def test_branch_missing_raises_409(self):
        with self._patch_ls_remote():
            with self.assertRaises(GitRefAccessError) as ctx:
                validate_ref_exists("https://git.example.com/r.git", "BRANCH", "nope")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Branch 'nope' does not exist", str(ctx.exception))

    def test_tag_exists(self):
        with self._patch_ls_remote():
            validate_ref_exists("https://git.example.com/r.git", "TAG", "v8r21.0")

    def test_tag_missing_raises_409(self):
        with self._patch_ls_remote():
            with self.assertRaises(GitRefAccessError) as ctx:
                validate_ref_exists("https://git.example.com/r.git", "TAG", "v9")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Tag 'v9' does not exist", str(ctx.exception))

    def test_tag_does_not_match_branch(self):
        with self._patch_ls_remote():
            # "main" is a branch, not a tag.
            with self.assertRaises(GitRefAccessError):
                validate_ref_exists("https://git.example.com/r.git", "TAG", "main")

    def test_invalid_ref_type_rejected(self):
        with self._patch_ls_remote():
            with self.assertRaises(GitRefAccessError) as ctx:
                validate_ref_exists("https://git.example.com/r.git", "COMMIT", "x")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_list_refs_for_picker(self):
        with self._patch_ls_remote():
            payload = list_refs_for_picker("https://git.example.com/r.git")
        self.assertIn("release/v8r21", payload["branches"])
        self.assertIn("v8r21.0", payload["tags"])
        self.assertTrue(payload["accessible"])

    def test_validate_repository_accessible(self):
        with self._patch_ls_remote():
            validate_repository_accessible("https://git.example.com/r.git")
