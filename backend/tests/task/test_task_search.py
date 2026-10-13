from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.task.services.task_records.queries import list_tasks


@pytest.fixture
def search_db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(User(id="user", email="search@example.com", hashed_password="x", display_name="Search"))
        db.add_all([Workspace(id=ws, name=ws, owner_id="user") for ws in ("ws", "other-ws")])
        for task_id, name, workspace_id, status, task_type in [
            ("target-a", "Search 100%_ready", "ws", TaskStatus.DONE, TaskType.DIAGNOSIS),
            ("target-b", "Search second", "ws", TaskStatus.DONE, TaskType.DIAGNOSIS),
            ("target-c", "Search failed", "ws", TaskStatus.FAILED, TaskType.DIAGNOSIS),
            ("target-d", "Search development", "ws", TaskStatus.DONE, TaskType.DEVELOPMENT),
            ("hidden", "Search pending", "ws", TaskStatus.PROVISIONING, TaskType.DIAGNOSIS),
            ("cross", "Search elsewhere", "other-ws", TaskStatus.DONE, TaskType.DIAGNOSIS),
        ]:
            db.add(
                SddTask(
                    id=task_id,
                    name=name,
                    workspace_id=workspace_id,
                    creator_id="user",
                    project_path=".",
                    status=status,
                    task_type=task_type,
                    created_at=datetime(2026, 1, 1),
                )
            )
        db.commit()
        yield db
    engine.dispose()


@pytest.mark.parametrize(
    ("search", "expected"),
    [
        (" sEaRcH ", {"target-a", "target-b", "target-c", "target-d"}),
        ("TARGET-B", {"target-b"}),
        ("%_", {"target-a"}),
        ("missing", set()),
        ("  ", {"target-a", "target-b", "target-c", "target-d"}),
    ],
)
def test_search_matches_literal_name_or_id_with_workspace_scope(search_db, search, expected):
    items, total = list_tasks(search_db, "ws", search=search)
    assert {task.id for task in items} == expected
    assert total == len(expected)


def test_search_combines_filters_before_pagination(search_db):
    filters = {
        "search": "Search",
        "status_filter": "DONE",
        "task_type": "DIAGNOSIS",
        "relation": "created_by_me",
        "current_user_id": "user",
        "independent": True,
    }
    first, total = list_tasks(search_db, "ws", page=1, page_size=1, **filters)
    second, _ = list_tasks(search_db, "ws", page=2, page_size=1, **filters)
    assert total == 2
    assert [task.id for task in first + second] == ["target-b", "target-a"]
    probe, _ = list_tasks(search_db, "ws", page_size=1, limit=2, with_total=False, **filters)
    assert [task.id for task in probe] == ["target-b", "target-a"]
