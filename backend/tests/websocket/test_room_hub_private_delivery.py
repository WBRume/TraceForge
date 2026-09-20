"""RoomHub 私有定向投递测试：不进公共 journal、按用户过滤、LIVE 才投递。"""
import asyncio
import json
import os
import sys

import pytest

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.websocket.ws.room_hub import RoomHubRegistry


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def send_json(self, payload):
        self.sent.append(payload)


async def _connect_live(registry, ws, user_id):
    """建立连接并走完恢复屏障（真实客户端：resync_required → 快照 → resync_complete）。"""
    connection = await registry.connect("task:t1", ws, user_id=user_id)
    hub = registry._hubs["task:t1"]
    ok = await registry.complete_resync(
        "task:t1",
        ws,
        epoch=hub.journal.epoch,
        barrier_sequence=connection.barrier_sequence or 0,
    )
    assert ok, "resync barrier completion must succeed in test setup"
    return connection


@pytest.mark.asyncio
async def test_send_to_user_targets_only_matching_user():
    registry = RoomHubRegistry()
    ws_a = _FakeWebSocket()
    ws_b = _FakeWebSocket()
    await _connect_live(registry, ws_a, "user-a")
    await _connect_live(registry, ws_b, "user-b")

    delivered = registry.send_to_user(
        "task:t1", "user-a", {"type": "reading_progress_changed", "payload": {"state_revision": "1"}}
    )
    await asyncio.sleep(0.05)  # 等待出站 sender task 实际写 socket

    assert delivered == 1
    a_frames = [f for f in ws_a.sent if isinstance(f, dict) and f.get("type") == "reading_progress_changed"]
    assert len(a_frames) == 1
    # user-b 只收到自己的屏障控制帧，收不到 user-a 的私有阅读事件
    b_private = [f for f in ws_b.sent if isinstance(f, dict) and f.get("type") == "reading_progress_changed"]
    assert b_private == []


@pytest.mark.asyncio
async def test_private_events_never_enter_public_journal():
    """私有事件不分配公共序号、不进入 journal 回放（验收矩阵：私有通知与公共回放）。"""
    registry = RoomHubRegistry()
    ws_a = _FakeWebSocket()
    await _connect_live(registry, ws_a, "user-a")
    hub = registry._hubs["task:t1"]

    registry.send_to_user(
        "task:t1", "user-a", {"type": "reading_progress_changed", "payload": {"state_revision": "1"}}
    )
    # 公共业务事件照常编号
    registry.publish_text("task:t1", json.dumps({"type": "chat_message", "payload": {}}))

    assert hub.journal.high_watermark == 1
    assert hub.journal.events[0].event_type == "chat_message"
    assert all(e.event_type != "reading_progress_changed" for e in hub.journal.events)

    # 新连接从 0 回放：只能取得公共事件，无法取得私有阅读事件
    ws_c = _FakeWebSocket()
    await _connect_live(registry, ws_c, "user-c")
    # 连接走屏障快照，不回放私有帧：其收到的帧中不得包含 reading_progress_changed
    assert all(
        not (isinstance(f, dict) and f.get("type") == "reading_progress_changed")
        for f in ws_c.sent
    )


@pytest.mark.asyncio
async def test_private_events_are_deferred_until_live():
    """SYNCING 阶段私有帧进入延迟队列，屏障完成后随 LIVE 一起投递。"""
    registry = RoomHubRegistry()
    ws_a = _FakeWebSocket()
    connection = await registry.connect("task:t1", ws_a, user_id="user-a")

    delivered = registry.send_to_user(
        "task:t1", "user-a", {"type": "reading_progress_changed", "payload": {}}
    )
    assert delivered == 1
    assert ws_a.sent == []  # 未 LIVE：延迟
    assert connection.deferred_count == 1

    hub = registry._hubs["task:t1"]
    ok = await registry.complete_resync(
        "task:t1", ws_a, epoch=hub.journal.epoch, barrier_sequence=connection.barrier_sequence or 0
    )
    assert ok
    await asyncio.sleep(0.05)  # 等待出站 sender task 消费延迟帧
    types = [f.get("type") for f in ws_a.sent if isinstance(f, dict)]
    assert "reading_progress_changed" in types


@pytest.mark.asyncio
async def test_send_to_user_without_presence_not_delivered():
    """未绑定该用户的连接收不到定向投递（其他用户与公开分享连接隔离）。"""
    registry = RoomHubRegistry()
    ws_anon = _FakeWebSocket()
    await _connect_live(registry, ws_anon, None)

    delivered = registry.send_to_user("task:t1", "user-a", {"type": "reading_progress_changed", "payload": {}})
    assert delivered == 0
    assert ws_anon.sent == []
