import asyncio
import os
import sys

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
from app.domains.task.models.pre_input import PreInputStatus  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.task.services import pre_input_service  # noqa: E402


@pytest.fixture()
def session_factory(monkeypatch):
    """SQLite 内存库 + 静态连接池；替换 app.database.SessionLocal
    使 run_db / run_db_txn 的线程内 session 落在同一个内存库上。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def db_session(session_factory):
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def _seed(db, *, task_status=TaskStatus.CODING):
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
            is_expert=user.id == "u-expert",
        ))
    db.add_all(rows)
    db.commit()
    return {"task": task, "workspace": workspace}


def _create(**kwargs):
    payload = {
        "task_id": "task-1",
        "creator_id": "u-owner",
        "main_text": "hello world",
        "mentioned_user_ids": ["u-member"],
        "edit_permission": "NONE",
        "wait_seconds": 180,
    }
    payload.update(kwargs)
    return asyncio.run(pre_input_service.create_pre_input(**payload))


def _get(db, pre_input_id):
    return pre_input_service.get_pre_input(db, pre_input_id)


def _edit(pre_input_id, user_id, is_expert, text):
    return asyncio.run(pre_input_service.edit_pre_input_document(
        pre_input_id=pre_input_id, task_id="task-1",
        user_id=user_id, is_expert=is_expert, new_text=text,
    ))


def _replace_span(pre_input_id, user_id, is_expert, start, end, anchor, replacement):
    return asyncio.run(pre_input_service.replace_pre_input_span(
        pre_input_id=pre_input_id, task_id="task-1",
        user_id=user_id, is_expert=is_expert,
        start=start, end=end, anchor_text=anchor, replacement=replacement,
    ))


@pytest.fixture(autouse=True)
def _noop_enqueue(monkeypatch, tmp_path):
    async def _noop(job_id):
        return None

    checkpoint_index = 0

    async def _fake_checkpoint(*_args, **_kwargs):
        nonlocal checkpoint_index
        checkpoint_index += 1
        root = tmp_path / f"checkpoint-{checkpoint_index}"
        root.mkdir()
        return {"root": str(root), "worktree": {}, "provider": {}}

    async def _fake_cleanup(_path):
        return None

    monkeypatch.setattr(pre_input_service.ai_job_service, "enqueue_task_chat_job", _noop)
    monkeypatch.setattr(
        pre_input_service.task_session_service.task_session_snapshot_service,
        "create_checkpoint",
        _fake_checkpoint,
    )
    monkeypatch.setattr(
        pre_input_service.task_session_service.task_session_snapshot_service,
        "cleanup_checkpoint",
        _fake_cleanup,
    )


def test_create_initializes_document_with_creator_attribution(db_session):
    db = db_session
    _seed(db)
    created = _create()

    pre_input = _get(db, created["pre_input_id"])
    segments = pre_input_service._document_segments(pre_input)
    assert pre_input_service._document_text(segments) == "hello world"
    assert all(s["created_by"] == "u-owner" and s["updated_by"] == "u-owner" for s in segments)
    participants = [c.user_id for c in pre_input.contributions]
    assert "u-owner" in participants


def test_create_rejects_duplicate_and_non_member_mention(db_session):
    db = db_session
    seeded = _seed(db)
    task = seeded["task"]

    created = _create()
    pre_input = _get(db, created["pre_input_id"])
    assert pre_input.status == PreInputStatus.COLLECTING

    with pytest.raises(pre_input_service.PreInputError) as exc:
        _create()
    assert exc.value.status_code == 409

    task.status = TaskStatus.INTERRUPTED
    db.commit()
    asyncio.run(pre_input_service.cancel_pre_input(
        pre_input_id=created["pre_input_id"], task_id="task-1", actor_user_id="u-owner",
    ))
    with pytest.raises(pre_input_service.PreInputError):
        _create(mentioned_user_ids=["u-out"])


def test_create_rejects_terminal_task(db_session):
    db = db_session
    _seed(db, task_status=TaskStatus.DONE)
    with pytest.raises(pre_input_service.PreInputError):
        _create()


def test_create_dispatches_mention_notifications(db_session):
    db = db_session
    _seed(db)
    _create(mentioned_user_ids=["u-member", "u-expert"])

    notifications = db.query(SddUserNotification).all()
    recipients = {n.recipient_user_id for n in notifications}
    assert recipients == {"u-member", "u-expert"}


def test_insert_text_allowed_for_any_member_char_level(db_session):
    db = db_session
    _seed(db)
    # @的是尚未参与的 u-expert，避免成员编辑后触发全员参与自动提交
    created = _create(mentioned_user_ids=["u-expert"], edit_permission="NONE")
    pre_input_id = created["pre_input_id"]

    # 句中插字 / 句尾追加，均为 insert，无需权限
    result = _edit(pre_input_id, "u-member", False, "hello brave world")
    assert result["auto_submitted"] is False

    pre_input = _get(db, pre_input_id)
    segments = pre_input_service._document_segments(pre_input)
    assert pre_input_service._document_text(segments) == "hello brave world"
    # 字符级归属：新增字符全部归属编辑者，原文文字保留发起人
    member_chars = "".join(s["text"] for s in segments if s["created_by"] == "u-member")
    owner_chars = "".join(s["text"] for s in segments if s["created_by"] == "u-owner")
    assert member_chars.strip() == "brave"
    assert "hello" in owner_chars and "world" in owner_chars


def test_modify_text_requires_permission_char_level(db_session):
    db = db_session
    seeded = _seed(db)
    created = _create(mentioned_user_ids=[], edit_permission="NONE")
    pre_input_id = created["pre_input_id"]
    # world → trace：替换已有字符，需要权限
    with pytest.raises(pre_input_service.PreInputError) as exc:
        _edit(pre_input_id, "u-member", False, "hello trace")
    assert exc.value.status_code == 403

    asyncio.run(pre_input_service.cancel_pre_input(
        pre_input_id=pre_input_id, task_id="task-1", actor_user_id="u-owner",
    ))
    created = _create(mentioned_user_ids=[], edit_permission="EXPERTS")
    pre_input_id = created["pre_input_id"]
    _edit(pre_input_id, "u-expert", True, "hello trace")
    pre_input = _get(db, pre_input_id)
    segments = pre_input_service._document_segments(pre_input)
    assert pre_input_service._document_text(segments) == "hello trace"
    # 字符级双归属：被改字符可见修改者；未动字符保持原作者且修改者不变
    expert_touched = "".join(s["text"] for s in segments if s["updated_by"] == "u-expert")
    untouched = "".join(s["text"] for s in segments if s["updated_by"] == "u-owner")
    assert expert_touched  # 专家的修改在文档中可见
    assert untouched.startswith("hello")
    assert all(s["created_by"] == "u-owner" for s in segments if s["updated_by"] == "u-owner")


def test_replace_span_box_selection(db_session):
    db = db_session
    _seed(db)
    created = _create(mentioned_user_ids=["u-expert"], edit_permission="EXPERTS")
    pre_input_id = created["pre_input_id"]

    # 框选 "world" 替换为 "traceforge"：与原文等长的 "trace" 保留原作者，多出的 "forge" 归专家
    _replace_span(pre_input_id, "u-expert", True, 6, 11, "world", "traceforge")
    pre_input = _get(db, pre_input_id)
    segments = pre_input_service._document_segments(pre_input)
    assert pre_input_service._document_text(segments) == "hello traceforge"
    head = segments[0]
    assert head["text"] == "hello " and head["created_by"] == "u-owner" and head["updated_by"] == "u-owner"
    trace = next(s for s in segments if s["text"] == "trace")
    assert trace["created_by"] == "u-owner"
    assert trace["updated_by"] == "u-expert"
    forge = next(s for s in segments if s["text"] == "forge")
    assert forge["created_by"] == "u-expert"
    assert forge["updated_by"] == "u-expert"


def test_replace_span_insert_anyone_replace_needs_permission(db_session):
    db = db_session
    _seed(db)
    created = _create(mentioned_user_ids=["u-expert"], edit_permission="NONE")
    pre_input_id = created["pre_input_id"]

    # 纯插入（start==end）：无权限成员也可
    _replace_span(pre_input_id, "u-member", False, 5, 5, "", " brave")
    pre_input = _get(db, pre_input_id)
    assert pre_input_service._document_text(
        pre_input_service._document_segments(pre_input)
    ) == "hello brave world"

    # 替换所选：无权限 → 403
    with pytest.raises(pre_input_service.PreInputError) as exc:
        _replace_span(pre_input_id, "u-member", False, 6, 11, "brave", "bold")
    assert exc.value.status_code == 403


def test_replace_span_rejects_stale_anchor(db_session):
    db = db_session
    _seed(db)
    created = _create(mentioned_user_ids=[], edit_permission="ALL")
    with pytest.raises(pre_input_service.PreInputError) as exc:
        _replace_span(created["pre_input_id"], "u-expert", True, 6, 11, "WRONG", "x")
    assert exc.value.status_code == 409


def test_delete_text_requires_permission(db_session):
    db = db_session
    _seed(db)
    created = _create(mentioned_user_ids=[], edit_permission="NONE")
    pre_input_id = created["pre_input_id"]
    with pytest.raises(pre_input_service.PreInputError):
        _edit(pre_input_id, "u-member", False, "hello")

    asyncio.run(pre_input_service.cancel_pre_input(
        pre_input_id=pre_input_id, task_id="task-1", actor_user_id="u-owner",
    ))
    created = _create(mentioned_user_ids=[], edit_permission="ALL")
    pre_input_id = created["pre_input_id"]
    _edit(pre_input_id, "u-member", False, "hello")
    pre_input = _get(db, pre_input_id)
    assert pre_input_service._document_text(
        pre_input_service._document_segments(pre_input)
    ) == "hello"


def test_mark_done_participates_without_edit(db_session):
    db = db_session
    _seed(db)
    created = _create()
    asyncio.run(pre_input_service.mark_pre_input_done(
        pre_input_id=created["pre_input_id"], task_id="task-1", user_id="u-member",
    ))
    pre_input = _get(db, created["pre_input_id"])
    participants = [c.user_id for c in pre_input.contributions]
    assert "u-member" in participants


def test_auto_submit_when_all_mentioned_participated(db_session):
    db = db_session
    _seed(db)
    task = db.query(SddTask).filter(SddTask.id == "task-1").one()

    created = _create(mentioned_user_ids=["u-member", "u-expert"])
    pre_input_id = created["pre_input_id"]
    result = _edit(pre_input_id, "u-member", False, "hello brave world")
    assert result["auto_submitted"] is False
    assert pre_input_service.get_active_pre_input(db, task.id) is not None

    result = asyncio.run(pre_input_service.mark_pre_input_done(
        pre_input_id=pre_input_id, task_id="task-1", user_id="u-expert",
    ))
    assert result["auto_submitted"] is True
    assert result["submission"]["chat_message_id"]
    assert pre_input_service.get_active_pre_input(db, task.id) is None

    pre_input = _get(db, pre_input_id)
    assert pre_input.status == PreInputStatus.SUBMITTED
    assert pre_input.submit_reason == "all_done"


def test_submit_cas_prevents_double_submission(db_session):
    db = db_session
    _seed(db)
    task = db.query(SddTask).filter(SddTask.id == "task-1").one()

    created = _create(mentioned_user_ids=[])
    pre_input_id = created["pre_input_id"]
    first = asyncio.run(pre_input_service.submit_pre_input(
        pre_input_id=pre_input_id, actor_user_id="u-owner", reason="manual",
    ))
    assert first is not None

    second = asyncio.run(pre_input_service.submit_pre_input(
        pre_input_id=pre_input_id, actor_user_id="u-owner", reason="timeout",
    ))
    assert second is None


def test_submit_content_and_segment_metadata(db_session):
    db = db_session
    _seed(db)
    task = db.query(SddTask).filter(SddTask.id == "task-1").one()

    created = _create(mentioned_user_ids=[], edit_permission="ALL")
    pre_input_id = created["pre_input_id"]
    _replace_span(pre_input_id, "u-member", False, 6, 11, "world", "traceforge")
    asyncio.run(pre_input_service.submit_pre_input(
        pre_input_id=pre_input_id, actor_user_id="u-owner", reason="manual",
    ))

    from app.domains.task.models.chat import ChatMessage

    message = db.query(ChatMessage).filter(ChatMessage.task_id == task.id).one()
    assert message.role == "user"
    # 提交给 agent / 展示的内容 = 最终文档原文（无拼接标签）
    assert message.content == "hello traceforge"
    metadata = message.metadata_json
    assert metadata["pre_input_id"] == pre_input_id
    segments = metadata["segments"]
    joined = "".join(s["text"] for s in segments)
    assert joined == "hello traceforge"
    trace = next(s for s in segments if s["text"] == "trace")
    assert trace["created_by"] == "u-owner"
    assert trace["created_by_name"] == "Owner"
    assert trace["updated_by"] == "u-member"
    assert trace["modified"] is True
    forge = next(s for s in segments if s["text"] == "forge")
    assert forge["created_by"] == "u-member"
    contributed = {p["user_id"] for p in metadata["participants"]}
    assert {"u-owner", "u-member"} <= contributed


def test_cancel_only_by_creator(db_session):
    db = db_session
    _seed(db)
    created = _create()
    pre_input_id = created["pre_input_id"]

    with pytest.raises(pre_input_service.PreInputError):
        asyncio.run(pre_input_service.cancel_pre_input(
            pre_input_id=pre_input_id, task_id="task-1", actor_user_id="u-member",
        ))

    asyncio.run(pre_input_service.cancel_pre_input(
        pre_input_id=pre_input_id, task_id="task-1", actor_user_id="u-owner",
    ))
    pre_input = _get(db, pre_input_id)
    assert pre_input.status == PreInputStatus.CANCELLED


def test_serialize_document_segments_attribution(db_session):
    db = db_session
    _seed(db)
    created = _create(mentioned_user_ids=["u-member", "u-expert"], edit_permission="EXPERTS")
    pre_input_id = created["pre_input_id"]
    _replace_span(pre_input_id, "u-expert", True, 6, 11, "world", "traceforge")

    pre_input = _get(db, pre_input_id)
    payload = pre_input_service.serialize_pre_input(db, pre_input)
    segments = payload["document_segments"]
    assert "".join(s["text"] for s in segments) == "hello traceforge"
    trace = next(s for s in segments if s["text"] == "trace")
    assert trace["created_by"] == "u-owner"
    assert trace["updated_by"] == "u-expert"
    assert trace["updated_by_name"] == "Expert"
    assert trace["modified"] is True
    forge = next(s for s in segments if s["text"] == "forge")
    assert forge["created_by"] == "u-expert"
    assert forge["modified"] is False

    statuses = {m["user_id"]: m["done"] for m in payload["mentionees"]}
    assert statuses == {"u-member": False, "u-expert": True}
    assert payload["all_participated"] is False
    assert "u-expert" in payload["participant_ids"]
