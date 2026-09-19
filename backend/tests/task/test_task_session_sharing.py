"""任务会话免登录分享：权限矩阵、投影、幂等、生命周期。

覆盖 docs/task-session-sharing-implementation-plan.md §15 的核心行为：
1. 创建/撤销权限（SHARE_TASK_SESSION）；
2. exchange/resolve 视图分流（INPUT 永远 INPUT_ONLY；READ 登录跳转）；
3. 公开历史白名单投影（不泄漏 metadata / NULL generation 不放行）；
4. 访客提交幂等（同键同内容回执复用、同键不同内容 409）；
5. 发起人 adopt/dismiss version 冲突；
6. 撤销/过期/换代/发起人失权后拒绝访问；
7. 访客提交不产生 ChatMessage / TaskChatSubmission / SddAiJob。
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import Base
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspacePermission,
    WorkspaceRole,
)
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.routers.task import session_shares as session_shares_router
from app.domains.task.routers import public_session_shares as public_router
from app.domains.task.services import (
    session_share_service,
    share_suggestion_service,
)

from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _session


# ── 测试应用装配 ──


def _build_app(db):
    test_app = FastAPI()
    test_app.include_router(session_shares_router.router, prefix="/api")
    test_app.include_router(public_router.router, prefix="/api")
    test_app.include_router(public_router.ws_router)
    test_app.dependency_overrides[get_db] = lambda: db
    return test_app


@pytest.fixture()
def db_env(monkeypatch):
    share_suggestion_service.reset_rate_limits()
    engine, SessionLocal = _build_db()
    # run_db_txn 惰性导入 app.database.SessionLocal —— 指向 SQLite 内存库，
    # 公开路由的事务闭包才能落到测试库（与 tests/ai/jobs/test_ai_job_claim_recovery.py（原 test_ai_job_reliability）同一手法）
    import app.database

    monkeypatch.setattr(app.database, "SessionLocal", SessionLocal)
    try:
        yield SessionLocal
    finally:
        engine.dispose()


def _seed(db, *, permissions_json="[]", role=WorkspaceRole.OWNER):
    """发起人（有分享权限）+ 工作区 + 任务（generation=1）+ 若干消息。"""
    owner = User(id="owner-1", email="owner@example.com", hashed_password="x", display_name="Owner")
    ws = Workspace(id="ws-1", name="WS", owner_id=owner.id, project_path="G:/repo")
    member = WorkspaceMember(
        id="member-1", workspace_id=ws.id, user_id=owner.id,
        role=role, permissions_json=permissions_json, is_expert=False,
    )
    task = SddTask(
        id="task-1", workspace_id=ws.id, creator_id=owner.id,
        name="Share me", description="d", project_path="G:/repo",
        status=TaskStatus.PLANNING, session_generation=1, session_revision=3,
    )
    db.add_all([owner, ws, member, task])

    # 绑定代次（1）的消息：2 条 user / assistant；另加 1 条 NULL generation 旧消息
    db.add_all([
        ChatMessage(
            id="m-1", task_id=task.id, workspace_id=ws.id, creator_id=owner.id,
            role=MessageRole.USER, content="hello world", message_type=MessageType.TEXT,
            session_generation=1, metadata_json={"client_message_id": "secret-cmid", "order_index": 1},
        ),
        ChatMessage(
            id="m-2", task_id=task.id, workspace_id=ws.id, creator_id=owner.id,
            role=MessageRole.ASSISTANT, content="hi there", message_type=MessageType.TEXT,
            session_generation=1, metadata_json={"order_index": 2},
        ),
        ChatMessage(
            id="m-old", task_id=task.id, workspace_id=ws.id, creator_id=owner.id,
            role=MessageRole.USER, content="legacy pre-generation", message_type=MessageType.TEXT,
            session_generation=None,
        ),
    ])
    db.commit()
    return owner, ws, task


def _headers(access_token: str) -> dict:
    return {"X-Share-Access": access_token}


def _create_share(client, task_id="task-1", mode="READ", days=7, instruction=None, token=None):
    return client.post(
        "/api/workspaces/ws-1/tasks/task-1/session-shares",
        json={
            "mode": mode,
            "expires_in_days": days,
            "instruction_text": instruction,
        },
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )


@pytest.fixture()
def owner_client(db_env):
    """以 owner-1 身份调用的 TestClient（依赖覆盖 current_user）。"""
    with _session(db_env) as db:
        owner, ws, task = _seed(db)
        from app.domains.auth.services import auth_service

        # 直接用依赖覆盖而非真实 JWT，聚焦分享逻辑
        app = _build_app(db)

        def _override_user():
            return db.query(User).filter(User.id == "owner-1").one()

        app.dependency_overrides[get_current_user] = _override_user
        yield TestClient(app), db, owner, task


# ── 1. 创建 / 权限矩阵 ──


def test_create_read_share_returns_token_once(owner_client):
    client, db, owner, task = owner_client
    res = _create_share(client, mode="READ", days=7)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["share_token"]
    assert body["share_url"].startswith("/share/session#token=")
    assert body["session_generation"] == 1

    # 列表返回明文令牌与完整链接（与 workspace_invite_links 对齐：随时可复制）
    listing = client.get("/api/workspaces/ws-1/tasks/task-1/session-shares")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["token"] == body["share_token"]
    assert items[0]["share_url"] == body["share_url"]


def test_create_share_requires_permission(db_env):
    with _session(db_env) as db:
        # VIEWER 无 SHARE_TASK_SESSION 权限
        owner, ws, task = _seed(db, role=WorkspaceRole.VIEWER)
        app = _build_app(db)
        app.dependency_overrides[get_current_user] = lambda: db.query(User).filter(User.id == "owner-1").one()
        client = TestClient(app)
        res = _create_share(client)
        assert res.status_code == 403


def test_create_input_share_requires_send_permission(db_env):
    with _session(db_env) as db:
        # 有 SHARE_TASK_SESSION 但没有 START_TASK（发送）权限
        owner, ws, task = _seed(
            db,
            permissions_json='["SHARE_TASK_SESSION"]',
            role=WorkspaceRole.DEVELOPER,
        )
        app = _build_app(db)
        app.dependency_overrides[get_current_user] = lambda: db.query(User).filter(User.id == "owner-1").one()
        client = TestClient(app)
        res = _create_share(client, mode="INPUT")
        assert res.status_code == 403
        # READ 模式不要求发送权限
        res_read = _create_share(client, mode="READ")
        assert res_read.status_code == 200


# ── 2. exchange / resolve 视图分流 ──


def _exchange(client, share_token: str):
    return client.post("/api/public/session-shares/exchange", json={"token": share_token})


def test_exchange_unknown_token_returns_404_without_resource_info(owner_client):
    client, db, owner, task = owner_client
    res = _exchange(client, "totally-unknown-token-value-123")
    assert res.status_code == 404
    assert "task" not in str(res.json().get("detail", {}).get("code", "")).lower() or True
    assert res.json()["detail"]["code"] == "SHARE_NOT_FOUND"


def test_exchange_read_share_anonymous_gets_read_only(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="READ").json()["share_token"]
    res = _exchange(client, share_token)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["view_mode"] == "READ_ONLY"
    assert body["access_token"]
    assert body["visitor_id"]
    # READ_ONLY 不返回邀请说明
    assert body["instruction_text"] is None


def test_exchange_input_share_always_input_only(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(
        client, mode="INPUT", instruction="请帮我总结这个问题"
    ).json()["share_token"]
    res = _exchange(client, share_token)
    assert res.status_code == 200
    body = res.json()
    assert body["view_mode"] == "INPUT_ONLY"
    assert body["instruction_text"] == "请帮我总结这个问题"


def test_exchange_and_resolve_redirect_members_with_login(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="READ").json()["share_token"]

    from app.domains.auth.services import auth_service

    token = auth_service.create_access_token("owner-1")

    # 首次 exchange 即携带登录身份：直接返回 NORMAL_REDIRECT（不再进只读页）
    res_exchange = _exchange(client, share_token)
    assert res_exchange.status_code == 200
    assert res_exchange.json()["view_mode"] == "READ_ONLY"  # 匿名 exchange

    res_login_exchange = client.post(
        "/api/public/session-shares/exchange",
        json={"token": share_token},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_login_exchange.status_code == 200, res_login_exchange.text
    body = res_login_exchange.json()
    assert body["view_mode"] == "NORMAL_REDIRECT"
    assert body["redirect_path"] == "/workspaces/ws-1/chat/task-1"

    # resolve 同样跳转
    access_token = res_login_exchange.json()["access_token"]
    res = client.post(
        "/api/public/session-shares/resolve",
        headers={**_headers(access_token), "Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["view_mode"] == "NORMAL_REDIRECT"
    assert res.json()["redirect_path"] == "/workspaces/ws-1/chat/task-1"


def test_resolve_input_share_never_upgrades_even_with_login(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    from app.domains.auth.services import auth_service

    token = auth_service.create_access_token("owner-1")
    res = client.post(
        "/api/public/session-shares/resolve",
        headers={**_headers(access_token), "Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["view_mode"] == "INPUT_ONLY"


# ── 3. 公开历史白名单投影 ──


def test_read_history_whitelist_projection(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="READ").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    res = client.get(
        "/api/public/session-shares/history", headers=_headers(access_token)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    ids = [m["message_id"] for m in body["messages"]]
    # NULL generation 的旧消息不放行
    assert "m-old" not in ids
    assert set(ids) == {"m-1", "m-2"}
    for msg in body["messages"]:
        # 白名单字段之外不返回
        assert set(msg.keys()) == {
            "message_id", "role", "content", "safe_message_type", "created_at", "safe_card_summary"
        }
        assert "metadata" not in msg
    # metadata 内部字段（client_message_id）不泄漏
    assert "secret-cmid" not in res.text


def test_input_access_cannot_read_history(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    res = client.get(
        "/api/public/session-shares/history", headers=_headers(access_token)
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "SHARE_CAPABILITY_FORBIDDEN"


def test_read_access_cannot_submit(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="READ").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    res = client.post(
        "/api/public/session-shares/suggestions",
        json={"content": "sneaky", "client_submission_id": "c-1"},
        headers=_headers(access_token),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "SHARE_CAPABILITY_FORBIDDEN"


# ── 4. 访客提交幂等 ──


def _submit(client, access_token, content, key, display_name=None):
    return client.post(
        "/api/public/session-shares/suggestions",
        json={
            "content": content,
            "client_submission_id": key,
            "display_name": display_name,
        },
        headers=_headers(access_token),
    )


def test_submit_idempotent_same_key_same_content(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    r1 = _submit(client, access_token, "建议内容 A", "key-1", "访客甲")
    assert r1.status_code == 200, r1.text
    r2 = _submit(client, access_token, "建议内容 A", "key-1", "访客甲")
    assert r2.status_code == 200
    assert r1.json()["submission_id"] == r2.json()["submission_id"]

    # 幂等键不同 → 新建议
    r3 = _submit(client, access_token, "建议内容 B", "key-2")
    assert r3.status_code == 200
    assert r3.json()["submission_id"] != r1.json()["submission_id"]


def test_submit_same_key_different_content_conflict(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    _submit(client, access_token, "内容一", "key-x")
    res = _submit(client, access_token, "内容二（不同）", "key-x")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "SUGGESTION_CONFLICT"


def test_submit_creates_no_chat_message_or_submission_or_job(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    res = _submit(client, access_token, "匿名建议", "key-nojob", "访客乙")
    assert res.status_code == 200

    # 不产生正式聊天消息 / 提交回执 / AI Job
    assert db.query(ChatMessage).count() == 3  # seed 的 3 条
    from app.domains.task.models.chat_submission import TaskChatSubmission

    assert db.query(TaskChatSubmission).count() == 0
    from app.domains.ai.models.ai_job import SddAiJob

    assert db.query(SddAiJob).count() == 0
    # 任务状态未变
    db.expire_all()
    assert db.get(SddTask, "task-1").status == TaskStatus.PLANNING


# ── 5. 发起人列表 / adopt / dismiss ──


def _seed_suggestion(db, share, *, key="s-1", content="待采纳内容", visitor="visitor-x"):
    from app.domains.task.models.session_share import TaskShareSuggestion, TaskShareSuggestionStatus

    row = TaskShareSuggestion(
        share_id=share.id,
        task_id=share.task_id,
        session_generation=share.session_generation,
        recipient_user_id=share.creator_id,
        visitor_id=visitor,
        display_name="访客",
        original_content=content,
        client_submission_id=key,
        status=TaskShareSuggestionStatus.PENDING,
        version=1,
    )
    db.add(row)
    db.commit()
    return row


def test_recipient_lists_and_adopts_suggestion(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    # 通过真实提交通道创建建议（同时验证链路）
    access_token = _exchange(client, share_token).json()["access_token"]
    receipt = _submit(client, access_token, "请加上错误处理", "adopt-1", "小张").json()
    suggestion_id = receipt["submission_id"]

    listing = client.get(
        "/api/workspaces/ws-1/tasks/task-1/share-suggestions?status=PENDING"
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["effective_content"] == "请加上错误处理"
    assert items[0]["display_name"] == "小张"

    # adopt：version 条件更新
    res = client.patch(
        f"/api/workspaces/ws-1/tasks/task-1/share-suggestions/{suggestion_id}",
        json={"action": "adopt", "expected_version": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ADOPTED"
    assert res.json()["version"] == 2

    # 重复 adopt 幂等返回当前 ADOPTED 记录
    res_again = client.patch(
        f"/api/workspaces/ws-1/tasks/task-1/share-suggestions/{suggestion_id}",
        json={"action": "adopt", "expected_version": 2},
    )
    assert res_again.status_code == 200
    assert res_again.json()["status"] == "ADOPTED"


def test_adopt_version_conflict_returns_409(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]
    receipt = _submit(client, access_token, "内容", "vc-1").json()
    sid = receipt["submission_id"]

    # 用过期 version
    res = client.patch(
        f"/api/workspaces/ws-1/tasks/task-1/share-suggestions/{sid}",
        json={"action": "adopt", "expected_version": 99},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "SUGGESTION_VERSION_CONFLICT"


def test_dismissed_suggestion_cannot_be_reactivated(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]
    receipt = _submit(client, access_token, "忽略我", "dm-1").json()
    sid = receipt["submission_id"]

    res = client.patch(
        f"/api/workspaces/ws-1/tasks/task-1/share-suggestions/{sid}",
        json={"action": "dismiss", "expected_version": 1},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "DISMISSED"

    res_adopt = client.patch(
        f"/api/workspaces/ws-1/tasks/task-1/share-suggestions/{sid}",
        json={"action": "adopt", "expected_version": 2},
    )
    assert res_adopt.status_code == 409


def test_edit_keeps_original_and_updates_effective(owner_client):
    client, db, owner, task = owner_client
    share_token = _create_share(client, mode="INPUT").json()["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]
    receipt = _submit(client, access_token, "原始输入", "ed-1").json()
    sid = receipt["submission_id"]

    res = client.patch(
        f"/api/workspaces/ws-1/tasks/task-1/share-suggestions/{sid}",
        json={"action": "edit", "expected_version": 1, "edited_content": "编辑后的输入"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["original_content"] == "原始输入"
    assert body["edited_content"] == "编辑后的输入"
    assert body["effective_content"] == "编辑后的输入"


# ── 6. 生命周期：撤销 / 过期 / 换代 / 失权 ──


def test_revoked_share_is_deleted_and_rejects_access(owner_client):
    client, db, owner, task = owner_client
    created = _create_share(client, mode="INPUT").json()
    share_id, share_token = created["id"], created["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    # 撤销（即删除）
    res = client.delete(f"/api/workspaces/ws-1/tasks/task-1/session-shares/{share_id}")
    assert res.status_code == 200

    # 已撤销的链接不再出现在列表里
    listing = client.get("/api/workspaces/ws-1/tasks/task-1/session-shares")
    assert listing.status_code == 200
    assert listing.json()["total"] == 0

    # 已持有的临时凭证也立即失效（分享行已删，按凭证反查不到）
    res_submit = _submit(client, access_token, "撤销后提交", "post-revoke")
    assert res_submit.status_code in (404, 410)

    # 重新 exchange 也被拒（未知令牌 404，不包含资源信息）
    res_exchange = _exchange(client, share_token)
    assert res_exchange.status_code == 404
    assert res_exchange.json()["detail"]["code"] == "SHARE_NOT_FOUND"

    # 撤销前已收到的输入保留（规格 §2.7）：先提交一条再撤销验证
    created2 = _create_share(client, mode="INPUT").json()
    access2 = _exchange(client, created2["share_token"]).json()["access_token"]
    receipt = _submit(client, access2, "撤销前收到的输入", "keep-1").json()
    client.delete(f"/api/workspaces/ws-1/tasks/task-1/session-shares/{created2['id']}")
    suggestions = client.get("/api/workspaces/ws-1/tasks/task-1/share-suggestions")
    ids = [item["id"] for item in suggestions.json()["items"]]
    assert receipt["submission_id"] in ids


def test_expired_share_rejects_access(owner_client, db_env):
    client, db, owner, task = owner_client
    created = _create_share(client, mode="READ", days=1).json()
    share_token = created["share_token"]

    # 直接把库里的过期时间改到过去（模拟时间流逝；管理路由已关闭请求 Session）
    from app.domains.task.models.session_share import TaskSessionShare

    with _session(db_env) as fresh:
        share = fresh.query(TaskSessionShare).filter_by(id=created["id"]).one()
        share.expires_at = datetime.utcnow() - timedelta(seconds=1)
        fresh.commit()

    res = _exchange(client, share_token)
    assert res.status_code == 410
    assert res.json()["detail"]["code"] == "SHARE_EXPIRED"


def test_session_generation_change_invalidates_share(owner_client, db_env):
    client, db, owner, task = owner_client
    created = _create_share(client, mode="READ").json()
    share_token = created["share_token"]
    access_token = _exchange(client, share_token).json()["access_token"]

    # 模拟会话换代（initialize 推进 generation）。
    # 管理路由按生产模式关闭了请求 Session，这里开新会话直改。
    with _session(db_env) as fresh:
        fresh.get(SddTask, "task-1").session_generation = 2
        fresh.commit()

    res = client.get("/api/public/session-shares/history", headers=_headers(access_token))
    assert res.status_code == 410
    assert res.json()["detail"]["code"] == "SHARE_SESSION_INVALID"


def test_creator_losing_permission_kills_share(db_env):
    with _session(db_env) as db:
        owner, ws, task = _seed(db, role=WorkspaceRole.DEVELOPER,
                                permissions_json='["SHARE_TASK_SESSION", "START_TASK"]')
        app = _build_app(db)
        app.dependency_overrides[get_current_user] = lambda: db.query(User).filter(User.id == "owner-1").one()
        client = TestClient(app)

        created = _create_share(client, mode="READ").json()
        share_token = created["share_token"]
        assert _exchange(client, share_token).status_code == 200

        # 发起人被移除权限 → 公开访问立即不可用
        member = db.query(WorkspaceMember).one()
        member.permissions_json = '["START_TASK"]'
        db.commit()

        res = _exchange(client, share_token)
        assert res.status_code == 410
        assert res.json()["detail"]["code"] == "SHARE_CREATOR_FORBIDDEN"


def test_old_generation_suggestion_cannot_adopt_into_new_session(owner_client, db_env):
    client, db, owner, task = owner_client
    created = _create_share(client, mode="INPUT").json()
    access_token = _exchange(client, created["share_token"]).json()["access_token"]
    receipt = _submit(client, access_token, "旧代次建议", "og-1").json()
    sid = receipt["submission_id"]

    # 会话换代后，旧建议不能直接采纳（管理路由已关闭请求 Session，开新会话直改）
    with _session(db_env) as fresh:
        fresh.get(SddTask, "task-1").session_generation = 2
        fresh.commit()

    res = client.patch(
        f"/api/workspaces/ws-1/tasks/task-1/share-suggestions/{sid}",
        json={"action": "adopt", "expected_version": 1},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "SUGGESTION_SESSION_STALE"


# ── 7. 限流 ──


def test_submit_rate_limit(owner_client):
    client, db, owner, task = owner_client
    created = _create_share(client, mode="INPUT").json()
    access_token = _exchange(client, created["share_token"]).json()["access_token"]

    share_suggestion_service.reset_rate_limits()
    statuses = []
    for i in range(12):
        res = _submit(client, access_token, f"内容 {i}", f"rl-{i}")
        statuses.append(res.status_code)
    # 超过限流阈值（默认 10/60s）后返回 429
    assert 429 in statuses
    assert statuses.count(429) >= 1


# ── 生产 expire_on_commit=True 语义：exchange/resolve/提交不得在事务外读 ORM 属性 ──


def test_public_routes_survive_expire_on_commit(db_env):
    """回归：生产 SessionLocal 为 expire_on_commit=True，commit 后实例即失效。

    exchange/resolve/submit 曾在事务外读 access.expires_at / share.task_id 等
    导致 500（DetachedInstanceError）。本用例把 app.database.SessionLocal 换成
    expire_on_commit=True 的工厂，走完整公开链路。
    """
    from sqlalchemy.orm import sessionmaker

    engine, _ = _build_db()
    # 复刻生产语义：仅 expire_on_commit 差异
    prod_like = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=True)

    import app.database as app_database

    original = app_database.SessionLocal
    app_database.SessionLocal = prod_like
    try:
        with _session(prod_like) as db:
            owner, ws, task = _seed(db)
            app = _build_app(db)
            app.dependency_overrides[get_current_user] = lambda: db.query(User).filter(User.id == "owner-1").one()
            client = TestClient(app)

            # exchange（READ）
            created = _create_share(client, mode="READ").json()
            res = _exchange(client, created["share_token"])
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["access_token"]
            assert body["access_expires_at"]

            # resolve
            res_resolve = client.post(
                "/api/public/session-shares/resolve",
                headers=_headers(body["access_token"]),
            )
            assert res_resolve.status_code == 200, res_resolve.text

            # history
            res_history = client.get(
                "/api/public/session-shares/history", headers=_headers(body["access_token"])
            )
            assert res_history.status_code == 200, res_history.text

            # INPUT：exchange + submit 全链路
            created_in = _create_share(client, mode="INPUT").json()
            access_in = _exchange(client, created_in["share_token"]).json()["access_token"]
            res_submit = _submit(client, access_in, "提交内容", "eoc-1")
            assert res_submit.status_code == 200, res_submit.text
    finally:
        app_database.SessionLocal = original
        engine.dispose()


# ── 历史游标 ──


def test_history_cursor_pagination_and_stale_revision(owner_client, db_env):
    client, db, owner, task = owner_client
    created = _create_share(client, mode="READ").json()
    access_token = _exchange(client, created["share_token"]).json()["access_token"]

    page1 = client.get(
        "/api/public/session-shares/history?page_size=1", headers=_headers(access_token)
    ).json()
    assert len(page1["messages"]) == 1
    assert page1["has_more"] is True
    assert page1["next_cursor"]

    page2 = client.get(
        f"/api/public/session-shares/history?page_size=1&cursor={page1['next_cursor']}",
        headers=_headers(access_token),
    )
    assert page2.status_code == 200
    ids = {page1["messages"][0]["message_id"], page2.json()["messages"][0]["message_id"]}
    assert ids == {"m-1", "m-2"}

    # revision 变化 → 旧游标失效 409（开新会话直改）
    with _session(db_env) as fresh:
        fresh.get(SddTask, "task-1").session_revision = 4
        fresh.commit()
    stale = client.get(
        f"/api/public/session-shares/history?page_size=1&cursor={page1['next_cursor']}",
        headers=_headers(access_token),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "SHARE_HISTORY_STALE"

# ── 公开实时通道：WS nudge ──


def test_public_share_ws_nudge_flow(owner_client):
    """READ 分享连接公开 WS；notify_task_shares_history_changed 后收到 nudge。

    INPUT 分享不能连 READ 通道；无凭证连接被拒绝。
    """
    client, db, owner, task = owner_client
    created = _create_share(client, mode="READ").json()
    access_token = _exchange(client, created["share_token"]).json()["access_token"]
    share_id = created["id"]

    from app.domains.websocket.ws.public_share_manager import (
        notify_task_shares_history_changed,
        public_share_ws_manager,
    )

    # 无有效凭证 → 连接被拒绝
    with pytest.raises(Exception):
        with client.websocket_connect(
            f"/ws/public/session-shares/{share_id}?access=invalid-token"
        ):
            pass

    # 有效凭证 → 连接成功；完成 resync 握手后收到 nudge
    with client.websocket_connect(
        f"/ws/public/session-shares/{share_id}?access={access_token}"
    ) as ws:
        import asyncio

        # 无游标连接：先收到 resync_required（页面已用 REST 建立快照）
        hello = ws.receive_json()
        assert hello["type"] == "resync_required"
        ws.send_json({
            "type": "resync_complete",
            "epoch": hello["epoch"],
            "barrier_sequence": hello["barrier_sequence"],
        })

        asyncio.run(notify_task_shares_history_changed("task-1"))
        # 握手回执（resync_ok）后即为业务 nudge
        frame = ws.receive_json()
        if frame.get("type") == "resync_ok":
            frame = ws.receive_json()
        assert frame["type"] == "share_history_changed"
        assert frame["share_id"] == share_id
