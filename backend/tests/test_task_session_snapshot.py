import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.services import task_session_snapshot_service as snapshots  # noqa: E402


def _git(cwd, *args):
    result = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


class TaskSessionSnapshotTest(unittest.TestCase):
    def test_restore_preserves_head_index_and_all_file_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "task")
            os.makedirs(repo)
            _git(repo, "init")
            _git(repo, "config", "user.email", "traceforge@example.test")
            _git(repo, "config", "user.name", "TraceForge Test")
            self._write(repo, "tracked.txt", "tracked-before\n")
            self._write(repo, "staged.txt", "staged-before\n")
            self._write(repo, ".gitignore", "ignored.txt\n")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "seed")
            self._write(repo, "staged.txt", "staged-before-but-staged-change\n")
            _git(repo, "add", "staged.txt")
            self._write(repo, "untracked.txt", "untracked-before\n")
            self._write(repo, "ignored.txt", "ignored-before\n")
            expected_status = _git(repo, "status", "--porcelain=v2", "--untracked-files=all")
            expected_head = _git(repo, "rev-parse", "HEAD").strip()
            index_path = _git(repo, "rev-parse", "--git-path", "index").strip()
            if not os.path.isabs(index_path):
                index_path = os.path.join(repo, index_path)
            expected_index = hashlib.sha256(open(index_path, "rb").read()).hexdigest()

            checkpoint_root = os.path.join(tmp, "checkpoint")
            os.makedirs(checkpoint_root)
            snapshots._create_worktree_checkpoint_sync(repo, [], checkpoint_root)

            self._write(repo, "tracked.txt", "changed\n")
            self._write(repo, "staged.txt", "changed-staged\n")
            _git(repo, "add", "staged.txt")
            os.remove(os.path.join(repo, "untracked.txt"))
            self._write(repo, "extra.txt", "must-disappear\n")
            self._write(repo, "ignored.txt", "changed-ignored\n")

            snapshots._restore_worktree_sync(
                checkpoint_root,
                repo,
                os.path.join(checkpoint_root, "current-worktree"),
            )

            self.assertEqual(open(os.path.join(repo, "tracked.txt"), encoding="utf-8").read(), "tracked-before\n")
            self.assertEqual(open(os.path.join(repo, "staged.txt"), encoding="utf-8").read(), "staged-before-but-staged-change\n")
            self.assertEqual(open(os.path.join(repo, "untracked.txt"), encoding="utf-8").read(), "untracked-before\n")
            self.assertEqual(open(os.path.join(repo, "ignored.txt"), encoding="utf-8").read(), "ignored-before\n")
            self.assertFalse(os.path.exists(os.path.join(repo, "extra.txt")))
            self.assertEqual(_git(repo, "rev-parse", "HEAD").strip(), expected_head)
            restored_index = hashlib.sha256(open(index_path, "rb").read()).hexdigest()
            self.assertEqual(restored_index, expected_index)
            self.assertEqual(_git(repo, "status", "--porcelain=v2", "--untracked-files=all"), expected_status)

            manifest = json.load(open(os.path.join(checkpoint_root, "worktree.json"), encoding="utf-8"))
            self.assertNotIn("must-disappear", json.dumps(manifest))

    def test_fresh_claude_checkpoint_removes_session_created_after_boundary(self):
        old_home = os.environ.get("CLAUDE_HOME")
        old_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["CLAUDE_HOME"] = os.path.join(tmp, "claude")
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
                project = os.path.join(tmp, "project")
                os.makedirs(project)
                checkpoint = os.path.join(tmp, "checkpoint")
                os.makedirs(checkpoint)

                metadata = snapshots._provider_checkpoint_sync(
                    "claude-code",
                    project,
                    None,
                    checkpoint,
                )
                self.assertEqual(metadata["kind"], "claude_jsonl")
                self.assertIsNone(metadata["copy"])

                store = snapshots._claude_store_dir(project)
                os.makedirs(store, exist_ok=True)
                session_path = os.path.join(store, "created-after-boundary.jsonl")
                self._write(store, "created-after-boundary.jsonl", '{"secret":"TF_FORGET_UNIT"}\n')

                snapshots._restore_provider_sync(
                    checkpoint,
                    "claude-code",
                    project,
                    "created-after-boundary",
                )
                self.assertFalse(os.path.exists(session_path))
        finally:
            if old_home is None:
                os.environ.pop("CLAUDE_HOME", None)
            else:
                os.environ["CLAUDE_HOME"] = old_home
            if old_config_dir is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = old_config_dir

    def test_current_claude_provider_backup_compensates_partial_restore(self):
        old_home = os.environ.get("CLAUDE_HOME")
        old_config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["CLAUDE_HOME"] = os.path.join(tmp, "claude")
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
                project = os.path.join(tmp, "project")
                os.makedirs(project)
                store = snapshots._claude_store_dir(project)
                os.makedirs(store, exist_ok=True)
                session_path = os.path.join(store, "session-1.jsonl")
                self._write(store, "session-1.jsonl", '{"secret":"CURRENT_STATE"}\n')

                checkpoint = os.path.join(tmp, "checkpoint")
                os.makedirs(checkpoint)
                snapshots._backup_current_provider_sync(
                    checkpoint,
                    "claude-code",
                    project,
                    "session-1",
                )
                self._write(store, "session-1.jsonl", '{"secret":"PARTIAL_MUTATION"}\n')

                snapshots._restore_provider_backup_sync(checkpoint)
                restored = open(session_path, encoding="utf-8").read()
                self.assertNotIn("PARTIAL_MUTATION", restored)
                self.assertIn("CURRENT_STATE", restored)
        finally:
            if old_home is None:
                os.environ.pop("CLAUDE_HOME", None)
            else:
                os.environ["CLAUDE_HOME"] = old_home
            if old_config_dir is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = old_config_dir

    def test_dsh_restore_prefix_can_be_isolated_to_a_cold_session(self):
        from app.agents.adapters.dsh import session_files

        old_setting = snapshots.settings.DSH_SESSION_ROOT
        old_env = os.environ.get("DSH_SESSION_ROOT")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                snapshots.settings.DSH_SESSION_ROOT = ""
                os.environ["DSH_SESSION_ROOT"] = os.path.join(tmp, "sessions")
                root = os.environ["DSH_SESSION_ROOT"]
                cwd = os.path.join(tmp, "task")
                os.makedirs(cwd)
                original_id = "session-live-old"
                source = session_files.session_log_path(root, cwd, original_id, ".jsonl")
                os.makedirs(os.path.dirname(source), exist_ok=True)
                self._write(
                    os.path.dirname(source),
                    "session.jsonl",
                    json.dumps({"type": "session", "id": original_id, "cwd": cwd})
                    + "\n"
                    + json.dumps({"type": "user/message", "text": "prefix-only"})
                    + "\n",
                )
                self._write(os.path.dirname(source), "attachment.sidecar", "sidecar-bytes")

                new_id = snapshots._fork_dsh_session_sync(original_id, cwd)
                self.assertIsNotNone(new_id)
                new_path, _suffix = session_files.locate_session_log(root, str(new_id))
                lines = open(new_path, encoding="utf-8").read().splitlines()
                header = json.loads(lines[0])
                self.assertEqual(header["id"], new_id)
                self.assertEqual(os.path.abspath(header["cwd"]), os.path.abspath(cwd))
                self.assertIn("prefix-only", lines[1])
                self.assertEqual(
                    open(os.path.join(os.path.dirname(new_path), "attachment.sidecar"), encoding="utf-8").read(),
                    "sidecar-bytes",
                )
                self.assertTrue(os.path.isfile(source))

                snapshots._cleanup_dsh_session_sync(str(new_id))
                with self.assertRaises(Exception):
                    session_files.locate_session_log(root, str(new_id))
        finally:
            snapshots.settings.DSH_SESSION_ROOT = old_setting
            if old_env is None:
                os.environ.pop("DSH_SESSION_ROOT", None)
            else:
                os.environ["DSH_SESSION_ROOT"] = old_env

    @staticmethod
    def _write(root, relative, content):
        path = os.path.join(root, relative)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)


if __name__ == "__main__":
    unittest.main()
