"""REST 接口合同测试（第 8 节）：鉴权、错误码、幂等、载荷形状。"""
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402  (模型注册见 conftest)
from app.dependencies import get_current_user, get_db  # noqa: E402
from app.domains.auth.models.user import User  # noqa: E402
from app.domains.task.models.chat import ChatMessage  # noqa: E402
from app.domains.task.routers.task import reading as reading_router  # noqa: E402
from app.domains.task.services import task_service  # noqa: E402


class _StubUser:
    """get_current_user 桩：路由只读 user.id。"""

    def __init__(self, user_id: str) -> None:
        self.id = user_id


@pytest.fixture()
def api_env(seeded_db, monkeypatch):
    env = seeded_db
    db = env["db"]

    # 空的 SEARCH_CURSOR_SECRET 由服务自行处理；这里签发窗口令牌需要密钥
    from app.config import settings
    monkeypatch.setattr(settings, "SEARCH_CURSOR_SECRET", "test-secret-for-reading")

    test_app = FastAPI()
    test_app.include_router(reading_router.router, prefix="/api")
    test_app.dependency_overrides[get_db] = lambda: db
    test_app.dependency_overrides[get_current_user] = lambda: _StubUser("user-b")
    client = TestClient(test_app)
    return env, client


def _open_session(client, env):
    resp = client.post(f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-sessions", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_reading_sessions_initializes_and_is_idempotent(api_env):
    env, client = api_env
    first = _open_session(client, env)
    assert first["state"]["initialized"] is True
    assert first["window_token"]
    second = _open_session(client, env)
    assert second["state"]["baseline_seq"] == first["state"]["baseline_seq"]


def test_get_progress_readonly_without_init(api_env):
    env, client = api_env
    resp = client.get(f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["initialized"] is False
    # GET 不创建状态
    from app.domains.task.models.reading import TaskReadingState
    assert env["db"].query(TaskReadingState).count() == 0


def test_receipts_and_progress_roundtrip(api_env):
    env, client = api_env
    session = _open_session(client, env)
    m = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                       creator_id="user-a", role="assistant", content="ai")
    env["db"].commit()
    epoch = session["state"]["reading_epoch"]
    resp = client.post(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-receipts",
        json={
            "reading_epoch": epoch,
            "items": [{"item_key": f"message:{m.id}", "change_seq": m and _seq(env, m)}],
            "resume": {"message_id": m.id, "content_seq": _seq(env, m), "offset_ratio": 0.5,
                       "expected_revision": session["state"]["resume"] or "0"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["resume_applied"] is True
    assert body["state"]["has_unread"] is False

    prog = client.get(f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-progress").json()
    assert prog["read_frontier_seq"] == body["state"]["read_frontier_seq"]


def _seq(env, message):
    from app.domains.task.models.reading import TaskReadingItem
    item = env["db"].query(TaskReadingItem).filter(
        TaskReadingItem.task_id == env["task_id"], TaskReadingItem.message_id == message.id).first()
    return str(int(item.change_seq))


def test_receipts_validation_rejects_unknown_fields_and_bad_ratio(api_env):
    env, client = api_env
    session = _open_session(client, env)
    epoch = session["state"]["reading_epoch"]
    # 未知字段
    resp = client.post(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-receipts",
        json={"reading_epoch": epoch, "items": [], "bogus": 1},
    )
    assert resp.status_code == 422
    # 非法 ratio
    resp = client.post(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-receipts",
        json={"reading_epoch": epoch, "items": [],
              "resume": {"message_id": "x", "content_seq": "1", "offset_ratio": 1.5, "expected_revision": "0"}},
    )
    assert resp.status_code == 422


def test_epoch_conflict_returns_409(api_env):
    env, client = api_env
    session = _open_session(client, env)
    task_service.clear_task_history(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"])
    env["db"].commit()
    resp = client.post(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-receipts",
        json={"reading_epoch": session["state"]["reading_epoch"], "items": []},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "READING_EPOCH_CHANGED"


def test_reading_updates_endpoint_filters_and_pagination(api_env):
    env, client = api_env
    # 先建基线（空任务 → frontier=0）
    _open_session(client, env)
    for i in range(3):
        task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                       creator_id="user-a", role="assistant", content=f"ai {i}")
    env["db"].commit()
    # 再取新令牌：lower=0, upper=3
    session = _open_session(client, env)
    token = session["window_token"]
    resp = client.get(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-updates",
        params={"window_token": token, "filter": "all", "limit": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True and body["next_cursor"]
    assert body["has_newer_updates"] is False  # 上界=当时水位
    # 翻页
    resp2 = client.get(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-updates",
        params={"window_token": token, "filter": "all", "limit": 2, "cursor": body["next_cursor"]},
    )
    body2 = resp2.json()
    seqs = [int(i["change_seq"]) for i in body2["items"]]
    assert all(s > int(body["next_cursor"]) for s in seqs)
    # 成员筛选：assistant 不是成员输入
    resp3 = client.get(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-updates",
        params={"window_token": token, "filter": "other-members"},
    )
    roles = [i.get("message", {}).get("role") for i in resp3.json()["items"] if i["kind"] == "message"]
    assert "assistant" not in roles


def test_reading_resume_endpoint_shape(api_env):
    env, client = api_env
    _open_session(client, env)
    m = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                       creator_id="user-a", role="assistant", content="ai")
    env["db"].commit()
    from app.domains.task.services import reading_progress_service as rps
    rps.submit_receipts(env["db"], user_id="user-b", workspace_id=env["ws_id"], task_id=env["task_id"],
                        epoch=1, raw_items=[],
                        resume={"message_id": m.id, "content_seq": _seq(env, m), "offset_ratio": 0.2,
                                "expected_revision": "0"})
    env["db"].commit()
    resp = client.get(f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-resume")
    assert resp.status_code == 200
    body = resp.json()
    assert body["anchor_status"] == "ok"
    assert body["anchor"]["message_id"] == m.id
    assert any(msg["id"] == m.id for msg in body["messages"])


def test_reading_items_endpoint_batches(api_env):
    env, client = api_env
    _open_session(client, env)
    ids = []
    for i in range(3):
        m = task_service.save_chat_message(env["db"], task_id=env["task_id"], workspace_id=env["ws_id"],
                                           creator_id="user-a", role="assistant", content=f"a{i}")
        ids.append(m.id)
    env["db"].commit()
    resp = client.get(
        f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-items",
        params=[("message_id", mid) for mid in ids],
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    assert all(item["item_key"] == f"message:{item['message_id']}" for item in items)


def test_workspace_access_enforced(api_env):
    """非本工作区用户 403（不泄漏任务存在性）。"""
    env, client = api_env
    other = User(id="user-out", email="out@example.com", hashed_password="x", display_name="Out")
    env["db"].add(other)
    env["db"].commit()

    from app.database import Base as _B  # noqa: F401
    test_app = FastAPI()
    test_app.include_router(reading_router.router, prefix="/api")
    test_app.dependency_overrides[get_db] = lambda: env["db"]
    test_app.dependency_overrides[get_current_user] = lambda: _StubUser("user-out")
    outside = TestClient(test_app)
    resp = outside.get(f"/api/workspaces/{env['ws_id']}/tasks/{env['task_id']}/reading-progress")
    assert resp.status_code == 403
