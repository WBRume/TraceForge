import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from app.domains.skill.services.runtime import materialization as skill_runtime_materialization

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


class SkillMaterializationAtomicReplaceTest(unittest.TestCase):
    def test_install_retries_windows_sharing_conflict(self):
        replace = os.replace
        error = PermissionError("directory is temporarily locked")
        error.winerror = 5
        with tempfile.TemporaryDirectory() as tmpdir:
            live_dir = os.path.join(tmpdir, "skills")
            with (
                mock.patch.object(os, "replace", side_effect=[error, mock.DEFAULT], wraps=replace) as rename,
                mock.patch.object(skill_runtime_materialization.time, "sleep") as sleep,
            ):
                skill_runtime_materialization._replace_skills_atomically([], live_dir)
            self.assertEqual(rename.call_count, 2)
            sleep.assert_called_once_with(0.05)
            self.assertEqual(os.listdir(tmpdir), ["skills"])

    def test_exhausted_windows_retries_restore_original_directory(self):
        replace = os.replace
        error = PermissionError("staged directory is locked")
        error.winerror = 5
        with tempfile.TemporaryDirectory() as tmpdir:
            live_dir = os.path.join(tmpdir, "skills")
            os.mkdir(live_dir)
            marker = os.path.join(live_dir, "keep.txt")
            with open(marker, "w", encoding="utf-8") as file:
                file.write("old")

            def deny_staged_rename(source, target):
                if ".__tmp__." in source:
                    raise error
                replace(source, target)

            with (
                mock.patch.object(os, "replace", side_effect=deny_staged_rename),
                mock.patch.object(skill_runtime_materialization.time, "sleep") as sleep,
                self.assertRaises(PermissionError),
            ):
                skill_runtime_materialization._replace_skills_atomically([], live_dir)
            self.assertEqual(sleep.call_count, 5)
            self.assertEqual(os.listdir(tmpdir), ["skills"])
            self.assertTrue(os.path.isfile(marker))

    def test_replace_skills_atomically_preserves_live_dir_on_copy_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            live_dir = os.path.join(tmpdir, ".claude", "skills")
            os.makedirs(live_dir, exist_ok=True)
            marker_path = os.path.join(live_dir, "keep.txt")
            with open(marker_path, "w", encoding="utf-8") as file:
                file.write("old-content")

            with mock.patch.object(
                skill_runtime_materialization, "_copy_skills_to_target", side_effect=RuntimeError("copy failed")
            ):
                with self.assertRaises(RuntimeError):
                    skill_runtime_materialization._replace_skills_atomically([], live_dir)

            self.assertTrue(os.path.isfile(marker_path))
            with open(marker_path, encoding="utf-8") as file:
                self.assertEqual(file.read(), "old-content")

    def test_replace_skills_atomically_can_discard_deleted_runtime_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            live_dir = os.path.join(tmpdir, ".claude", "skills")
            deleted_dir = os.path.join(live_dir, "session-marker")
            os.makedirs(deleted_dir, exist_ok=True)
            with open(os.path.join(deleted_dir, "SKILL.md"), "w", encoding="utf-8") as file:
                file.write("# Session Marker\n")
            with open(
                os.path.join(live_dir, skill_runtime_materialization.TASK_SKILLS_MANIFEST), "w", encoding="utf-8"
            ) as file:
                json.dump(
                    {
                        "version": 1,
                        "items": [
                            {
                                "skill_id": "runtime:session-marker",
                                "name": "session-marker",
                                "materialized_dir": "session-marker",
                            }
                        ],
                    },
                    file,
                )

            skill_runtime_materialization._replace_skills_atomically(
                [],
                live_dir,
                preserve_deleted_runtime_skills=False,
            )

            self.assertFalse(os.path.exists(deleted_dir))
            with open(
                os.path.join(live_dir, skill_runtime_materialization.TASK_SKILLS_MANIFEST), encoding="utf-8"
            ) as file:
                payload = json.load(file)
            self.assertEqual(payload.get("items"), [])


if __name__ == "__main__":
    unittest.main()
