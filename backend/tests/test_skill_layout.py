import os
import sys
import tempfile
import unittest
from types import SimpleNamespace


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.services import skill_service  # noqa: E402


class TaskSkillLayoutTest(unittest.TestCase):
    def test_backend_skill_layout_mapping(self):
        self.assertEqual(skill_service.task_skills_rel_root("claude-code"), ".claude/skills")
        self.assertEqual(skill_service.task_skills_rel_root("mock"), ".claude/skills")
        self.assertEqual(skill_service.task_skills_rel_root("opencode"), ".agents/skills")
        self.assertEqual(skill_service.task_skills_rel_root("dsh"), ".agents/skills")
        self.assertEqual(skill_service.task_skills_rel_root("unknown"), ".claude/skills")

    def test_resolve_task_skills_root_uses_workspace_backend_when_task_not_sticky(self):
        class FakeWorkspace:
            agent_backend = "opencode"

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return FakeWorkspace()

        class FakeDb:
            def query(self, *args, **kwargs):
                return FakeQuery()

        with tempfile.TemporaryDirectory() as tmpdir:
            task = SimpleNamespace(
                id="task-1",
                workspace_id="ws-1",
                project_path=tmpdir,
                agent_backend=None,
            )
            root = skill_service.resolve_task_skills_root(FakeDb(), task)
            self.assertEqual(
                os.path.normpath(root),
                os.path.normpath(os.path.join(tmpdir, ".agents", "skills")),
            )


if __name__ == "__main__":
    unittest.main()