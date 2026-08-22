import asyncio
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
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole  # noqa: E402
from app.domains.notification.models.notification import SddUserNotification  # noqa: E402
from app.domains.task.models.pre_input import (  # noqa: E402
    PreInputEditPermission,
    PreInputStatus,
    SddTaskPreInput,
)
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.task.services import pre_input_service  # noqa: E402


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


def _seed(db, *, task_status=TaskStatus.CODING, expert_ids=()):
    owner = User(id="u-owner", email="owner@example.com", hashed_password="x", display_name="Owner")
    member = User(id="u-member", email="member@example.com", hashed_password="x", display_name="Member")
    expert = User(id="u-expert", email="expert@example.com", hashed_password="x", display_name="Expert")
    outsider = User(id="u-out", email="out@example.com", hashed_password="x", display_name="Outsider")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=owner.id)
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=owner.id,
        name="Task",
        project_path="G:/tmp/task-1",
        status=task_status,
    )
    rows = [owner, member, expert, outsider, workspace, task]
    for user in (owner, member, expert):
        rows.append(WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.DEVELOPER,
            is_expert=user.id in expert_ids or user.id == "u-expert",
        ))
    db.add_all(rows)
    db.commit()
    return {"task": task, "workspace": workspace}


def _create(db, task, **kwargs):
    payload = {
        "task": task,
        "creator_id": "u-owner",
        "main_text": "please review the plan",
        "mentioned_user_ids": ["u-member"],
        "edit_permission": "NONE",
        "wait_seconds": 180,
    }
    payload.update(kwargs)
    return asyncio.run(pre_input_service.create_pre_input(db, **payload))


def test_create_pre_input_rejects_duplicate_and_non_member_mention(db_session):
    db = db_session
    seeded = _seed(db)
    task = seeded["task"]

    pre_input = _create(db, task)
    assert pre_input.status == PreInputStatus.COLLECTING
    assert pre_input.mentioned_user_ids == ["u-member"]

    with pytest.raises(pre_input_service.PreInputError) as exc:
        _create(db, task)
    assert exc.value.status_code == 409

    task.status = TaskStatus.INTERRUPTED
    db.commit()
    # 先取消再重建，验证非成员@被拒绝
    asyncio.run(pre_input_service.cancel_pre_input(db, pre_input=pre_input, actor_user_id="u-owner"))
    with pytest.raises(pre_input_service.PreInputError):
        _create(db, task, mentioned_user_ids=["u-out"])


def test_create_pre_input_rejects_terminal_task(db_session):
    db = db_session
    seeded = _seed(db, task_status=TaskStatus.DONE)
    with pytest.raises(pre_input_service.PreInputError):
        _create(db, seeded["task"])


def test_create_dispatches_mention_notifications(db_session):
    db = db_session
    seeded = _seed(db)
    _create(db, seeded["task"], mentioned_user_ids=["u-member", "u-expert"])

    notifications = db.query(SddUserNotification).all()
    recipients = {n.recipient_user_id for n in notifications}
    assert recipients == {"u-member", "u-expert"}
    assert all(n.type == "pre_input_mention" for n in notifications)


def test_upsert_contribution_auto_submits_when_all_mentioned_done(db_session, monkeypatch):
    db = db_session
    seeded = _seed(db)
    task = seeded["task"]

    async def _noop_enqueue(job_id):
        return None

    monkeypatch.setattr(pre_input_service.ai_job_service, "enqueue_task_chat_job", _noop_enqueue)

    pre_input = _create(db, task, mentioned_user_ids=["u-member", "u-expert"])
    result = asyncio.run(pre_input_service.upsert_contribution(
        db, pre_input=pre_input, user_id="u-member", content="looks good",
    ))
    assert result["auto_submitted"] is False
    assert pre_input_service.get_active_pre_input(db, task.id) is not None

    result = asyncio.run(pre_input_service.upsert_contribution(
        db, pre_input=pre_input, user_id="u-expert", content="expert note",
    ))
    assert result["auto_submitted"] is True
    assert result["submission"]["chat_message_id"]
    assert pre_input_service.get_active_pre_input(db, task.id) is None

    db.refresh(pre_input)
    assert pre_input.status == PreInputStatus.SUBMITTED
    assert pre_input.submit_reason == "all_done"


