"""撤回 / 清空 / 锚点恢复语义测试（第 7 节合同）。"""
from datetime import datetime

from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingItem
from app.domains.task.models.task import SddTask
from app.domains.task.services import reading_capture_service as rcs
from app.domains.task.services import reading_progress_service as rps
from app.domains.task.services import reading_resume_service as rrs
from app.domains.task.services import task_service


def _save(env, *, role="assistant", content, creator="user-a", index=None, message_type="text"):
    message = task_service.save_chat_message(
        env["db"], task_id=env["task_id"], workspace_id=env["ws_id"], creator_id=creator,
        role=role, content=content, message_type=message_type,
    )
    if index is not None:
        message.created_at = datetime(2026, 1, 1, 0, 0, index)
        env["db"].add(message)
        env["db"].commit()
    return message


def _open(env, user_id):
    result = rps.open_reading_session(env["db"], user_id=user_id, workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    return result


def test_single_retraction_creates_one_notice_and_deactivates(seeded_db):
    env = seeded_db
    m1 = _save(env, content="only one")
    _open(env, "user-b")
    m1_id = str(m1.id)
    rcs.record_message_retractions(env["db"], task_id=env["task_id"], message_ids=[m1_id], operation_id="op-1")
    env["db"].query(ChatMessage).filter(ChatMessage.id == m1_id).delete(synchronize_session=False)
    env["db"].commit()
    item = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == env["task_id"], TaskReadingItem.item_key == f"message:{m1_id}").first()
    assert not item.active and item.operation_id == "op-1"
    notices = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == env["task_id"], TaskReadingItem.kind == "messages_retracted").all()
    assert len(notices) == 1 and notices[0].affected_count == 1
    assert notices[0].content_fingerprint is None  # 不含正文


def test_bulk_retraction_single_notice_with_idempotency(seeded_db):
    env = seeded_db
    messages = [_save(env, content=f"m{i}", index=i) for i in range(30)]
    _open(env, "user-b")
    ids = [str(m.id) for m in messages]
    rcs.record_message_retractions(env["db"], task_id=env["task_id"], message_ids=ids, operation_id="op-bulk")
    env["db"].query(ChatMessage).filter(ChatMessage.id.in_(ids)).delete(synchronize_session=False)
    env["db"].commit()
    # 幂等重放
    rcs.record_message_retractions(env["db"], task_id=env["task_id"], message_ids=ids, operation_id="op-bulk")
    env["db"].commit()
    notices = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == env["task_id"], TaskReadingItem.kind == "messages_retracted").all()
    assert len(notices) == 1
    assert notices[0].affected_count == 30
    assert notices[0].boundary_before_id == ids[0]
    assert notices[0].boundary_after_id == ids[-1]


def test_retraction_of_hidden_only_messages_inserts_no_notice(seeded_db):
    env = seeded_db
    thinking = _save(env, content="t", message_type="thinking")
    _open(env, "user-b")
    rcs.record_message_retractions(env["db"], task_id=env["task_id"], message_ids=[thinking.id], operation_id="op-hidden")
    env["db"].commit()
    notices = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == env["task_id"], TaskReadingItem.kind == "messages_retracted").all()
    assert notices == []


def test_resume_resolution_updated_when_version_drifts(seeded_db):
    env = seeded_db
    m1 = _save(env, content="v1")
    _open(env, "user-b")
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[{"item_key": f"message:{m1.id}", "change_seq": "1"}],
        resume={"message_id": m1.id, "content_seq": "1", "offset_ratio": 0.5, "expected_revision": "0"},
    )
    env["db"].commit()
    assert resp["resume_applied"] is True
    m1.content = "v2 edited"
    env["db"].add(m1)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id=env["task_id"], message=m1)
    env["db"].commit()
    res = rrs.resolve_resume(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    assert res["anchor_status"] == "updated"
    assert res["anchor"]["offset_ratio"] is None  # 版本更新后偏移归零


def test_resume_resolution_retracted_uses_saved_order_key(seeded_db):
    env = seeded_db
    m1 = _save(env, content="first", index=1)
    m2 = _save(env, content="second", index=2)
    _open(env, "user-b")
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[],
        resume={"message_id": m2.id, "content_seq": "2", "offset_ratio": 0.5, "expected_revision": "0"},
    )
    env["db"].commit()
    assert resp["resume_applied"] is True
    # 撤回 m2（源删除）
    m2_id = str(m2.id)
    rcs.record_message_retractions(env["db"], task_id=env["task_id"], message_ids=[m2_id], operation_id="op-r")
    env["db"].query(ChatMessage).filter(ChatMessage.id == m2_id).delete(synchronize_session=False)
    env["db"].commit()
    res = rrs.resolve_resume(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    assert res["anchor_status"] == "retracted"
    assert res["anchor"]["message_id"] == str(m1.id)  # 最近仍存在的前一条
    assert res["messages"], "邻域上下文必须返回"


def test_resume_resolution_missing_without_capture_record(seeded_db):
    env = seeded_db
    m1 = _save(env, content="first", index=1)
    _open(env, "user-b")
    rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[],
        resume={"message_id": m1.id, "content_seq": "1", "offset_ratio": 0.5, "expected_revision": "0"},
    )
    env["db"].commit()
    # 直接物理删除（无捕获记录）：不能编造撤回原因
    env["db"].query(ChatMessage).filter(ChatMessage.id == m1.id).delete(synchronize_session=False)
    env["db"].commit()
    res = rrs.resolve_resume(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    assert res["anchor_status"] in {"missing", "empty"}


def test_resume_resolution_empty_after_clearing_everything(seeded_db):
    env = seeded_db
    m1 = _save(env, content="first", index=1)
    _open(env, "user-b")
    rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[],
        resume={"message_id": m1.id, "content_seq": "1", "offset_ratio": 0.5, "expected_revision": "0"},
    )
    env["db"].commit()
    task_service.clear_task_history(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"])
    env["db"].commit()
    res = rrs.resolve_resume(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    # epoch 变化后状态未迁移 → 无锚点可解析；迁移后 anchor 清空
    assert res["anchor_status"] == "none"
    migrated = _open(env, "user-b")["state"]
    assert migrated["resume"] is None


def test_clear_history_deactivates_items_and_notices(seeded_db):
    env = seeded_db
    m1 = _save(env, content="first", index=1)
    _open(env, "user-b")
    rcs.record_message_retractions(env["db"], task_id=env["task_id"], message_ids=[m1.id], operation_id="op-pre")
    env["db"].commit()
    task_service.clear_task_history(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"])
    env["db"].commit()
    active = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == env["task_id"], TaskReadingItem.active.is_(True)).all()
    kinds = [item.kind for item in active]
    assert kinds == ["history_cleared"]
    task = env["db"].query(SddTask).get(env["task_id"])
    assert int(task.reading_epoch) == 2
    # change_seq 继续递增，不重置
    assert int(task.reading_change_seq) == 3
