import json
import uuid
import pytest
from app.domains.diagnosis_playbook import guide_session as sop
from app.domains.diagnosis_playbook.contracts import PlaybookError
from tests.diagnosis_playbook.test_business_flow import seed_case
from app.domains.diagnosis_playbook.analysis_guide import promote_case, task_binding


def setup(db):
    user, workspace, task, case = seed_case(db)
    spec = promote_case(db, case)["spec"]
    task.task_meta_json = {"diagnosis_playbook_guide": task_binding(db, workspace.id, spec["id"])}
    db.commit()
    return task, user


def report(db, task, **updates):
    payload = {"phase": sop.public(task)["active_phase"], "findings": "已检查本次日志",
        "evidence": [{"reference": "incident.log:12", "observation": "错误码 1213"}],
        "ready_for_review": True, **updates}
    result = sop.accept_result(db, task.id, sop.turn_context(task), "分析结果\n```traceforge-sop\n" + json.dumps(payload) + "\n```", "job-1")
    db.commit()
    return result


def decide(db, task, user, action="advance", **updates):
    result = sop.command(db, task, {"action": action, "expected_version": sop.public(task)["version"],
        "idempotency_key": str(uuid.uuid4()), **updates}, user.id)
    db.commit()
    return result


def hypotheses():
    return [{"id": f"H{i}", "claim": f"假说 {i}", "prediction": "双向等待", "falsifier": "单向等待",
        "verdict": "SUPPORTED", "verdict_reason": "本次日志观察到预测的事务互锁",
        "evidence": [{"reference": "deadlock.log:14", "observation": "事务互锁"}]} for i in (1, 2)]


def test_four_stages_require_current_evidence_human_root_and_execution_observation(db):
    task, user = setup(db)
    with pytest.raises(PlaybookError, match="STAGE_EVIDENCE_REQUIRED"):
        decide(db, task, user)
    report(db, task)
    assert decide(db, task, user)["active_phase"] == "HYPOTHESIZE"
    report(db, task, hypotheses=hypotheses())
    with pytest.raises(PlaybookError, match="ROOT_CAUSE_CONFIRMATION_REQUIRED"):
        decide(db, task, user)
    decide(db, task, user, "approve_hypothesis", hypothesis_id="H1")
    decide(db, task, user, "exclude_hypothesis", hypothesis_id="H2")
    assert decide(db, task, user)["active_phase"] == "REPRODUCE"
    report(db, task, code="def test_deadlock(): pass")
    with pytest.raises(PlaybookError, match="EXECUTION_OBSERVATION_REQUIRED"):
        decide(db, task, user)
    report(db, task, outcome="OBSERVED")
    assert decide(db, task, user)["active_phase"] == "PATCH"
    report(db, task, outcome="OBSERVED", findings="回归完成")
    final = decide(db, task, user)
    assert final["completed"] and len(final["confirmations"]) == 4
    assert final["hypotheses"][0]["state"] == "APPROVED"
    assert "physical_receipt" not in final
    db.expire_all()
    assert sop.public(task) == final


def test_stale_turns_version_conflicts_and_idempotent_commands(db):
    task, user = setup(db)
    fence = sop.turn_context(task)
    report(db, task)
    request = {"action": "advance", "expected_version": sop.public(task)["version"], "idempotency_key": "one"}
    first = sop.command(db, task, request, user.id)
    db.commit()
    assert sop.command(db, task, request, user.id) == first
    assert sop.accept_result(db, task.id, fence, "old result", "old-job") is None
    with pytest.raises(PlaybookError, match="STATE_VERSION_CONFLICT"):
        sop.command(db, task, {**request, "idempotency_key": "two"}, user.id)
    fence = sop.turn_context(task)
    task.session_revision += 1
    db.flush()
    assert sop.accept_result(db, task.id, fence, "late", "old-job") is None
    task.session_generation += 1
    assert sop.public(task)["active_phase"] == "PROBE" and not sop.public(task)["reports"]


def test_invalid_report_never_advances_or_reuses_old_ready_result(db):
    task, user = setup(db)
    report(db, task)
    value = sop.accept_result(db, task.id, sop.turn_context(task), "文字 PASS 不构成结果", "job")
    db.commit()
    assert value["error"]
    with pytest.raises(PlaybookError, match="STAGE_EVIDENCE_REQUIRED"):
        decide(db, task, user)


