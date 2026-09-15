"""Workspace invite-link concurrency integration tests (MySQL instance).

doc 审计 0c381413 §4.3：在独立 MySQL 测试库上验证真实行锁与事务边界
（SQLite 结果不能称为 MySQL 实测）。实例不可达时整体跳过。测试库为
独立 schema（``traceforge_invite_link_audit``），测完即删，不触碰
``sdd_platform`` 数据。

验收项（§4.3）：
1. max_uses=1，两个用户同时 accept：恰好一个新增成功，另一个
   unavailable；used_count=1。
2. 同用户并发 accept（不同链接）：一条成员记录，只扣一次。
3. revoke 先持有相同锁并提交，accept 后取得锁：必须拒绝；反向顺序允许
   先完成的领取成功。
4. 持锁等待期间链接过期：取得锁后拒绝，不新增成员。
5. 在成员插入与提交前故障注入：成员与计数均回滚。
"""

import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.workspace.models.invite_link import WorkspaceInviteLink
from app.domains.workspace.services import workspace_service as ws

TEST_SCHEMA = "traceforge_invite_link_audit"


def _mysql_reachable() -> bool:
    try:
        import pymysql

        conn = pymysql.connect(
            host=settings.DB_HOST,
            port=int(settings.DB_PORT),
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mysql_reachable(), reason="MySQL instance unreachable"
)


def _server_url() -> str:
    return (
        f"mysql+pymysql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/?charset=utf8mb4"
    )


def _schema_url() -> str:
    return (
        f"mysql+pymysql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{TEST_SCHEMA}?charset=utf8mb4"
    )


