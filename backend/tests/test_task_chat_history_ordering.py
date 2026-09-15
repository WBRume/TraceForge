import json
import os
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.ai.models.ai_job  # noqa: F401,E402
import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.provision_job  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.task.models.task import SddTask  # noqa: E402
from app.domains.task.models.chat import ChatMessage, MessageType  # noqa: E402
from app.domains.task.models.log import LogType, SddExecutionLog  # noqa: E402
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload  # noqa: E402
from app.domains.task.services import diagnosis_result_service, task_service  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()


def _seed_task(db):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path="G:/tmp/task-1",
        status="CODING",
    )
    db.add_all([user, workspace, task])
    db.commit()
    return task


def test_task_history_keeps_streamed_bubbles_in_insertion_order(db_session):
    db = db_session
    task = _seed_task(db)

    for index in range(3):
        task_service.save_chat_message(
            db,
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            role="assistant",
            content=f"stream-chunk-{index}",
            message_type="text",
        )

    # Simulate the real streaming case: every chunk lands within the same second.
    same_time = datetime.utcnow()
    db.query(ChatMessage).filter(ChatMessage.task_id == task.id).update(
        {"created_at": same_time}
    )
    db.commit()

    history = task_service.get_task_history(db, task.id, task.workspace_id)
    contents = [m["content"] for m in history["messages"]]
    assert contents == ["stream-chunk-0", "stream-chunk-1", "stream-chunk-2"]
    assert len(history["messages"]) == 3


def test_task_history_pagination_returns_latest_page_first(db_session):
    db = db_session
    task = _seed_task(db)

    total = 120
    for index in range(total):
        task_service.save_chat_message(
            db,
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            role="assistant",
            content=f"msg-{index}",
            message_type="text",
        )

    # 同一秒写入，确保分页依据 order_index 而不是 created_at 秒级精度
    same_time = datetime.utcnow()
    db.query(ChatMessage).filter(ChatMessage.task_id == task.id).update(
        {"created_at": same_time}
    )
    db.commit()

    page1 = task_service.get_task_history(db, task.id, task.workspace_id, page=1, page_size=50)
    assert len(page1["messages"]) == 50
    assert page1["has_more"] is True
    assert [m["content"] for m in page1["messages"]] == [f"msg-{i}" for i in range(70, 120)]

    page2 = task_service.get_task_history(db, task.id, task.workspace_id, page=2, page_size=50)
    assert len(page2["messages"]) == 50
    assert page2["has_more"] is True
    assert [m["content"] for m in page2["messages"]] == [f"msg-{i}" for i in range(20, 70)]

    page3 = task_service.get_task_history(db, task.id, task.workspace_id, page=3, page_size=50)
    assert len(page3["messages"]) == 20
    assert page3["has_more"] is False
    assert [m["content"] for m in page3["messages"]] == [f"msg-{i}" for i in range(20)]


def test_task_history_limits_terminal_logs_and_excludes_provider_noise(db_session):
    db = db_session
    task = _seed_task(db)
    base_time = datetime.utcnow()

    for index in range(8):
        db.add(SddExecutionLog(
            id=f"log-{index}",
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            log_type=LogType.STDOUT,
            content=json.dumps({
                "tool_name": "read_file",
                "tool_input": {"path": f"file-{index}.py"},
                "tool_use_id": f"call-{index}",
            }),
            event_order=index + 1,
            created_at=base_time + timedelta(milliseconds=index),
        ))
    db.add_all([
        SddExecutionLog(
            id="debug-log",
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            log_type=LogType.STDOUT,
            content='[opencode:session.status] {"type": "busy"}',
            event_order=100,
            created_at=base_time + timedelta(seconds=1),
        ),
        SddExecutionLog(
            id="assistant-copy",
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            log_type=LogType.STDOUT,
            content="duplicate assistant response",
            event_order=101,
            created_at=base_time + timedelta(seconds=2),
        ),
    ])
    db.commit()

    history = task_service.get_task_history(
        db,
        task.id,
        task.workspace_id,
        log_limit=5,
    )

    assert history["logs_has_more"] is True
    assert len(history["logs"]) == 5
    assert [json.loads(log["content"])["tool_use_id"] for log in history["logs"]] == [
        "call-3",
        "call-4",
        "call-5",
        "call-6",
        "call-7",
    ]


def test_diagnosis_result_card_comes_after_last_assistant_bubble(db_session):
    db = db_session
    task = _seed_task(db)
    task.task_type = "DIAGNOSIS"
    db.commit()

    for index in range(3):
        task_service.save_chat_message(
            db,
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            role="assistant",
            content=f"stream-chunk-{index}",
            message_type="text",
        )

    diagnosis_result_service.upsert_diagnosis_result_from_ai(
        db,
        task=task,
        payload=DiagnosisResultPayload(summary="root cause confirmed", root_cause="R1"),
        actor_user_id=task.creator_id,
    )

    # 把所有消息压到同一秒，复现真实流式回复场景
    same_time = datetime.utcnow()
    db.query(ChatMessage).filter(ChatMessage.task_id == task.id).update(
        {"created_at": same_time}
    )
    db.commit()

    history = task_service.get_task_history(db, task.id, task.workspace_id)
    types = [m["type"] for m in history.get("messages", [])]
    # 最后一条必须是定位结果卡片，而不是与上一个 assistant 文本气泡倒转
    assert types[-1] == MessageType.DIAGNOSIS_RESULT.value
    assert types[:-1] == ["text", "text", "text"]


def test_diagnosis_result_card_moves_to_end_when_updated_again(db_session):
    db = db_session
    task = _seed_task(db)
    task.task_type = "DIAGNOSIS"
    db.commit()

    for index in range(3):
        task_service.save_chat_message(
            db,
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            role="assistant",
            content=f"stream-chunk-{index}",
            message_type="text",
        )

    diagnosis_result_service.upsert_diagnosis_result_from_ai(
        db,
        task=task,
        payload=DiagnosisResultPayload(summary="first result", root_cause="R1"),
        actor_user_id=task.creator_id,
    )

    # 卡片生成后，会话又追加了两条回复
    for index in range(2):
        task_service.save_chat_message(
            db,
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            role="assistant",
            content=f"later-chunk-{index}",
            message_type="text",
        )

    # 一键总结再次更新定位结果，卡片应移动到会话最后
    diagnosis_result_service.upsert_diagnosis_result_from_ai(
        db,
        task=task,
        payload=DiagnosisResultPayload(summary="updated summary", root_cause="R2"),
        actor_user_id=task.creator_id,
    )

    same_time = datetime.utcnow()
    db.query(ChatMessage).filter(ChatMessage.task_id == task.id).update(
        {"created_at": same_time}
    )
    db.commit()

    history = task_service.get_task_history(db, task.id, task.workspace_id)
    types = [m["type"] for m in history.get("messages", [])]
    assert types == [
        "text",
        "text",
        "text",
        "text",
        "text",
        MessageType.DIAGNOSIS_RESULT.value,
    ]
    assert history["messages"][-1]["metadata"]["summary"] == "updated summary"