def test_undo_invalidates_affected_evidence_and_downstream_confirmations(db):
    task, user = setup(db)
    report(db, task)
    decide(db, task, user)
    report(db, task, hypotheses=hypotheses())
    decide(db, task, user, "approve_hypothesis", hypothesis_id="H1")
    decide(db, task, user)
    old_version = sop.public(task)["version"]
    sop.invalidate_reverted_jobs(task, {"unrelated-job"})
    assert sop.public(task)["version"] == old_version
    sop.invalidate_reverted_jobs(task, {"job-1"})
    db.commit()
    state = sop.public(task)
    assert state["version"] > old_version
    assert state["active_phase"] == "PROBE"
    assert not state["reports"] and not state["confirmations"] and not state["hypotheses"]


def test_active_agent_blocks_stage_changes_and_changed_claim_loses_approval(db):
    from app.domains.ai.models.ai_job import SddAiJob, AiJobChannel, AiJobStatus
    task, user = setup(db)
    report(db, task)
    decide(db, task, user)
    report(db, task, hypotheses=hypotheses())
    decide(db, task, user, "approve_hypothesis", hypothesis_id="H1")
    changed = hypotheses()
    changed[0]["claim"] = "另一种根因"
    value = report(db, task, hypotheses=changed)
    assert value["hypotheses"][0]["state"] == "PROPOSED"
    decide(db, task, user, "approve_hypothesis", hypothesis_id="H1")
    changed[0]["evidence"] = []
    changed[0]["verdict"] = "UNTESTED"
    value = report(db, task, hypotheses=changed)
    assert value["hypotheses"][0]["state"] == "PROPOSED"
    job = SddAiJob(workspace_id=task.workspace_id, task_id=task.id, channel=AiJobChannel.TASK_CHAT,
        creator_id=user.id, queue_key="task:" + task.id, status=AiJobStatus.RUNNING)
    db.add(job)
    db.commit()
    with pytest.raises(PlaybookError, match="AGENT_TURN_ACTIVE"):
        decide(db, task, user, "approve_hypothesis", hypothesis_id="H1")


