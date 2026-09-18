"""会话生命周期服务边界测试。

覆盖 task_session_control_service 中由路由层下沉的会话建立编排
（start / initialize 同步步骤与守卫、build_session_prompt 组装），
以及 diagnosis_result_service.prepare_diagnosis_summary_sync 的守卫与幂等。
"""

import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.case_center.models.case import SddCase  # noqa: E402
from app.domains.task.models.task import TaskStatus, TaskType  # noqa: E402
from app.domains.task.services import (  # noqa: E402
    diagnosis_result_service,
    task_session_control_service,
)
from test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


# ── build_session_prompt：用户可见文案与 agent prompt 的组装 ──


def test_build_session_prompt_prefers_requested_prompt():
    task = SimpleNamespace(name="T", description="description fallback", spec_doc_path=None)
    prompts = task_session_control_service.build_session_prompt(task, " 用户输入 ")
    assert prompts["user_display"] == "用户输入"
    assert prompts["prompt"] == "用户输入"


def test_build_session_prompt_falls_back_to_description_then_default():
    task = SimpleNamespace(name="checkout", description="描述文案", spec_doc_path=None)
    prompts = task_session_control_service.build_session_prompt(task, "  ")
    assert prompts["user_display"] == "描述文案"

    empty = SimpleNamespace(name="checkout", description="  ", spec_doc_path=None)
    prompts = task_session_control_service.build_session_prompt(empty, None)
    assert prompts["user_display"] == "Please start task 'checkout'."


def test_build_session_prompt_appends_spec_doc_guidance_for_agent_only():
    task = SimpleNamespace(name="T", description="d", spec_doc_path="G:/repo/spec.md")
    prompts = task_session_control_service.build_session_prompt(task, "开始")
    assert "G:\\repo\\spec.md" in prompts["prompt"] or "G:/repo/spec.md" in prompts["prompt"]
    # 规格文件指引只随作业发给 agent，不出现在会话窗口展示文案里
    assert "specification file" not in prompts["user_display"]


def test_build_session_prompt_appends_diagnosis_contract_for_diagnosis_tasks():
    task = SimpleNamespace(
        name="T", description="d", spec_doc_path=None,
        task_type="DIAGNOSIS", task_meta_json={"phenomenon": "500 报错"},
    )
    prompts = task_session_control_service.build_session_prompt(task, "开始")
    assert "[问题定位任务]" in prompts["prompt"]
    assert "[问题定位任务]" not in prompts["user_display"]


# ── load_start_task_context_sync：启动守卫 ──


@pytest.fixture()
def db_env():
    engine, SessionLocal = _build_db()
    try:
        yield SessionLocal
    finally:
        engine.dispose()


def test_load_start_context_rejects_running_or_interrupted_task(db_env):
    with _session(db_env) as db:
        _user, _ws, task = _seed_workspace(db, workspace_id="ws-guard", task_id="task-guard")

        task.status = TaskStatus.CODING
        db.commit()
        with pytest.raises(task_session_control_service.TaskSessionControlError) as exc:
            task_session_control_service.load_start_task_context_sync(
                db, ws_id="ws-guard", task_id="task-guard"
            )
        assert exc.value.status_code == 409

        task.status = TaskStatus.INTERRUPTED
        db.commit()
        with pytest.raises(task_session_control_service.TaskSessionControlError) as exc:
            task_session_control_service.load_start_task_context_sync(
                db, ws_id="ws-guard", task_id="task-guard"
            )
        assert exc.value.status_code == 409


def test_load_start_context_rejects_baselined_task(db_env):
    with _session(db_env) as db:
        _user, _ws, task = _seed_workspace(db, workspace_id="ws-base", task_id="task-base")
        task.status = TaskStatus.BASELINED
        db.commit()
        with pytest.raises(task_session_control_service.TaskSessionControlError) as exc:
            task_session_control_service.load_start_task_context_sync(
                db, ws_id="ws-base", task_id="task-base"
            )
        assert exc.value.status_code == 403


def test_load_start_context_rejects_unknown_task(db_env):
    with _session(db_env) as db:
        with pytest.raises(task_session_control_service.TaskSessionControlError) as exc:
            task_session_control_service.load_start_task_context_sync(
                db, ws_id="ws-missing", task_id="task-missing"
            )
        assert exc.value.status_code == 404