def test_submit_cas_prevents_double_submission(db_session, monkeypatch):
    db = db_session
    seeded = _seed(db)
    task = seeded["task"]

    async def _noop_enqueue(job_id):
        return None

    monkeypatch.setattr(pre_input_service.ai_job_service, "enqueue_task_chat_job", _noop_enqueue)

    pre_input = _create(db, task, mentioned_user_ids=[])
    first = asyncio.run(pre_input_service.submit_pre_input(
        db, pre_input=pre_input, actor_user_id="u-owner", reason="manual",
    ))
    assert first is not None

    db.refresh(pre_input)
    second = asyncio.run(pre_input_service.submit_pre_input(
        db, pre_input=pre_input, actor_user_id="u-owner", reason="timeout",
    ))
    assert second is None


def test_merged_content_and_metadata(db_session, monkeypatch):
    db = db_session
    seeded = _seed(db)
    task = seeded["task"]

    async def _noop_enqueue(job_id):
        return None

    monkeypatch.setattr(pre_input_service.ai_job_service, "enqueue_task_chat_job", _noop_enqueue)

    pre_input = _create(db, task, mentioned_user_ids=["u-member", "u-expert"], edit_permission="ALL")
    asyncio.run(pre_input_service.upsert_contribution(db, pre_input=pre_input, user_id="u-member", content="member says hi"))
    asyncio.run(pre_input_service.upsert_contribution(db, pre_input=pre_input, user_id="u-expert", content="expert says hi"))
    asyncio.run(pre_input_service.submit_pre_input(db, pre_input=pre_input, actor_user_id="u-owner", reason="manual"))

    from app.domains.task.models.chat import ChatMessage

    message = db.query(ChatMessage).filter(ChatMessage.task_id == task.id).one()
    assert message.role == "user"
    assert "[发起] Owner：please review the plan" in message.content
    assert "[输入] Member：member says hi" in message.content
    assert "[输入] Expert（专家）：expert says hi" in message.content
    metadata = message.metadata_json
    assert metadata["pre_input_id"] == pre_input.id
    contributed = {p["user_id"]: p["contributed"] for p in metadata["participants"]}
    assert contributed == {"u-owner": True, "u-member": True, "u-expert": True}
    # 结构化分段（前端协作气泡渲染依据）：发起人主文本 + 各成员输入段
    segments = {(s["user_id"], s["content"]) for s in metadata["segments"]}
    assert ("u-owner", "please review the plan") in segments
    assert ("u-member", "member says hi") in segments
    assert ("u-expert", "expert says hi") in segments
    assert all(s.get("display_name") for s in metadata["segments"])


