import os
import json
import sys
import tempfile
import unittest
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.services import skill_service  # noqa: E402


class SkillMaterializationAtomicReplaceTest(unittest.TestCase):
    def test_replace_skills_atomically_preserves_live_dir_on_copy_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            live_dir = os.path.join(tmpdir, ".claude", "skills")
            os.makedirs(live_dir, exist_ok=True)
            marker_path = os.path.join(live_dir, "keep.txt")
            with open(marker_path, "w", encoding="utf-8") as file:
                file.write("old-content")

            with mock.patch.object(skill_service, "_copy_skills_to_target", side_effect=RuntimeError("copy failed")):
                with self.assertRaises(RuntimeError):
                    skill_service._replace_skills_atomically([], live_dir)

            self.assertTrue(os.path.isfile(marker_path))
            with open(marker_path, "r", encoding="utf-8") as file:
                self.assertEqual(file.read(), "old-content")

    def test_replace_skills_atomically_can_discard_deleted_runtime_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            live_dir = os.path.join(tmpdir, ".claude", "skills")
            deleted_dir = os.path.join(live_dir, "session-marker")
            os.makedirs(deleted_dir, exist_ok=True)
            with open(os.path.join(deleted_dir, "SKILL.md"), "w", encoding="utf-8") as file:
                file.write("# Session Marker\n")
            with open(os.path.join(live_dir, skill_service.TASK_SKILLS_MANIFEST), "w", encoding="utf-8") as file:
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

            skill_service._replace_skills_atomically(
                [],
                live_dir,
                preserve_deleted_runtime_skills=False,
            )

            self.assertFalse(os.path.exists(deleted_dir))
            with open(os.path.join(live_dir, skill_service.TASK_SKILLS_MANIFEST), "r", encoding="utf-8") as file:
                payload = json.load(file)
            self.assertEqual(payload.get("items"), [])


if __name__ == "__main__":
    unittest.main()
