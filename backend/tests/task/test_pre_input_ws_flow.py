"""协作预输入 WebSocket 全链路集成测试：发起 → 框选 → 手动提交 / 非发起人提交报错。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.domains.ai.models.ai_job
import app.domains.api_mock.models.api_mock
import app.domains.task.models.test_result
import app.domains.workflow.models.provision_job
import app.domains.workflow.models.task_change
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401
import app.main as main_module
from app.config import settings
from app.database import Base
from app.domains.ai.services.jobs import (
    publishing as ai_publishing,
)
from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.domains.auth.services import auth_service
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import chat_submission_service, pre_input_worker, task_event_publisher
from app.domains.websocket.ws import task_handler
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db


def _receive_business(websocket):
    while True:
        frame = websocket.receive_json()
        frame_type = frame.get("type")
        if frame_type == "resync_required":
            websocket.send_json(
                {
                    "type": "resync_complete",
                    "payload": {
                        "epoch": frame["epoch"],
                        "barrier_sequence": frame["barrier_sequence"],
                    },
                }
            )
            continue
        if frame_type in {"resync_ok", "resume_ok"}:
            continue
        if frame_type == "event":
            return {"type": frame["event_type"], "payload": frame.get("payload")}
        return frame


def _complete_initial_sync(websocket):
    frame = websocket.receive_json()
    assert frame["type"] == "resync_required"
    websocket.send_json(
        {
            "type": "resync_complete",
            "payload": {
                "epoch": frame["epoch"],
                "barrier_sequence": frame["barrier_sequence"],
            },
        }
    )
    assert websocket.receive_json()["type"] == "resync_ok"


def _seed(db, project_path: str):
    owner = User(id="u-owner", email="owner@example.com", hashed_password="x", display_name="Owner")
    member = User(id="u-member", email="member@example.com", hashed_password="x", display_name="Member")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=owner.id)
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=owner.id,
        name="Task",
        project_path=project_path,
        status=TaskStatus.RUNNING,
    )
    rows = [owner, member, workspace, task]
    for user in (owner, member):
        rows.append(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.DEVELOPER,
                is_expert=False,
            )
        )
    db.add_all(rows)
    db.commit()


@pytest.fixture()
def ws_env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SEARCH_WORKERS_ENABLED", False)
    engine = create_engine(f"sqlite:///{tmp_path / 'pre_input.db'}")
    Base.metadata.create_all(engine)

    task_root = tmp_path / "task-1"
    task_root.mkdir()
    monkeypatch.setattr(
        settings,
        "TASK_SESSION_SNAPSHOT_ROOT",
        str(tmp_path / "snapshots"),
    )

    # manager 是进程级单例：清掉此前用例留下的连接与房间 journal，避免事件串扰
    main_module.manager.registry.reset()

    # 独立 session 和连接，避免 offload 线程与测试主线程共用 SQLite 事务。
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    test_session = factory()

    monkeypatch.setattr(main_module, "SessionLocal", factory)
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr(pre_input_worker, "SessionLocal", factory)
    # offload 层（run_db/run_db_txn）在线程内从 app.database 惰性导入 SessionLocal
    monkeypatch.setattr("app.database.SessionLocal", factory)

    # outbox 发布器：测试不跑后台循环，wake 即同步补发一轮
    async def _publish_on_wake():
        while await task_event_publisher.publish_once():
            pass

    monkeypatch.setattr(task_event_publisher, "start", lambda: None)
    monkeypatch.setattr(chat_submission_service, "wake_event_publisher", _publish_on_wake)

    async def _noop_enqueue(job_id):
        return None

    monkeypatch.setattr(ai_publishing, "enqueue_task_chat_job", _noop_enqueue)

    async def _noop_worker(stop_event=None):
        return None

    monkeypatch.setattr(main_module.pre_input_deadline_worker, "run_pre_input_worker", _noop_worker)
    monkeypatch.setattr(task_handler, "get_engine", lambda task_id: None)

    # token 直接携带用户 id，绕开 JWT 签发
    monkeypatch.setattr(
        auth_service,
        "decode_token",
        lambda token, expected_type=None: {"sub": str(token)},
    )

    _seed(test_session, str(task_root))
    try:
        yield test_session
    finally:
        test_session.close()
        engine.dispose()
        main_module.manager.registry.reset()


def test_ws_pre_input_full_flow(ws_env):
    with TestClient(main_module.app) as client:
        # 1) 发起人连接并发起预输入
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            _complete_initial_sync(owner_ws)
            owner_ws.send_json(
                {
                    "type": "pre_input_create",
                    "payload": {
                        "main_text": "hello world",
                        "mentioned_user_ids": ["u-member"],
                        "edit_permission": "ALL",
                        "wait_seconds": 180,
                    },
                }
            )
            evt = _receive_business(owner_ws)
            assert evt["type"] == "pre_input_update"
            assert evt["payload"]["status"] == "COLLECTING"
            assert evt["payload"]["document_segments"][0]["text"] == "hello world"

            # 2) 发起人框选 world → traceforge
            owner_ws.send_json(
                {
                    "type": "pre_input_replace_span",
                    "payload": {"start": 6, "end": 11, "anchor_text": "world", "replacement": "traceforge"},
                }
            )
            evt = _receive_business(owner_ws)
            assert evt["type"] == "pre_input_update"
            joined = "".join(s["text"] for s in evt["payload"]["document_segments"])
            assert joined == "hello traceforge"

            # 3) 立即提交（发起人）
            pre_input_id = evt["payload"]["id"]
            owner_ws.send_json({"type": "pre_input_submit", "payload": {"pre_input_id": pre_input_id}})
            accepted = _receive_business(owner_ws)
            assert accepted["type"] == "chat_submission_update"
            assert accepted["payload"]["receipt"]["status"] == "PREPARING"
            assert accepted["payload"]["receipt"]["client_message_id"] == f"pre-input:{pre_input_id}"
            done_evt = _receive_business(owner_ws)
            assert done_evt["type"] == "pre_input_submitted"
            assert done_evt["payload"]["status"] == "SUBMITTED"
            chat_evt = _receive_business(owner_ws)
            while chat_evt["type"] == "task_status_changed":
                chat_evt = _receive_business(owner_ws)
            assert chat_evt["type"] == "chat_submission_update"
            assert chat_evt["payload"]["receipt"]["status"] == "EXECUTING"
            message = chat_evt["payload"]["message"]
            assert message["content"] == "hello traceforge"
            assert message["metadata"]["segments"]

            # Retrying the original submit while the next document is open
            # must leave the new document editable.
            owner_ws.send_json({"type": "pre_input_create", "payload": {"main_text": "next document"}})
            next_input = _receive_business(owner_ws)["payload"]
            assert next_input["id"] != pre_input_id
            owner_ws.send_json({"type": "pre_input_submit", "payload": {"pre_input_id": pre_input_id}})
            owner_ws.send_json({"type": "pre_input_edit_document", "payload": {"text": "next document edited"}})
            next_update = _receive_business(owner_ws)
            assert next_update["type"] == "pre_input_update"
            assert next_update["payload"]["id"] == next_input["id"]
            assert next_update["payload"]["status"] == "COLLECTING"
            assert next_update["payload"]["main_text"] == "next document edited"


def test_ws_chat_message_persists_receipt_before_background_preparation(ws_env, monkeypatch):
    from app.domains.ai.models.ai_job import SddAiJob
    from app.domains.task.models.chat import ChatMessage
    from app.domains.task.models.chat_submission import TaskChatSubmission
    from app.domains.task.services import chat_submission_service

    scheduled = []
    monkeypatch.setattr(chat_submission_service, "schedule", scheduled.append)
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            _complete_initial_sync(owner_ws)
            owner_ws.send_json(
                {
                    "type": "chat_message",
                    "payload": {
                        "content": "hello agent",
                        "client_message_id": "client-1",
                    },
                }
            )
            event = _receive_business(owner_ws)
            assert event["type"] == "chat_submission_update"
            assert event["payload"]["receipt"]["status"] == "PREPARING"
            assert event["payload"]["receipt"]["client_message_id"] == "client-1"
            receipt_id = event["payload"]["receipt"]["id"]
            assert ws_env.get(TaskChatSubmission, receipt_id).content == "hello agent"
            assert ws_env.query(ChatMessage).count() == ws_env.query(SddAiJob).count() == 0
    assert receipt_id in scheduled


def test_ws_chat_message_broadcasts_submission_to_second_client(ws_env, monkeypatch):
    from app.domains.ai.models.ai_job import SddAiJob
    from app.domains.task.models.chat import ChatMessage
    from app.domains.task.models.chat_submission import TaskChatSubmission
    from app.domains.task.services import chat_submission_service

    scheduled = []
    monkeypatch.setattr(chat_submission_service, "schedule", scheduled.append)
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as sender_ws:
            _complete_initial_sync(sender_ws)
            with client.websocket_connect("/ws/task/task-1?token=u-member") as observer_ws:
                _complete_initial_sync(observer_ws)
                sender_ws.send_json(
                    {
                        "type": "chat_message",
                        "payload": {
                            "content": "hello from client A",
                            "client_message_id": "client-a-message",
                        },
                    }
                )

                # Read from B: a sender-only acknowledgement cannot satisfy this.
                event = _receive_business(observer_ws)
                assert event["type"] == "chat_submission_update"
                payload = event["payload"]
                assert payload["task_id"] == "task-1"
                assert payload["event_id"]
                receipt = payload["receipt"]
                assert receipt["client_message_id"] == "client-a-message"
                assert receipt["creator_id"] == "u-owner"
                assert receipt["status"] == "PREPARING"
                assert receipt["version"] == 1
                row = ws_env.get(TaskChatSubmission, receipt["id"])
                assert row is not None and row.client_message_id == "client-a-message"
                assert ws_env.query(ChatMessage).count() == ws_env.query(SddAiJob).count() == 0
    assert receipt["id"] in scheduled


def test_ws_pre_input_unexpected_error_returns_error_event(ws_env, monkeypatch):
    async def _fail_submit(*args, **kwargs):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(task_handler.pre_input_service, "submit_pre_input", _fail_submit)

    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            _complete_initial_sync(owner_ws)
            owner_ws.send_json(
                {
                    "type": "pre_input_create",
                    "payload": {
                        "main_text": "hello world",
                        "mentioned_user_ids": [],
                        "edit_permission": "ALL",
                        "wait_seconds": 180,
                    },
                }
            )
            assert _receive_business(owner_ws)["type"] == "pre_input_update"

            owner_ws.send_json({"type": "pre_input_submit", "payload": {}})
            evt = _receive_business(owner_ws)
            assert evt["type"] == "pre_input_error"
            assert evt["payload"]["action"] == "pre_input_submit"
            assert evt["payload"]["message"] == "Failed to process pre input"

            # 单条消息处理失败不应终止整个 WebSocket 会话。
            owner_ws.send_json(
                {
                    "type": "pre_input_edit_document",
                    "payload": {"text": "still connected"},
                }
            )
            update_evt = _receive_business(owner_ws)
            assert update_evt["type"] == "pre_input_update"


def test_ws_pre_input_submit_rejected_for_non_creator(ws_env):
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            _complete_initial_sync(owner_ws)
            owner_ws.send_json(
                {
                    "type": "pre_input_create",
                    "payload": {
                        "main_text": "hello world",
                        "mentioned_user_ids": [],
                        "edit_permission": "ALL",
                        "wait_seconds": 180,
                    },
                }
            )
            assert _receive_business(owner_ws)["type"] == "pre_input_update"

        # 非发起人提交 → pre_input_error
        with client.websocket_connect("/ws/task/task-1?token=u-member") as member_ws:
            _complete_initial_sync(member_ws)
            member_ws.send_json({"type": "pre_input_submit", "payload": {}})
            evt = member_ws.receive_json()
            assert evt["type"] == "pre_input_error"
            assert "creator" in evt["payload"]["message"]


def test_ws_pre_input_edit_document_flow(ws_env):
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-member") as member_ws:
            _complete_initial_sync(member_ws)
            # 无进行中预输入 → 报错
            member_ws.send_json({"type": "pre_input_edit_document", "payload": {"text": "x"}})
            evt = member_ws.receive_json()
            assert evt["type"] == "pre_input_error"

        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            _complete_initial_sync(owner_ws)
            owner_ws.send_json(
                {
                    "type": "pre_input_create",
                    "payload": {
                        "main_text": "hello world",
                        "mentioned_user_ids": [],
                        "edit_permission": "ALL",
                        "wait_seconds": 180,
                    },
                }
            )
            assert _receive_business(owner_ws)["type"] == "pre_input_update"

        with client.websocket_connect("/ws/task/task-1?token=u-member") as member_ws:
            _complete_initial_sync(member_ws)
            member_ws.send_json({"type": "pre_input_edit_document", "payload": {"text": "hello brave world"}})
            evt = _receive_business(member_ws)
            assert evt["type"] == "pre_input_update"
            joined = "".join(s["text"] for s in evt["payload"]["document_segments"])
            assert joined == "hello brave world"