@pytest.fixture(scope="module")
def mysql_engine():
    admin = create_engine(_server_url(), connect_args={"connect_timeout": 5})
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_SCHEMA}"))
        conn.execute(
            text(
                f"CREATE DATABASE {TEST_SCHEMA} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        conn.commit()
    engine = create_engine(
        _schema_url(), pool_pre_ping=True, pool_size=8, max_overflow=8
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_SCHEMA}"))
            conn.commit()
        admin.dispose()


@pytest.fixture()
def clean_tables(mysql_engine):
    with mysql_engine.begin() as conn:
        conn.execute(text("DELETE FROM workspace_members"))
        conn.execute(text("DELETE FROM workspace_invite_links"))
        conn.execute(text("DELETE FROM workspaces"))
        conn.execute(text("DELETE FROM users"))
    factory = sessionmaker(bind=mysql_engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                User(
                    id=x,
                    email=f"{x}@mysql-audit.invalid",
                    hashed_password="x",
                    display_name=x,
                )
                for x in ("owner", "user-a", "user-b")
            ]
        )
        db.add(Workspace(id="ws-m", name="audit-mysql", owner_id="owner"))
        db.commit()
    return mysql_engine


def _factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def _create_link(db, token: str, max_uses=None) -> WorkspaceInviteLink:
    link = WorkspaceInviteLink(
        id=f"link-{token}",
        workspace_id="ws-m",
        token=token,
        role=WorkspaceRole.DEVELOPER,
        permissions_json="[]",
        max_uses=max_uses,
        used_count=0,
        created_by="owner",
    )
    db.add(link)
    db.commit()
    return link


def _run_concurrently(worker_count: int, target):
    """Start all workers together; collect (ok/err, value) per worker."""
    start = threading.Barrier(worker_count)
    results: dict = {}

    def runner(index):
        start.wait(timeout=10)
        try:
            results[index] = ("ok", target(index))
        except Exception as exc:  # noqa: BLE001 - 并发结果按异常类型断言
            results[index] = ("err", exc)

    threads = [
        threading.Thread(target=runner, args=(i,), daemon=True)
        for i in range(worker_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "worker deadlocked"
    return results


def _outcomes(results):
    return list(results.values())


def test_concurrent_accept_single_use_link_exactly_one_wins(clean_tables):
    """§4.3-1：max_uses=1 两个用户同时 accept → 恰好一个成功，另一个 unavailable。"""
    factory = _factory(clean_tables)
    with factory() as db:
        _create_link(db, "tok-1", max_uses=1)

    def accept(index):
        user_id = "user-a" if index == 0 else "user-b"
        with factory() as db:
            member, link, already = ws.accept_invite_in_txn(
                db, "tok-1", db.get(User, user_id).id
            )
            db.commit()
            return member.user_id, link.used_count, already

    results = _run_concurrently(2, accept)
    outcomes = _outcomes(results)
    winners = [value for state, value in outcomes if state == "ok"]
    losers = [value for state, value in outcomes if state == "err"]
    assert len(winners) == 1 and len(losers) == 1, results
    assert all(isinstance(exc, ValueError) for exc in losers), results
    assert "exhausted" in str(losers[0]).lower(), results

    winner_user, _, already = winners[0]
    assert already is False and winner_user in ("user-a", "user-b")
    with factory() as db:
        members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == "ws-m").count()
        used = db.get(WorkspaceInviteLink, "link-tok-1").used_count
    assert members == 1 and used == 1, (members, used)


def test_same_user_concurrent_accept_via_two_links_is_idempotent(clean_tables):
    """§4.3-2：同用户并发 accept（不同链接）→ 一条成员记录，只扣一次。"""
    factory = _factory(clean_tables)
    with factory() as db:
        _create_link(db, "tok-l1", max_uses=1)
        _create_link(db, "tok-l2", max_uses=1)

    def accept(index):
        token = "tok-l1" if index == 0 else "tok-l2"
        with factory() as db:
            member, link, already = ws.accept_invite_in_txn(
                db, token, db.get(User, "user-a").id
            )
            db.commit()
            return member.user_id, token, already

    results = _run_concurrently(2, accept)
    outcomes = _outcomes(results)
    values = [value for state, value in outcomes if state == "ok"]
    assert len(values) == 2, results
    # 两条路径都必须收敛为"已存在成员"：一条真正创建，另一条 already_member。
    assert sorted(already for _, _, already in values) == [False, True], results

    with factory() as db:
        members = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == "ws-m",
                WorkspaceMember.user_id == "user-a",
            )
            .count()
        )
        used1 = db.get(WorkspaceInviteLink, "link-tok-l1").used_count
        used2 = db.get(WorkspaceInviteLink, "link-tok-l2").used_count
    assert members == 1, (members, results)
    assert used1 + used2 == 1, ("count deducted exactly once", used1, used2, results)


def test_revoke_before_accept_rejects_late_locker(clean_tables):
    """§4.3-3a：revoke 先持有相同锁并提交，accept 后取得锁 → 必须拒绝。"""
    factory = _factory(clean_tables)
    with factory() as db:
        link = _create_link(db, "tok-r1", max_uses=5)

    # 先由 revoke 持锁（不提交），accept 线程此时必然阻塞在 Workspace 行锁上。
    db_a = factory()
    revoked = ws.revoke_invite_link_in_txn(db_a, "ws-m", link.id)
    assert revoked is not None and revoked.revoked_at is not None

    outcome = {}

    def accept(index):
        with factory() as db:
            try:
                member, _, already = ws.accept_invite_in_txn(
                    db, "tok-r1", db.get(User, "user-a").id
                )
                db.commit()
                outcome["result"] = ("ok", already)
            except ValueError as exc:
                outcome["result"] = ("err", str(exc))

    thread = threading.Thread(target=accept, args=(0,), daemon=True)
    thread.start()
    time.sleep(0.5)  # 让 accept 线程已阻塞在锁上
    db_a.commit()
    thread.join(timeout=30)
    assert not thread.is_alive(), "accept worker deadlocked"
    assert outcome.get("result", (None, None))[0] == "err", outcome
    assert "revoked" in str(outcome["result"][1]).lower(), outcome

    with factory() as db:
        members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == "ws-m").count()
    assert members == 0, members


