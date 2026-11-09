from types import SimpleNamespace

from app.domains.skill.models.skill import SddSkill, SkillAnalysisStatus, SkillDimension
from app.domains.skill.routers.skill import list_active_skill_analyses
from app.domains.workspace.services import workspace_service
from tests.ai.jobs.domain_job_test_utils import make_analysis
from tests.skill import test_skill_analysis_service as scan_tests


def test_active_analyses_only_restore_owned_accessible_running_jobs(monkeypatch):
    db = scan_tests.SkillAnalysisDeterministicScanTest()._db()
    try:
        skill = SddSkill(
            id="visible",
            name="Visible skill",
            workspace_id="ws",
            dimension=SkillDimension.WORKSPACE,
            creator_id="user",
            last_modifier_id="user",
            package_path="fixture",
        )
        hidden_skill = SddSkill(
            id="hidden",
            name="Moved skill",
            workspace_id="other",
            dimension=SkillDimension.WORKSPACE,
            creator_id="user",
            last_modifier_id="user",
            package_path="fixture-other",
        )
        db.add_all([skill, hidden_skill])
        for analysis_id, owner, workspace, skill_id, status in [
            ("own-running", "user", "ws", "visible", SkillAnalysisStatus.RUNNING),
            ("own-pending", "user", "ws", "visible", SkillAnalysisStatus.PENDING),
            ("finished", "user", "ws", "visible", SkillAnalysisStatus.SUCCESS),
            ("other-user", "another", "ws", "visible", SkillAnalysisStatus.RUNNING),
            ("lost-membership", "user", "revoked", "visible", SkillAnalysisStatus.RUNNING),
            ("moved-skill", "user", "ws", "hidden", SkillAnalysisStatus.RUNNING),
        ]:
            db.add(
                make_analysis(
                    id=analysis_id, created_by_id=owner, workspace_id=workspace, skill_id=skill_id, status=status
                )
            )
        db.commit()
        monkeypatch.setattr(workspace_service, "get_workspace_member", lambda db, ws, user: ws == "ws")
        restored = list_active_skill_analyses(current_user=SimpleNamespace(id="user"), db=db)
        assert {item.id for item in restored} == {"own-running", "own-pending"}
        assert all(item.skill_name == "Visible skill" for item in restored)
    finally:
        db.close()
