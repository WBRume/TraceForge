import os
import sys
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User  # noqa: E402
from app.domains.notification.models.notification import SddUserNotification  # noqa: E402
from app.domains.notification.routers import notification as notification_router  # noqa: E402
from app.domains.notification.services import notification_service  # noqa: E402
from app.domains.notification.types import get_notification_type, is_registered  # noqa: E402
from app.domains.task.services import pre_input_service  # noqa: F401,E402  # 触发全量模型注册,保证 create_all 可用


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    user = User(id="u-1", email="u1@example.com", hashed_password="x", display_name="U1")
    other = User(id="u-2", email="u2@example.com", hashed_password="x", display_name="U2")
    db.add_all([user, other])
    db.commit()
    return SessionLocal, user, other


def _seed_notifications(db, user_id):
    unread = SddUserNotification(
        id="n-unread",
        recipient_user_id=user_id,
        type="pre_input_mention",
        title="unread one",
        payload_json={"task_id": "t-1", "workspace_id": "ws-1"},
    )
    read = SddUserNotification(
        id="n-read",
        recipient_user_id=user_id,
        type="pre_input_submitted",
        title="read one",
        read_at=datetime.utcnow(),
    )
    foreign = SddUserNotification(
        id="n-foreign",
        recipient_user_id="u-2",
        type="pre_input_mention",
        title="not mine",
    )
    db.add_all([unread, read, foreign])
    db.commit()
    return unread, read, foreign


def _build_app(SessionLocal, current_user_state):
    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(notification_router.router, prefix="/api")
    app.dependency_overrides[notification_router.get_db] = _override_db
    app.dependency_overrides[notification_router.get_current_user] = lambda: current_user_state["user"]
    return app


def test_delete_notification_consumes_single_message():
    SessionLocal, user, _other = _build_db()
    db = SessionLocal()
    _seed_notifications(db, user.id)
    db.close()

    client = TestClient(_build_app(SessionLocal, {"user": user}))

    resp = client.delete("/api/notifications/n-unread")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "was_unread": True}

    count = client.get("/api/notifications/unread-count").json()
    assert count == {"count": 0}

    items = client.get("/api/notifications").json()["items"]
    assert [item["id"] for item in items] == ["n-read"]


def test_delete_notification_rejects_missing_and_foreign():
    SessionLocal, user, other = _build_db()
    db = SessionLocal()
    _seed_notifications(db, user.id)
    db.close()

    client = TestClient(_build_app(SessionLocal, {"user": user}))
    assert client.delete("/api/notifications/n-missing").status_code == 404

    # 他人通知不可删
    assert client.delete("/api/notifications/n-foreign").status_code == 404

    foreign_client = TestClient(_build_app(SessionLocal, {"user": other}))
    assert foreign_client.delete("/api/notifications/n-unread").status_code == 404


def test_clear_notifications_removes_all_owned_only():
    SessionLocal, user, _other = _build_db()
    db = SessionLocal()
    _seed_notifications(db, user.id)
    db.close()

    client = TestClient(_build_app(SessionLocal, {"user": user}))
    resp = client.delete("/api/notifications")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2, "unread_deleted": 1}

    assert client.get("/api/notifications").json()["items"] == []
    assert client.get("/api/notifications/unread-count").json() == {"count": 0}

    # 他人的通知不受影响
    db = SessionLocal()
    remaining = db.query(SddUserNotification).all()
    assert [row.id for row in remaining] == ["n-foreign"]
    db.close()


def test_service_delete_returns_was_unread():
    SessionLocal, user, _other = _build_db()
    db = SessionLocal()
    unread, read, _foreign = _seed_notifications(db, user.id)

    assert notification_service.delete_notification(db, user.id, unread.id) is True
    assert notification_service.delete_notification(db, user.id, read.id) is False
    assert notification_service.delete_notification(db, user.id, "n-missing") is None
    db.close()


def test_types_endpoint_lists_registered_metadata():
    SessionLocal, user, _other = _build_db()

    # /types 不依赖数据库,仅验证注册表元信息
    client = TestClient(_build_app(SessionLocal, {"user": user}))
    resp = client.get("/api/notifications/types")
    assert resp.status_code == 200
    codes = {item["code"] for item in resp.json()}
    assert {"pre_input_mention", "pre_input_submitted"} <= codes

    info = get_notification_type("pre_input_mention")
    assert info is not None and info.category == "collab"
    assert "task_id" in info.payload_keys
    assert is_registered("pre_input_submitted")
    assert not is_registered("not_a_real_type")
