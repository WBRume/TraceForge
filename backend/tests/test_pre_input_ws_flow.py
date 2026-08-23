"""协作预输入 WebSocket 全链路集成测试：发起 → 框选 → 手动提交 / 非发起人提交报错。"""

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient
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
from app.domains.auth.models.user import (  # noqa: E402
    User, Workspace, WorkspaceMember, WorkspaceRole,
)
from app.domains.auth.services import auth_service  # noqa: E402
from app.domains.ai.services import ai_job_service  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
import app.main as main_module  # noqa: E402
from app.domains.task.services import pre_input_worker  # noqa: E402


def _seed(db):
    owner = User(id="u-owner", email="owner@example.com", hashed_password="x", display_name="Owner")
    member = User(id="u-member", email="member@example.com", hashed_password="x", display_name="Member")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=owner.id)
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=owner.id,
        name="Task",
        project_path="G:/tmp/task-1",
        status=TaskStatus.CODING,
    )
    rows = [owner, member, workspace, task]
    for user in (owner, member):
        rows.append(WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.DEVELOPER,
            is_expert=False,
        ))
    db.add_all(rows)
    db.commit()


@pytest.fixture()
def ws_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)()

    # manager 是进程级单例：清掉此前用例留下的连接与离线缓冲，避免事件串扰
    main_module.manager.active_connections.clear()
    main_module.manager.pending_payloads.clear()

    monkeypatch.setattr(main_module, "SessionLocal", lambda: test_session)
    monkeypatch.setattr(ai_job_service, "SessionLocal", lambda: test_session)
    monkeypatch.setattr(pre_input_worker, "SessionLocal", lambda: test_session)

    async def _noop_enqueue(job_id):
        return None

    monkeypatch.setattr(ai_job_service, "enqueue_task_chat_job", _noop_enqueue)

    async def _noop_worker(stop_event=None):
        return None

    monkeypatch.setattr(main_module.pre_input_deadline_worker, "run_pre_input_worker", _noop_worker)
    monkeypatch.setattr(main_module, "get_engine", lambda task_id: None)

    # token 直接携带用户 id，绕开 JWT 签发
    monkeypatch.setattr(
        auth_service,
        "decode_token",
        lambda token, expected_type=None: {"sub": str(token)},
    )

    _seed(test_session)
    yield test_session

    main_module.manager.active_connections.clear()
    main_module.manager.pending_payloads.clear()


def test_ws_pre_input_full_flow(ws_env):
    with TestClient(main_module.app) as client:
        # 1) 发起人连接并发起预输入
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            owner_ws.send_json({
                "type": "pre_input_create",
                "payload": {
                    "main_text": "hello world",
                    "mentioned_user_ids": ["u-member"],
                    "edit_permission": "ALL",
                    "wait_seconds": 180,
                },
            })
            evt = owner_ws.receive_json()
            assert evt["type"] == "pre_input_update"
            assert evt["payload"]["status"] == "COLLECTING"
            assert evt["payload"]["document_segments"][0]["text"] == "hello world"

            # 2) 发起人框选 world → traceforge
            owner_ws.send_json({
                "type": "pre_input_replace_span",
                "payload": {"start": 6, "end": 11, "anchor_text": "world", "replacement": "traceforge"},
            })
            evt = owner_ws.receive_json()
            assert evt["type"] == "pre_input_update"
            joined = "".join(s["text"] for s in evt["payload"]["document_segments"])
            assert joined == "hello traceforge"

            # 3) 立即提交（发起人）
            owner_ws.send_json({"type": "pre_input_submit", "payload": {}})
            chat_evt = owner_ws.receive_json()
            assert chat_evt["type"] == "chat_message"
            # 内容 = 文档原文，无拼接标签
            assert chat_evt["payload"]["content"] == "hello traceforge"
            assert chat_evt["payload"]["metadata"]["segments"]
            done_evt = owner_ws.receive_json()
            assert done_evt["type"] == "pre_input_submitted"
            assert done_evt["payload"]["status"] == "SUBMITTED"


def test_ws_pre_input_submit_rejected_for_non_creator(ws_env):
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            owner_ws.send_json({
                "type": "pre_input_create",
                "payload": {"main_text": "hello world", "mentioned_user_ids": [], "edit_permission": "ALL", "wait_seconds": 180},
            })
            assert owner_ws.receive_json()["type"] == "pre_input_update"

        # 非发起人提交 → pre_input_error
        with client.websocket_connect("/ws/task/task-1?token=u-member") as member_ws:
            member_ws.send_json({"type": "pre_input_submit", "payload": {}})
            evt = member_ws.receive_json()
            assert evt["type"] == "pre_input_error"
            assert "creator" in evt["payload"]["message"]


def test_ws_pre_input_edit_document_flow(ws_env):
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-member") as member_ws:
            # 无进行中预输入 → 报错
            member_ws.send_json({"type": "pre_input_edit_document", "payload": {"text": "x"}})
            evt = member_ws.receive_json()
            assert evt["type"] == "pre_input_error"

        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner_ws:
            owner_ws.send_json({
                "type": "pre_input_create",
                "payload": {"main_text": "hello world", "mentioned_user_ids": [], "edit_permission": "ALL", "wait_seconds": 180},
            })
            assert owner_ws.receive_json()["type"] == "pre_input_update"

        with client.websocket_connect("/ws/task/task-1?token=u-member") as member_ws:
            member_ws.send_json({"type": "pre_input_edit_document", "payload": {"text": "hello brave world"}})
            evt = member_ws.receive_json()
            assert evt["type"] == "pre_input_update"
            joined = "".join(s["text"] for s in evt["payload"]["document_segments"])
            assert joined == "hello brave world"