def test_load_start_context_allows_pending_task(db_env):
    with _session(db_env) as db:
        _user, _ws, task = _seed_workspace(db, workspace_id="ws-ok", task_id="task-ok")
        task.status = TaskStatus.PENDING
        task.description = "准备就绪"
        db.commit()
        state = task_session_control_service.load_start_task_context_sync(
            db, ws_id="ws-ok", task_id="task-ok"
        )
        assert state["user_display"] == "准备就绪"


# ── apply_initialize_sync：代际推进与在途作业互斥 ──


def _seed_blocking_chat_job(db, *, task_id, workspace_id="ws-init"):
    job = SddAiJob(
        id=f"job-{task_id}",
        task_id=task_id,
        workspace_id=workspace_id,
        creator_id="user-1",
        channel=AiJobChannel.TASK_CHAT,
        status=AiJobStatus.RUNNING,
        queue_key=f"task:{task_id}",
        prompt_text="p",
    )
    db.add(job)
    db.commit()
    return job


def test_apply_initialize_blocks_while_jobs_still_active(db_env):
    with _session(db_env) as db:
        _user, _ws, task = _seed_workspace(db, workspace_id="ws-init", task_id="task-init")
        task.status = TaskStatus.INTERRUPTED
        db.commit()
        _seed_blocking_chat_job(db, task_id="task-init")

        with pytest.raises(task_session_control_service.TaskSessionControlError) as exc:
            task_session_control_service.apply_initialize_sync(
                db, ws_id="ws-init", task_id="task-init",
                skill_ids=None, keep_deleted_runtime_skills=True,
            )
        assert exc.value.status_code == 409


def test_apply_initialize_bumps_generation_and_builds_prompt(db_env):
    with _session(db_env) as db:
        _user, _ws, task = _seed_workspace(db, workspace_id="ws-init2", task_id="task-init2")
        task.status = TaskStatus.INTERRUPTED
        task.interrupt_reason = "worker crashed"
        task.session_id = "old-session"
        task.retry_count = 1
        task.session_generation = 2
        db.commit()

        state = task_session_control_service.apply_initialize_sync(
            db, ws_id="ws-init2", task_id="task-init2",
            skill_ids=None, keep_deleted_runtime_skills=True,
            requested_prompt="重新开始",
        )

        assert state["user_display"] == "重新开始"
        assert task.status == TaskStatus.CODING
        assert task.retry_count == 2
        assert task.session_generation == 3
        assert task.session_id is None
        assert task.interrupt_reason is None


# ── prepare_diagnosis_summary_sync：守卫与幂等 ──


def _make_diagnosis_task(db, task, *, status="CONFIRMED"):
    task.task_type = TaskType.DIAGNOSIS
    db.commit()
    result = diagnosis_result_service.SddDiagnosisResult(
        task_id=task.id, workspace_id=task.workspace_id, created_by_id="user-1",
        status=status, summary="s", root_cause="r",
    )
    db.add(result)
    db.commit()
    return result


def test_prepare_summary_rejects_non_diagnosis_task(db_env):
    with _session(db_env) as db:
        _user, _ws, _task = _seed_workspace(db, workspace_id="ws-dev", task_id="task-dev")
        with pytest.raises(diagnosis_result_service.DiagnosisSummaryError) as exc:
            diagnosis_result_service.prepare_diagnosis_summary_sync(
                db, ws_id="ws-dev", task_id="task-dev", actor_user_id="user-1"
            )
        assert exc.value.status_code == 403


def test_prepare_summary_rejects_adopted_case(db_env):
    with _session(db_env) as db:
        _user, ws, task = _seed_workspace(db, workspace_id="ws-adopt", task_id="task-adopt")
        _make_diagnosis_task(db, task)
        db.add(SddCase(
            id="case-1", workspace_id=ws.id, source_task_id=task.id,
            title="c", creator_id="user-1", status="DRAFT",
        ))
        db.commit()

        with pytest.raises(diagnosis_result_service.DiagnosisSummaryError) as exc:
            diagnosis_result_service.prepare_diagnosis_summary_sync(
                db, ws_id="ws-adopt", task_id="task-adopt", actor_user_id="user-1"
            )
        assert exc.value.status_code == 409
        assert "adopted" in str(exc.value)


def test_prepare_summary_rejects_unknown_task(db_env):
    with _session(db_env) as db:
        with pytest.raises(diagnosis_result_service.DiagnosisSummaryError) as exc:
            diagnosis_result_service.prepare_diagnosis_summary_sync(
                db, ws_id="ws-none", task_id="task-none", actor_user_id="user-1"
            )
        assert exc.value.status_code == 404
