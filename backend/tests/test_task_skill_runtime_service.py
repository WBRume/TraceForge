import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.services import skill_runtime_trace_service, task_skill_runtime_service


class TaskSkillRuntimeServiceTest(unittest.TestCase):
    def _task(self, project_path: str):
        return SimpleNamespace(
            id="task-1",
            workspace_id="ws-1",
            project_path=project_path,
            created_at=datetime.utcnow(),
        )

    def test_manifest_runtime_skill_survives_config_skill_deletion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task = self._task(tmpdir)
            root = os.path.join(tmpdir, ".claude", "skills")
            skill_root = os.path.join(root, "git-commit")
            os.makedirs(skill_root, exist_ok=True)
            with open(os.path.join(skill_root, "SKILL.md"), "w", encoding="utf-8") as file:
                file.write("# Git Commit\n")
            with open(os.path.join(root, ".sdd-runtime-skills.json"), "w", encoding="utf-8") as file:
                file.write(
                    '{"version":1,"items":[{"skill_id":"deleted-skill","name":"git-commit",'
                    '"dimension":"WORKSPACE","materialized_dir":"git-commit"}]}'
                )

            with patch.object(task_skill_runtime_service.skill_service, "get_task_skills", return_value=[]):
                records = task_skill_runtime_service.get_task_runtime_skill_records(SimpleNamespace(), task)
                tree = task_skill_runtime_service.build_task_runtime_skill_file_tree(
                    SimpleNamespace(),
                    task,
                    skill_id="deleted-skill",
                )
                content = task_skill_runtime_service.write_task_runtime_skill_file(
                    SimpleNamespace(),
                    task,
                    skill_id="deleted-skill",
                    path="notes.md",
                    content="runtime edit",
                )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].skill_id, "deleted-skill")
        self.assertTrue(records[0].config_deleted)
        self.assertEqual(tree[0]["path"], "SKILL.md")
        self.assertEqual(content["content"], "runtime edit")

    def test_trace_index_uses_materialized_dir_without_deleted_skill_id(self):
        task = self._task("C:/workspace/project")
        record = task_skill_runtime_service.RuntimeSkillRecord(
            skill_id="deleted-skill",
            name="git-commit",
            description=None,
            dimension="WORKSPACE",
            materialized_dir="git-commit",
            skill=None,
            config_deleted=True,
        )

        with patch.object(task_skill_runtime_service, "get_task_runtime_skill_records", return_value=[record]):
            index = skill_runtime_trace_service.build_runtime_skill_index(SimpleNamespace(), task)

        self.assertEqual(len(index), 1)
        self.assertIsNone(index[0].skill_id)
        self.assertEqual(index[0].materialized_dir, "git-commit")

    def test_usage_stats_can_count_events_by_materialized_dir_without_skill_id(self):
        task = self._task("C:/workspace/project")
        record = task_skill_runtime_service.RuntimeSkillRecord(
            skill_id="deleted-skill",
            name="git-commit",
            description=None,
            dimension="WORKSPACE",
            materialized_dir="git-commit",
            skill=None,
            config_deleted=True,
        )
        event = SimpleNamespace(
            skill_id=None,
            materialized_dir="git-commit",
            created_at=datetime.utcnow(),
        )

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def all(self):
                return [event]

        class FakeDb:
            def query(self, *args, **kwargs):
                return FakeQuery()

        usage = task_skill_runtime_service._build_usage_stats(
            FakeDb(),
            task,
            records=[record],
            scope_start_at=None,
        )

        self.assertTrue(usage["deleted-skill"]["is_used"])
        self.assertEqual(usage["deleted-skill"]["used_count"], 1)

    def test_list_runtime_skills_marks_deleted_config_records(self):
        task = self._task("C:/workspace/project")
        record = task_skill_runtime_service.RuntimeSkillRecord(
            skill_id="runtime:session-marker",
            name="session-marker",
            description=None,
            dimension="TASK_RUNTIME",
            materialized_dir="session-marker",
            skill=None,
            config_deleted=True,
        )
        usage = {
            "runtime:session-marker": {
                "is_used": False,
                "used_count": 0,
                "last_used_at": None,
                "usage_scope_start_at": None,
            }
        }

        with (
            patch.object(task_skill_runtime_service, "get_task_runtime_skill_records", return_value=[record]),
            patch.object(task_skill_runtime_service, "_latest_usage_scope_start", return_value=None),
            patch.object(task_skill_runtime_service, "_build_usage_stats", return_value=usage),
        ):
            payload = task_skill_runtime_service.list_task_runtime_skills(SimpleNamespace(), task)

        self.assertEqual(payload["items"][0]["skill_id"], "runtime:session-marker")
        self.assertTrue(payload["items"][0]["config_deleted"])


if __name__ == "__main__":
    unittest.main()
