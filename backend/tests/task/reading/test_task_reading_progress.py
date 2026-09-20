"""个人阅读状态与跨设备合并语义测试（第 6/8 节合同）。"""
import pytest

from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingReceipt
from app.domains.task.services import reading_capture_service as rcs
from app.domains.task.services import reading_progress_service as rps
from app.domains.task.services import task_service


@pytest.fixture()
def ready_env(seeded_db):
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="user", content="u1")
    m2 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a1")
    return env, m1, m2


def _open(env, user_id):
    result = rps.open_reading_session(env["db"], user_id=user_id, workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    return result


def test_baseline_covers_history_without_faking_unread(ready_env):
    env, m1, m2 = ready_env
    state = _open(env, "user-b")["state"]
    assert state["initialized"] is True
    assert state["baseline_seq"] == state["read_frontier_seq"] == state["latest_change_seq"]
    assert state["has_unread"] is False
    assert state["unread_count"] == {"value": 0, "relation": "eq"}


def test_repeated_open_does_not_reset_baseline(ready_env):
    env, m1, m2 = ready_env
    first = _open(env, "user-b")["state"]
    second = _open(env, "user-b")["state"]
    assert first["baseline_seq"] == second["baseline_seq"]
    assert first["state_revision"] == second["state_revision"]


def test_receipts_accept_exact_versions_and_advance_frontier(ready_env):
    env, m1, m2 = ready_env
    _open(env, "user-b")
    m3 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a2")
    env["db"].commit()
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[{"item_key": f"message:{m3.id}", "change_seq": "3"}], resume=None,
    )
    env["db"].commit()
    assert resp["accepted_items"] == [{"item_key": f"message:{m3.id}", "change_seq": "3"}]
    assert resp["state"]["read_frontier_seq"] == "3"


def test_receipt_rejects_version_mismatch(seeded_db):
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="user", content="u1")
    env["db"].commit()
    _open(env, "user-b")
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[{"item_key": f"message:{m1.id}", "change_seq": "999"}], resume=None,
    )
    env["db"].commit()
    assert resp["skipped_items"] == [{"item_key": f"message:{m1.id}", "reason": "version_changed"}]
    assert resp["state"]["read_frontier_seq"] == "1"


def test_duplicate_receipt_is_idempotent_and_does_not_bump_revision(seeded_db):
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a")
    env["db"].commit()
    _open(env, "user-b")
    first = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[{"item_key": f"message:{m1.id}", "change_seq": "1"}], resume=None,
    )
    env["db"].commit()
    second = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[{"item_key": f"message:{m1.id}", "change_seq": "1"}], resume=None,
    )
    env["db"].commit()
    assert second["state"]["state_revision"] == first["state"]["state_revision"]


def test_receipts_merge_max_per_item(seeded_db):
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a1")
    m2 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a2")
    m2.content = "a2-updated"
    env["db"].add(m2)
    env["db"].flush()
    rcs.record_message_change(env["db"], task_id=env["task_id"], message=m2)
    env["db"].commit()
    _open(env, "user-b")
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[
            {"item_key": f"message:{m2.id}", "change_seq": "1"},   # 同批去重：保留 max
            {"item_key": f"message:{m2.id}", "change_seq": "3"},   # 当前版本
        ],
        resume=None,
    )
    env["db"].commit()
    assert resp["accepted_items"] == [{"item_key": f"message:{m2.id}", "change_seq": "3"}]
    assert resp["skipped_items"] == []


def test_own_user_input_never_blocks_own_frontier(seeded_db):
    env = seeded_db
    _open(env, "user-b")
    m = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                       creator_id="user-b", role="user", content="my own words")
    env["db"].commit()
    prog = rps.read_only_progress(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    assert prog["has_unread"] is False
    # compact 推进越过本人输入
    resp = rps.compact_progress(env["db"], user_id="user-b", workspace_id=env["ws_id"],
                                task_id=env["task_id"], epoch=1)
    env["db"].commit()
    assert resp["advanced"] is True
    assert int(resp["state"]["read_frontier_seq"]) == int(m.metadata_json["order_index"]) + 1


def test_compact_stops_at_first_real_unread(seeded_db):
    env = seeded_db
    _open(env, "user-b")
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a1")
    m2 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a2")
    env["db"].commit()
    # 只回执 m2（跳过 m1）
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[{"item_key": f"message:{m2.id}", "change_seq": "2"}], resume=None,
    )
    env["db"].commit()
    # m1 未读 → 前缀停在 m1 之前
    assert int(resp["state"]["read_frontier_seq"]) == 0
    assert resp["state"]["has_unread"] is True
    # 补读缺口后推进到 m2
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[{"item_key": f"message:{m1.id}", "change_seq": "1"}], resume=None,
    )
    env["db"].commit()
    assert int(resp["state"]["read_frontier_seq"]) == 2