def test_accept_before_revoke_keeps_completed_claim(clean_tables):
    """§4.3-3b：反向顺序 → 允许先完成的领取成功，随后 revoke 正常生效。"""
    factory = _factory(clean_tables)
    with factory() as db:
        link = _create_link(db, "tok-r2", max_uses=5)

    with factory() as db:
        member, _, already = ws.accept_invite_in_txn(
            db, "tok-r2", db.get(User, "user-a").id
        )
        db.commit()
    assert already is False

    with factory() as db:
        revoked = ws.revoke_invite_link_in_txn(db, "ws-m", link.id)
        db.commit()
    assert revoked.revoked_at is not None

    with factory() as db:
        members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == "ws-m").count()
        used = db.get(WorkspaceInviteLink, "link-tok-r2").used_count
    assert members == 1 and used == 1, (members, used)


def test_link_expires_while_lock_is_held_rejects_after_acquire(clean_tables):
    """§4.3-4：持锁等待期间链接过期 → 取得锁后拒绝，不新增成员。"""
    factory = _factory(clean_tables)
    with factory() as db:
        _create_link(db, "tok-x", max_uses=5)

    # 第一事务只持锁不提交：accept 线程必须阻塞等待。
    holder = factory()
    holder.query(Workspace).filter(Workspace.id == "ws-m").with_for_update().first()

    outcome = {}

    def accept(index):
        with factory() as db:
            try:
                member, _, already = ws.accept_invite_in_txn(
                    db, "tok-x", db.get(User, "user-a").id
                )
                db.commit()
                outcome["result"] = ("ok", already)
            except ValueError as exc:
                outcome["result"] = ("err", str(exc))

    thread = threading.Thread(target=accept, args=(0,), daemon=True)
    thread.start()
    time.sleep(0.5)  # accept 线程已阻塞在 Workspace 行锁上
    # 等待期间把链接过期（link 行未被锁，独立连接可写）。
    with factory() as db:
        link = db.get(WorkspaceInviteLink, "link-tok-x")
        link.expires_at = ws._utcnow() - timedelta(seconds=1)
        db.commit()
    time.sleep(1.0)
    holder.commit()
    holder.close()
    thread.join(timeout=30)
    assert not thread.is_alive(), "accept worker deadlocked"
    assert outcome.get("result", (None, None))[0] == "err", outcome
    assert "expired" in str(outcome["result"][1]).lower(), outcome

    with factory() as db:
        members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == "ws-m").count()
        used = db.get(WorkspaceInviteLink, "link-tok-x").used_count
    assert members == 0 and used == 0, (members, used)


def test_failure_injection_before_commit_rolls_back_member_and_count(clean_tables):
    """§4.3-5：成员插入与提交之间故障注入 → 成员与计数均回滚。"""
    factory = _factory(clean_tables)
    with factory() as db:
        _create_link(db, "tok-f", max_uses=3)

    with pytest.raises(RuntimeError, match="injected before commit"):
        with factory() as db:
            member, link, already = ws.accept_invite_in_txn(
                db, "tok-f", db.get(User, "user-a").id
            )
            assert already is False
            assert member.id is not None
            raise RuntimeError("injected before commit")

    with factory() as db:
        members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == "ws-m").count()
        used = db.get(WorkspaceInviteLink, "link-tok-f").used_count
    assert members == 0 and used == 0, (members, used)

    # 注入失败后链接仍可用：正常领取成功且只扣一次；同用户重试幂等不扣次数。
    with factory() as db:
        member, _, already = ws.accept_invite_in_txn(
            db, "tok-f", db.get(User, "user-b").id
        )
        db.commit()
    assert already is False
    with factory() as db:
        member_again, _, already_again = ws.accept_invite_in_txn(
            db, "tok-f", db.get(User, "user-b").id
        )
        db.commit()
    assert already_again is True and member_again.id == member.id
    with factory() as db:
        assert db.get(WorkspaceInviteLink, "link-tok-f").used_count == 1