def test_edit_permission_matrix(db_session):
    db = db_session
    seeded = _seed(db)

    async def _edit_main(pre_input, actor_user_id, actor_is_expert, text):
        return await pre_input_service.edit_main_text(
            db,
            pre_input=pre_input,
            actor_user_id=actor_user_id,
            actor_is_expert=actor_is_expert,
            main_text=text,
        )

    async def _close(pre_input):
        await pre_input_service.cancel_pre_input(db, pre_input=pre_input, actor_user_id="u-owner")

    # NONE：仅发起人可编辑
    pre_input = _create(db, seeded["task"], edit_permission="NONE")
    with pytest.raises(pre_input_service.PreInputError):
        asyncio.run(_edit_main(pre_input, "u-member", False, "x"))
    asyncio.run(_edit_main(pre_input, "u-owner", False, "owner text"))
    db.refresh(pre_input)
    assert pre_input.main_text == "owner text"
    asyncio.run(_close(pre_input))

    # MENTIONED：被@成员可编辑
    pre_input = _create(db, seeded["task"], edit_permission="MENTIONED")
    with pytest.raises(pre_input_service.PreInputError):
        asyncio.run(_edit_main(pre_input, "u-expert", True, "x"))
    asyncio.run(_edit_main(pre_input, "u-member", False, "member text"))
    asyncio.run(_close(pre_input))

    # EXPERTS：仅专家可编辑
    pre_input = _create(db, seeded["task"], edit_permission="EXPERTS")
    with pytest.raises(pre_input_service.PreInputError):
        asyncio.run(_edit_main(pre_input, "u-member", False, "x"))
    asyncio.run(_edit_main(pre_input, "u-expert", True, "expert text"))
    asyncio.run(_close(pre_input))

    # ALL：任何成员可编辑（WS 层保证是工作区成员）
    pre_input = _create(db, seeded["task"], edit_permission="ALL")
    asyncio.run(_edit_main(pre_input, "u-member", False, "anyone text"))


def test_edit_other_contribution_requires_permission(db_session):
    db = db_session
    seeded = _seed(db)
    # @两个成员，单人提交不会触发全员完成自动提交，保持窗口打开
    pre_input = _create(db, seeded["task"], mentioned_user_ids=["u-member", "u-expert"], edit_permission="NONE")
    asyncio.run(pre_input_service.upsert_contribution(db, pre_input=pre_input, user_id="u-member", content="original"))

    with pytest.raises(pre_input_service.PreInputError):
        asyncio.run(pre_input_service.edit_contribution(
            db, pre_input=pre_input, actor_user_id="u-expert", actor_is_expert=True,
            target_user_id="u-member", content="hijack",
        ))
    # 本人始终可编辑自己的段
    asyncio.run(pre_input_service.edit_contribution(
        db, pre_input=pre_input, actor_user_id="u-member", actor_is_expert=False,
        target_user_id="u-member", content="updated by self",
    ))
    db.refresh(pre_input)
    contents = {c.user_id: c.content for c in pre_input.contributions}
    assert contents["u-member"] == "updated by self"


def test_cancel_only_by_creator(db_session):
    db = db_session
    seeded = _seed(db)
    pre_input = _create(db, seeded["task"])

    with pytest.raises(pre_input_service.PreInputError):
        asyncio.run(pre_input_service.cancel_pre_input(db, pre_input=pre_input, actor_user_id="u-member"))

    asyncio.run(pre_input_service.cancel_pre_input(db, pre_input=pre_input, actor_user_id="u-owner"))
    db.refresh(pre_input)
    assert pre_input.status == PreInputStatus.CANCELLED


def test_serialize_member_status(db_session, monkeypatch):
    db = db_session
    seeded = _seed(db)

    async def _noop_enqueue(job_id):
        return None

    monkeypatch.setattr(pre_input_service.ai_job_service, "enqueue_task_chat_job", _noop_enqueue)

    pre_input = _create(db, seeded["task"], mentioned_user_ids=["u-member", "u-expert"])
    asyncio.run(pre_input_service.upsert_contribution(db, pre_input=pre_input, user_id="u-member", content="done part"))
    asyncio.run(pre_input_service.upsert_contribution(db, pre_input=pre_input, user_id="u-expert", content="expert part"))

    payload = pre_input_service.serialize_pre_input(db, pre_input)
    assert payload["all_mentioned_done"] is True
    statuses = {m["user_id"]: m["done"] for m in payload["mentionees"]}
    assert statuses == {"u-member": True, "u-expert": True}
    assert payload["creator"]["display_name"] == "Owner"
    assert payload["volunteers"] == []
    # 专家标记透传
    expert_row = next(m for m in payload["mentionees"] if m["user_id"] == "u-expert")
    assert expert_row["is_expert"] is True