def test_resume_cas_rejects_stale_overwrite(seeded_db):
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a")
    env["db"].commit()
    _open(env, "user-b")
    ok = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[], resume={"message_id": m1.id, "content_seq": "1", "offset_ratio": 0.4, "expected_revision": "0"},
    )
    env["db"].commit()
    assert ok["resume_applied"] is True
    late = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[], resume={"message_id": m1.id, "content_seq": "1", "offset_ratio": 0.9, "expected_revision": "0"},
    )
    env["db"].commit()
    assert late["resume_applied"] is False
    assert late["state"]["resume"]["offset_ratio"] == 0.4
    # 冲突不得回滚已合并的回执
    assert late["state"]["read_frontier_seq"] == "1"


def test_resume_validation_rejects_deleted_anchor(seeded_db):
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a")
    env["db"].commit()
    _open(env, "user-b")
    rcs.record_message_retractions(env["db"], task_id=env["task_id"], message_ids=[m1.id], operation_id="op-x")
    env["db"].commit()
    resp = rps.submit_receipts(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        raw_items=[], resume={"message_id": m1.id, "content_seq": "1", "offset_ratio": 0.4, "expected_revision": "0"},
    )
    env["db"].commit()
    assert resp["resume_applied"] is False


def test_ack_bounded_by_window_upper(seeded_db):
    env = seeded_db
    result = rps.open_reading_session(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    assert result["state"]["read_frontier_seq"] == "0"  # 空任务基线 0
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="new after window")
    env["db"].commit()
    resp = rps.acknowledge_through_window(
        env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"], epoch=1,
        window_token=result["window_token"],
    )
    env["db"].commit()
    assert int(resp["applied_upper_seq"]) == 0  # 窗口上界为 0：只推进到 0
    assert resp["state"]["has_unread"] is True  # 窗口上界之外的新消息仍未读
    assert int(resp["state"]["read_frontier_seq"]) == 0


def test_epoch_conflict_on_stale_submission(seeded_db):
    env = seeded_db
    _open(env, "user-b")
    task_service.clear_task_history(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"])
    env["db"].commit()
    with pytest.raises(rps.ReadingEpochChanged):
        rps.submit_receipts(env["db"], user_id="user-b", workspace_id=env["ws_id"],
                            task_id=env["task_id"], epoch=1, raw_items=[], resume=None)


def test_clear_history_resets_epoch_and_lazy_migrates(seeded_db):
    env = seeded_db
    _open(env, "user-b")
    task_service.clear_task_history(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"])
    env["db"].commit()
    prog = rps.read_only_progress(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    assert prog["initialized"] is False
    migrated = _open(env, "user-b")["state"]
    assert migrated["reading_epoch"] == "2"
    # 前缀=清空 notice 序号减一 → 用户能看到清空提示
    assert migrated["has_unread"] is True
    assert migrated["unread_count"]["value"] == 1


def test_reading_items_batch_identity(seeded_db):
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="a")
    m2 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="assistant", content="b")
    env["db"].commit()
    result = rps.get_reading_items(env["db"], task_id=env["task_id"], message_ids=[m1.id, m2.id, "ghost"])
    assert len(result["items"]) == 2
    by_id = {item["message_id"]: item for item in result["items"]}
    assert by_id[m1.id]["item_key"] == f"message:{m1.id}"
    assert by_id[m2.id]["active"] is True
    assert "ghost" not in by_id


def test_self_created_assistant_reply_is_exempt_from_unread(seeded_db):
    """本人触发的会话的 AI 回复（creator_id=本人）不计本人未读；他人仍计未读。"""
    env = seeded_db
    _open(env, "user-a")
    _open(env, "user-b")
    task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                   creator_id="user-a", role="user", content="A asks")
    task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                   creator_id="user-a", role="assistant", content="AI replies to A")
    env["db"].commit()
    prog_a = rps.read_only_progress(env["db"], user_id="user-a", workspace_id=env["ws_id"], task_id=env["task_id"])
    assert prog_a["has_unread"] is False, prog_a["unread_count"]
    prog_b = rps.read_only_progress(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    assert prog_b["has_unread"] is True and prog_b["unread_count"]["value"] == 2


def test_resume_prefers_first_unread_over_saved_anchor(seeded_db):
    """从上次阅读处继续优先落在未读起点（最早未读），而非旧保存锚点。"""
    env = seeded_db
    m1 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="user", content="old anchor msg")
    env["db"].commit()
    _open(env, "user-b")
    # 旧机制保存的锚点（指向 m1）
    rps.submit_receipts(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"],
                        epoch=1, raw_items=[],
                        resume={"message_id": m1.id, "content_seq": "1", "offset_ratio": 0.5,
                                "expected_revision": "0"})
    env["db"].commit()
    # 之后出现新未读（user-a 发言，user-b 未读）
    m2 = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                        creator_id="user-a", role="user", content="new unread msg")
    env["db"].commit()
    from app.domains.task.services import reading_resume_service as rrs
    res = rrs.resolve_resume(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"])
    env["db"].commit()
    assert res["anchor_status"] == "ok", res
    assert res["anchor"]["message_id"] == str(m2.id), res["anchor"]
