import json
from uuid import uuid4

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.diagnosis_playbook import guide_execution as execution, guide_session as sop
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task import TaskStatus
from app.domains.task.services.chat_submission_service import finalize_submission_in_txn
from tests.diagnosis_playbook.test_guide_session import setup, hypotheses


def configured(db):
    task, user = setup(db)
    task.status = TaskStatus.CODING
    task.session_generation = 1
    db.commit()
    return task, user


def command(db, task, user, action):
    result = execution.command(db, task, {'action': action, 'expected_version': sop.public(task)['version'],
        'idempotency_key': str(uuid4())}, user.id)
    db.commit()
    return result


def finish(db, task, user, *, success=True, recommendation='H1', observed=True, verdict='SUPPORTED'):
    receipt = db.query(TaskChatSubmission).filter_by(active_task_id=task.id).one()
    job = SddAiJob(task_id=task.id, workspace_id=task.workspace_id, creator_id=user.id,
        channel=AiJobChannel.TASK_CHAT, queue_key='task:' + task.id, status=AiJobStatus.RUNNING,
        session_generation=task.session_generation)
    db.add(job)
    db.flush()
    receipt.ai_job_id = job.id
    receipt.status = 'EXECUTING'
    db.commit()
    phase = sop.public(task)['active_phase']
    payload = {'phase': phase, 'findings': 'Observed current experiment',
        'evidence': [{'reference': 'this-run.txt', 'observation': 'actual output'}],
        'outcome': 'OBSERVED' if observed else 'NOT_RUN', 'ready_for_review': True}
    if phase == 'HYPOTHESIZE':
        payload.update(hypotheses=[{**h, 'verdict': verdict} for h in hypotheses()], root_cause_hypothesis_id=recommendation)
    sop.accept_result(db, task.id, sop.turn_context(task),
        '```traceforge-sop\n' + json.dumps(payload) + '\n```', job.id)
    db.commit()
    job.status = AiJobStatus.SUCCESS if success else AiJobStatus.INTERRUPTED
    finalize_submission_in_txn(db, job, job.status)
    db.flush()
    result = execution.on_job_finished(db, job)
    db.commit()
    return result, job


def test_automatic_four_stages_are_durable_and_need_no_browser(db):
    task, user = configured(db)
    command(db, task, user, 'enable_auto')
    for next_phase in ('HYPOTHESIZE', 'REPRODUCE', 'PATCH', 'PATCH'):
        result, job = finish(db, task, user)
        assert result['active_phase'] == next_phase
    assert result['completed']
    assert all(v['mode'] == 'AUTOMATIC' for v in result['confirmations'].values())
    assert result['hypotheses'][0]['decision_mode'] == 'AUTOMATIC'
    assert db.query(TaskChatSubmission).count() == 4
    assert not db.query(TaskChatSubmission).filter_by(active_task_id=task.id).count()
    assert execution.on_job_finished(db, job) is None  # finalizer replay never launches another stage


def test_automatic_mode_pauses_without_unambiguous_root(db):
    task, user = configured(db)
    command(db, task, user, 'enable_auto')
    finish(db, task, user)
    result, _ = finish(db, task, user, recommendation=None)
    assert not result['auto_run'] and result['auto_pause_reason']
    assert result['active_phase'] == 'HYPOTHESIZE'
    assert all(h['state'] == 'PROPOSED' for h in result['hypotheses'])
    assert db.query(TaskChatSubmission).count() == 2


def test_auto_never_approves_a_refuted_recommendation(db):
    task, user = configured(db)
    command(db, task, user, 'enable_auto')
    finish(db, task, user)
    result, _ = finish(db, task, user, verdict='REFUTED')
    assert result['active_phase'] == 'HYPOTHESIZE' and not result['auto_run']
    assert all(h['verdict'] == 'REFUTED' and h['state'] == 'PROPOSED' for h in result['hypotheses'])
    assert db.query(TaskChatSubmission).count() == 2


def test_turn_failure_pauses_instead_of_looping(db):
    task, user = configured(db)
    command(db, task, user, 'enable_auto')
    result, _ = finish(db, task, user, success=False)
    assert not result['auto_run'] and result['active_phase'] == 'PROBE'
    assert db.query(TaskChatSubmission).count() == 1


def test_disabling_auto_preserves_current_turn_without_scheduling_next(db):
    task, user = configured(db)
    command(db, task, user, 'enable_auto')
    command(db, task, user, 'disable_auto')
    result, _ = finish(db, task, user)
    assert result is None
    assert sop.public(task)['reports']['PROBE']['ready_for_review']
    assert sop.public(task)['active_phase'] == 'PROBE'
    assert db.query(TaskChatSubmission).count() == 1


def test_reproduction_without_observation_never_auto_advances(db):
    task, user = configured(db)
    command(db, task, user, 'enable_auto')
    finish(db, task, user)
    finish(db, task, user)
    result, _ = finish(db, task, user, observed=False)
    assert not result['auto_run'] and result['active_phase'] == 'REPRODUCE'
    assert db.query(TaskChatSubmission).count() == 3


def test_websocket_failure_does_not_prevent_durable_submission_dispatch(monkeypatch):
    import asyncio
    import pytest
    from unittest.mock import AsyncMock, Mock
    from app.domains.task.services import chat_submission_service
    scheduled = Mock()
    monkeypatch.setattr(chat_submission_service, 'schedule', scheduled)
    monkeypatch.setattr(chat_submission_service, 'wake_event_publisher', AsyncMock())
    monkeypatch.setattr(sop, 'publish', AsyncMock(side_effect=RuntimeError('WS unavailable')))
    with pytest.raises(RuntimeError):
        asyncio.run(execution.dispatch('task', {'next_submission': {'id': 'durable-receipt'}}))
    scheduled.assert_called_once_with('durable-receipt')