def test_commands_commit_and_broadcast_the_same_snapshot(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock
    from app.dependencies import get_current_user, get_db
    from app.domains.diagnosis_playbook.router import router
    task, user = setup(db)
    from app.domains.task.models.task import TaskStatus
    from app.domains.task.services import chat_submission_service
    from unittest.mock import Mock
    task.status = TaskStatus.CODING
    db.commit()
    scheduled = Mock()
    monkeypatch.setattr(chat_submission_service, 'schedule', scheduled)
    monkeypatch.setattr(chat_submission_service, 'wake_event_publisher', AsyncMock())
    report(db, task)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    published = AsyncMock()
    monkeypatch.setattr(sop, 'publish', published)
    client = TestClient(app)
    url = f'/workspaces/{task.workspace_id}/tasks/{task.id}/guide-session'
    current = client.get(url).json()
    response = client.post(url + '/commands', json={"action": "advance", "expected_version": current["version"], "idempotency_key": "api"})
    assert response.status_code == 200, response.text
    assert response.json()["active_phase"] == "HYPOTHESIZE"
    published.assert_awaited_once_with(task.id, response.json())
    assert client.get(url).json() == response.json()
    from app.domains.task.models.chat_submission import TaskChatSubmission
    receipt = db.query(TaskChatSubmission).one()
    assert receipt.status == 'PREPARING'
    assert '假说与实验' in receipt.content
    scheduled.assert_called_once_with(receipt.id)
    repeated = client.post(url + '/commands', json={"action": "advance", "expected_version": current["version"], "idempotency_key": "api"})
    assert repeated.status_code == 200
    assert db.query(TaskChatSubmission).count() == 1


def test_initial_generation_normalization_preserves_report_and_confirmation(db):
    task, user = setup(db)
    task.session_generation = 0
    db.commit()
    report(db, task)
    decide(db, task, user)
    sop.migrate_initial_generation(task)
    task.session_generation = 1
    db.commit()
    assert sop.public(task)['active_phase'] == 'HYPOTHESIZE'
    assert 'PROBE' in sop.public(task)['confirmations']
    state = report(db, task, hypotheses=hypotheses())
    assert len(state['hypotheses']) == 2
    assert set(state['reports']) == {'PROBE', 'HYPOTHESIZE'}


def test_complete_stream_report_used_when_provider_result_is_truncated(db):
    task, user = setup(db)
    report(db, task)
    decide(db, task, user)
    payload = {'phase': 'HYPOTHESIZE', 'findings': 'complete', 'hypotheses': hypotheses()}
    text = '```traceforge-sop\n' + json.dumps(payload) + '\n```'
    value = sop.accept_result(db, task.id, sop.turn_context(task), text[:80], 'job-full', text)
    assert value['error'] is None
    assert len(value['hypotheses']) == 2


def test_control_toggle_during_execution_does_not_invalidate_current_report(db):
    task, user = setup(db)
    fence = sop.turn_context(task)
    decide(db, task, user, 'enable_auto')
    decide(db, task, user, 'disable_auto')
    text = '```traceforge-sop\n' + json.dumps({'phase': 'PROBE', 'findings': 'done'}) + '\n```'
    value = sop.accept_result(db, task.id, fence, text, 'job-full')
    assert value is not None and not value['auto_run']


def test_main_switch_seeds_auto_run_and_manual_override_wins_within_session(db):
    task, user = setup(db)
    # 未开启主开关：新会话默认手动模式
    assert sop.public(task)['auto_run'] is False
    # 新建任务 / 启动引擎写入的主开关：新会话以自动执行初始化
    task.task_meta_json = {**task.task_meta_json, 'sop_auto_run': True}
    db.commit()
    assert sop.public(task)['auto_run'] is True
    # 会话内手动关闭优先于主开关
    decide(db, task, user, 'disable_auto')
    assert sop.public(task)['auto_run'] is False
    # 新会话（generation 变更）重新按主开关初始化
    task.session_generation += 1
    db.commit()
    assert sop.public(task)['auto_run'] is True


def test_refuted_hypothesis_cannot_be_approved_and_new_verdict_revokes_approval(db):
    task, user = setup(db)
    report(db, task)
    decide(db, task, user)
    items = hypotheses()
    report(db, task, hypotheses=items)
    decide(db, task, user, 'approve_hypothesis', hypothesis_id='H1')
    items[0].update(verdict='REFUTED', verdict_reason='本次区分实验与预测矛盾')
    value = report(db, task, hypotheses=items)
    assert value['hypotheses'][0]['verdict'] == 'REFUTED'
    assert value['hypotheses'][0]['state'] == 'PROPOSED'
    with pytest.raises(PlaybookError, match='HYPOTHESIS_NOT_SUPPORTED'):
        decide(db, task, user, 'approve_hypothesis', hypothesis_id='H1')
    with pytest.raises(PlaybookError, match='ROOT_CAUSE_CONFIRMATION_REQUIRED'):
        decide(db, task, user)
    decide(db, task, user, 'approve_hypothesis', hypothesis_id='H2')
    assert decide(db, task, user)['active_phase'] == 'REPRODUCE'


@pytest.mark.parametrize('verdict', ['SUPPORTED', 'REFUTED', 'INCONCLUSIVE'])
def test_verdict_requires_reason_and_actual_evidence(verdict):
    item = hypotheses()[0]
    for patch in ({'evidence': []}, {'verdict_reason': ' '}):
        with pytest.raises(ValueError):
            sop.Hypothesis.model_validate({**item, 'verdict': verdict, **patch})


def test_legacy_evidence_does_not_imply_support(db):
    task, user = setup(db)
    report(db, task)
    decide(db, task, user)
    items = [{k: v for k, v in h.items() if k not in {'verdict', 'verdict_reason'}} for h in hypotheses()]
    value = report(db, task, hypotheses=items)
    assert all(h['verdict'] == 'UNTESTED' for h in value['hypotheses'])
    with pytest.raises(PlaybookError, match='HYPOTHESIS_NOT_SUPPORTED'):
        decide(db, task, user, 'approve_hypothesis', hypothesis_id='H1')
