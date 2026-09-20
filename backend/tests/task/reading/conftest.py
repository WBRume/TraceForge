"""阅读进度测试共享设施：全模型注册 + SQLite 内存库 + 种子数据。"""
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TESTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if TESTS_ROOT not in sys.path:
    sys.path.insert(0, TESTS_ROOT)

# 全量模型注册（与生产 app 全量加载等价），保证 create_all 覆盖 FK 关系
import importlib  # noqa: E402
import pkgutil  # noqa: E402

from app import domains as _domains  # noqa: E402

for _name in [n for _, n, _ in pkgutil.iter_modules(_domains.__path__)]:
    try:
        _models_pkg = importlib.import_module(f"app.domains.{_name}.models")
    except ModuleNotFoundError:
        continue
    if not hasattr(_models_pkg, "__path__"):
        continue
    for _, _mod, _ in pkgutil.walk_packages(_models_pkg.__path__, prefix=f"app.domains.{_name}.models."):
        importlib.import_module(_mod)

from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace, WorkspaceMember  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def seeded_db(db):
    """用户 A/B + 工作区 + 任务（reading_ready=true）。"""
    user_a = User(id="user-a", email="a@example.com", hashed_password="x", display_name="A")
    user_b = User(id="user-b", email="b@example.com", hashed_password="x", display_name="B")
    db.add_all([user_a, user_b])
    db.commit()
    ws = Workspace(id="ws-1", name="WS", owner_id=user_a.id, project_path="G:/repo")
    db.add(ws)
    db.commit()
    for user in (user_a, user_b):
        db.add(WorkspaceMember(id=f"m-{user.id}", workspace_id=ws.id, user_id=user.id))
    task = SddTask(
        id="task-1", workspace_id=ws.id, creator_id=user_a.id, name="T",
        project_path="G:/repo/task", status=TaskStatus.PENDING,
        session_generation=0, session_revision=0,
        reading_change_seq=0, reading_epoch=1, reading_ready=True,
    )
    db.add(task)
    db.commit()
    return {"db": db, "ws_id": ws.id, "task_id": task.id, "user_a": user_a.id, "user_b": user_b.id}
