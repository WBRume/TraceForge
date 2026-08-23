import os
import sys
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.services.skill_runtime_trace_service import RuntimeSkillIndexItem, detect_tool_use_events


def _index_item() -> RuntimeSkillIndexItem:
    return RuntimeSkillIndexItem(
        skill_id="skill-1",
        skill_name="backend-api",
        materialized_dir="backend-api-12345678",
        runtime_root_abs=os.path.abspath(os.path.join("C:\\proj\\task", ".claude", "skills", "backend-api-12345678")),
        runtime_root_rel=".claude/skills/backend-api-12345678",
    )


def _opencode_index_item() -> RuntimeSkillIndexItem:
    return RuntimeSkillIndexItem(
        skill_id="skill-2",
        skill_name="frontend-api",
        materialized_dir="frontend-api-87654321",
        runtime_root_abs=os.path.abspath(os.path.join("C:\\proj\\task", ".agents", "skills", "frontend-api-87654321")),
        runtime_root_rel=".agents/skills/frontend-api-87654321",
    )


class SkillRuntimeTraceMatcherTest(unittest.TestCase):
    def _events(self, tool_name, tool_input):
        return detect_tool_use_events(
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-1",
            runtime_index=[_index_item()],
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id="tool-1",
        )

    def test_read_skill_md_records_entry_read(self):
        events = self._events("Read", {"file_path": ".claude/skills/backend-api-12345678/SKILL.md"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"].value, "ENTRY_READ")
        self.assertEqual(events[0]["evidence_level"].value, "EXACT_PATH")
        self.assertEqual(events[0]["relative_path"], "SKILL.md")

    def test_read_internal_file_records_file_read(self):
        events = self._events("Read", {"file_path": ".claude\\skills\\backend-api-12345678\\workflow.md"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"].value, "FILE_READ")
        self.assertEqual(events[0]["relative_path"], "workflow.md")

    def test_opencode_agents_skills_path_records_file_read(self):
        events = detect_tool_use_events(
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-1",
            runtime_index=[_opencode_index_item()],
            tool_name="Read",
            tool_input={"file_path": ".agents/skills/frontend-api-87654321/SKILL.md"},
            tool_use_id="tool-1",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"].value, "ENTRY_READ")
        self.assertEqual(events[0]["relative_path"], "SKILL.md")

    def test_ls_grep_glob_and_write_are_mapped(self):
        cases = [
            ("LS", {"path": ".claude/skills/backend-api-12345678/templates"}, "DIR_LIST"),
            ("Grep", {"path": ".claude/skills/backend-api-12345678", "pattern": "token"}, "FILE_SEARCH"),
            ("Glob", {"pattern": ".claude/skills/backend-api-12345678/**/*.md"}, "FILE_SEARCH"),
            ("Edit", {"file_path": ".claude/skills/backend-api-12345678/rules/a.md"}, "FILE_WRITE"),
            ("Write", {"file_path": ".claude/skills/backend-api-12345678/rules/a.md"}, "FILE_WRITE"),
            ("MultiEdit", {"file_path": ".claude/skills/backend-api-12345678/rules/a.md"}, "FILE_WRITE"),
        ]
        for tool_name, tool_input, expected in cases:
            with self.subTest(tool_name=tool_name):
                events = self._events(tool_name, tool_input)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["event_type"].value, expected)

    def test_bash_command_path_records_script_exec(self):
        events = self._events("Bash", {"command": "python .claude/skills/backend-api-12345678/tools/generate_plan.py"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"].value, "SCRIPT_EXEC")
        self.assertEqual(events[0]["evidence_level"].value, "COMMAND_PATH")
        self.assertEqual(events[0]["relative_path"], "tools/generate_plan.py")

    def test_skill_tool_exact_materialized_dir_records_confirmed_usage(self):
        events = self._events("Skill", {"skill": "backend-api-12345678"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"].value, "USAGE_CONFIRMED")
        self.assertEqual(events[0]["evidence_level"].value, "EXACT_PATH")
        self.assertEqual(events[0]["materialized_dir"], "backend-api-12345678")
        self.assertIsNone(events[0]["relative_path"])

    def test_searching_skills_root_without_materialized_dir_is_ignored(self):
        events = self._events("Grep", {"path": ".claude/skills", "pattern": "SKILL.md"})
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
