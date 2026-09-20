"""回填 / 核对 / 清理服务测试（第 12 节合同）。"""
from datetime import datetime

from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingItem
from app.domains.task.models.task import SddTask
from app.domains.task.services import reading_backfill_service as rbs
from app.domains.task.services import reading_capture_service as rcs
from app.domains.task.services import task_service


def _add_legacy_messages(env, count, *, with_sort_seq=True, task_id=None):
    db = env["db"]
    target_task = task_id or env["task_id"]
    rows = []
    for i in range(count):
        rows.append(ChatMessage(
            task_id=target_task, workspace_id=env["ws_id"], creator_id="user-a",
            role="user", content=f"legacy {i}", message_type="text",
            sort_seq=i if with_sort_seq else None,
            created_at=datetime(2025, 1, 1, 0, 0, i),
        ))
    db.add_all(rows)
    db.commit()
    return rows


def _fresh_task(env, task_id="task-legacy"):
    task = SddTask(
        id=task_id, workspace_id=env["ws_id"], creator_id="user-a", name="legacy",
        project_path="G:/repo/legacy", status="PENDING",
        reading_change_seq=0, reading_epoch=1, reading_ready=False,
    )
    env["db"].add(task)
    env["db"].commit()
    return task


def test_backfill_creates_items_for_history_without_sorting_changes(seeded_db):
    env = seeded_db
    _fresh_task(env)
    rows = _add_legacy_messages(env, 5, task_id="task-legacy")
    result = rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=200)
    env["db"].commit()
    assert result["done"] is True and result["created"] == 5
    items = env["db"].query(TaskReadingItem).filter(TaskReadingItem.task_id == "task-legacy").all()
    assert len(items) == 5
    # 序号唯一且随源事务提交
    seqs = [item.change_seq for item in items]
    assert len(set(seqs)) == 5


def test_backfill_is_idempotent_and_never_overwrites_live_capture(seeded_db):
    env = seeded_db
    _fresh_task(env)
    _add_legacy_messages(env, 3, task_id="task-legacy")
    rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=200)
    env["db"].commit()
    # 在线写入又建了新 item（更新指纹）
    message = env["db"].query(ChatMessage).filter_by(task_id="task-legacy", content="legacy 1").first()
    message.content = "legacy 1 (edited)"
    env["db"].add(message)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id="task-legacy", message=message)
    env["db"].commit()
    # 重跑回填：不得覆盖在线捕获的新版本
    result = rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=200)
    env["db"].commit()
    assert result["created"] == 0
    item = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == "task-legacy", TaskReadingItem.message_id == message.id).first()
    assert item.change_seq == 4  # 在线捕获保留
    assert item.content_fingerprint is not None


def test_backfill_blocked_when_sort_seq_not_ready(seeded_db):
    env = seeded_db
    _fresh_task(env)
    _add_legacy_messages(env, 3, with_sort_seq=False, task_id="task-legacy")
    result = rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=200)
    env["db"].commit()
    assert result.get("blocked") == "SORT_SEQ_NOT_READY"
    assert env["db"].query(TaskReadingItem).filter(TaskReadingItem.task_id == "task-legacy").count() == 0


def test_backfill_checkpoint_resumes_across_batches(seeded_db):
    env = seeded_db
    _fresh_task(env)
    _add_legacy_messages(env, 5, task_id="task-legacy")
    first = rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=2)
    env["db"].commit()
    assert first["done"] is False and first["created"] == 2
    second = rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=2)
    env["db"].commit()
    assert second["created"] == 2
    third = rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=2)
    env["db"].commit()
    assert third["done"] is True and third["created"] == 1
    total = env["db"].query(TaskReadingItem).filter(TaskReadingItem.task_id == "task-legacy").count()
    assert total == 5


def test_verify_sets_reading_ready_and_detects_missing(seeded_db):
    env = seeded_db
    _fresh_task(env)
    _add_legacy_messages(env, 4, task_id="task-legacy")
    # 故意漏掉 1 条（小 batch 模拟中断）
    rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=3)
    env["db"].commit()
    verify_partial = rbs.verify_task(env["db"], task_id="task-legacy")
    env["db"].commit()
    assert verify_partial["ok"] is False and verify_partial["missing_items_count"] == 1
    task_row = rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=3)
    env["db"].commit()
    assert task_row["done"] is True
    verify = rbs.verify_task(env["db"], task_id="task-legacy")
    env["db"].commit()
    assert verify["ok"] is True
    task = env["db"].get(SddTask, "task-legacy")
    assert task.reading_ready is True


def test_verify_flags_active_items_pointing_to_deleted_sources(seeded_db):
    env = seeded_db
    _fresh_task(env)
    rows = _add_legacy_messages(env, 2, task_id="task-legacy")
    rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=200)
    env["db"].commit()
    # 源被物理删除但条目仍 active（异常场景）
    env["db"].query(ChatMessage).filter(ChatMessage.id == rows[0].id).delete(synchronize_session=False)
    env["db"].commit()
    verify = rbs.verify_task(env["db"], task_id="task-legacy")
    env["db"].commit()
    assert verify["ok"] is False and verify["stale_active"]
    task = env["db"].get(SddTask, "task-legacy")
    assert task.reading_ready is False


def test_live_capture_after_ready_does_not_conflict_with_backfill(seeded_db):
    env = seeded_db
    _fresh_task(env)
    _add_legacy_messages(env, 2, task_id="task-legacy")
    rbs.backfill_task_batch(env["db"], task_id="task-legacy", batch_size=200)
    env["db"].commit()
    verify = rbs.verify_task(env["db"], task_id="task-legacy")
    env["db"].commit()
    assert verify["ok"]
    # ready 之后在线写入正常递增，不与回填序号冲突
    m = task_service.save_chat_message(env["db"], task_id="task-legacy", workspace_id=env["ws_id"],
                                       creator_id="user-a", role="user", content="new live")
    env["db"].commit()
    item = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == "task-legacy", TaskReadingItem.message_id == m.id).first()
    assert item is not None and item.active
    seqs = [int(row.change_seq) for row in env["db"].query(TaskReadingItem.change_seq)
            .filter(TaskReadingItem.task_id == "task-legacy").all()]
    assert len(seqs) == len(set(seqs))


def test_cleanup_receipts_removes_stale_epoch_and_covered(seeded_db):
    env = seeded_db
    from app.domains.task.models.reading import TaskReadingReceipt, TaskReadingState
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a")
    env["db"].commit()
    state = TaskReadingState(
        user_id="user-b", task_id=env["task_id"], workspace_id=env["ws_id"],
        reading_epoch=1, baseline_seq=1, read_frontier_seq=1, state_revision=1, resume_revision=0,
    )
    env["db"].add(state)
    env["db"].add(TaskReadingReceipt(
        user_id="user-b", task_id=env["task_id"], reading_epoch=1,
        item_key=f"message:{m1.id}", seen_change_seq=1,
    ))
    env["db"].commit()
    # 清空历史 → epoch=2，epoch 1 的回执全部过期（含被前缀覆盖的）
    task_service.clear_task_history(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"])
    env["db"].commit()
    result = rbs.cleanup_receipts(env["db"], batch_size=500)
    env["db"].commit()
    assert result["removed_stale_epoch"] == 1
    assert env["db"].query(TaskReadingReceipt).count() == 0
