"""消息变更捕获语义测试（第 4/5 节合同）。"""
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingItem
from app.domains.task.services import reading_capture_service as rcs
from app.domains.task.services import task_service


def _save(env, *, role, content, message_type="text", creator="user-a", metadata=None):
    db = env["db"]
    return task_service.save_chat_message(
        db, task_id=env["task_id"], workspace_id=env["ws_id"], creator_id=creator,
        role=role, content=content, message_type=message_type, metadata_json=metadata,
    )


def _item(env, message_id):
    return (
        env["db"].query(TaskReadingItem)
        .filter(TaskReadingItem.task_id == env["task_id"], TaskReadingItem.item_key == f"message:{message_id}")
        .first()
    )


def test_visible_message_creates_reading_item_with_unique_seq(seeded_db):
    env = seeded_db
    m1 = _save(env, role="user", content="hello")
    m2 = _save(env, role="assistant", content="world")
    item = _item(env, m1.id)
    assert item is not None and item.active and item.kind == "message"
    assert item.change_seq != _item(env, m2.id).change_seq
    assert item.first_change_seq == item.change_seq
    # 撤回提示等后续依赖：order 键快照必须落库
    assert item.order_message_id == m1.id
    assert item.order_sort_seq is not None


def test_thinking_and_hidden_types_do_not_capture(seeded_db):
    env = seeded_db
    m = _save(env, role="assistant", content="deep thought", message_type="thinking")
    assert _item(env, m.id) is None


def test_in_place_update_bumps_change_seq_and_keeps_first(seeded_db):
    env = seeded_db
    m = _save(env, role="assistant", content="v1")
    first_seq = int(_item(env, m.id).change_seq)
    first_fp = str(_item(env, m.id).content_fingerprint)

    m.content = "v2"
    env["db"].add(m)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id=env["task_id"], message=m)
    env["db"].commit()

    item = _item(env, m.id)
    assert int(item.change_seq) == first_seq + 1
    assert int(item.first_change_seq) == first_seq
    assert item.content_fingerprint != first_fp


def test_identical_content_update_does_not_bump(seeded_db):
    env = seeded_db
    m = _save(env, role="assistant", content="stable")
    before = int(_item(env, m.id).change_seq)
    # 内部 metadata 变化（token 统计等）不影响可见指纹
    m.metadata_json = {**(m.metadata_json or {}), "session_revision": 99}
    env["db"].add(m)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id=env["task_id"], message=m)
    env["db"].commit()
    assert int(_item(env, m.id).change_seq) == before


def test_role_and_author_change_is_a_new_visible_version(seeded_db):
    env = seeded_db
    m = _save(env, role="assistant", content="text")
    before = int(_item(env, m.id).change_seq)
    m.creator_id = "user-b"
    env["db"].add(m)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id=env["task_id"], message=m)
    env["db"].commit()
    item = _item(env, m.id)
    assert int(item.change_seq) > before
    assert item.creator_id == "user-b"


def test_visible_to_invisible_deactivates_item(seeded_db):
    env = seeded_db
    m = _save(env, role="assistant", content="visible then hidden")
    assert _item(env, m.id).active
    m.message_type = "thinking"
    env["db"].add(m)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id=env["task_id"], message=m)
    env["db"].commit()
    item = _item(env, m.id)
    assert not item.active
    assert item.deleted_change_seq is not None


def test_hitl_confirmation_metadata_participates_in_fingerprint(seeded_db):
    env = seeded_db
    meta = {"confirmation": {"interaction_id": "i1", "kind": "boolean", "options": ["ok"]}}
    m = _save(env, role="assistant", content="please confirm", metadata=meta)
    before = _item(env, m.id).content_fingerprint
    m.metadata_json = {**meta, "confirmation": {**meta["confirmation"], "kind": "select"}}
    env["db"].add(m)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id=env["task_id"], message=m)
    env["db"].commit()
    assert _item(env, m.id).content_fingerprint != before


def test_capture_failure_aborts_transaction(seeded_db):
    env = seeded_db
    db = env["db"]
    # 任务不存在：序号分配/捕获抛错，源消息不得残留
    try:
        task_service.save_chat_message(
            db, task_id="missing-task", workspace_id=env["ws_id"], creator_id="user-a",
            role="user", content="orphan", message_type="text",
        )
        raised = False
    except Exception:
        raised = True
    assert raised
    db.rollback()
    assert not db.query(ChatMessage).filter(ChatMessage.task_id == "missing-task").count()
