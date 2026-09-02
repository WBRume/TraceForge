import os
import sys
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.notification.models.notification import SddUserNotification  # noqa: E402
from app.domains.task.models.chat import ChatMessage  # noqa: E402
from app.domains.task.models.pre_input import SddTaskPreInput  # noqa: E402
from app.domains.task.models.task import SddTask, SddTaskFollower  # noqa: E402
from app.domains.task.services import task_service  # noqa: E402


def test_task_advanced_relations_are_scoped_to_current_user_and_workspace():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        user = User(id="user-1", email="one@example.com", hashed_password="x", display_name="One")
        other = User(id="user-2", email="two@example.com", hashed_password="x", display_name="Two")
        workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id)
        other_workspace = Workspace(id="ws-2", name="Other", owner_id=other.id)
        created = SddTask(id="task-created", workspace_id="ws-1", creator_id=user.id, name="Created", project_path=".")
        mentioned = SddTask(id="task-mentioned", workspace_id="ws-1", creator_id=other.id, name="Mentioned", project_path=".")
        messaged = SddTask(id="task-messaged", workspace_id="ws-1", creator_id=other.id, name="Messaged", project_path=".")
        followed = SddTask(id="task-followed", workspace_id="ws-1", creator_id=other.id, name="Followed", project_path=".")
        cross_workspace = SddTask(id="task-cross", workspace_id="ws-2", creator_id=user.id, name="Cross", project_path=".")
        db.add_all([user, other, workspace, other_workspace, created, mentioned, messaged, followed, cross_workspace])
        db.flush()
        db.add(SddTaskPreInput(
            task_id=mentioned.id,
            workspace_id=workspace.id,
            creator_id=other.id,
            main_text="Please review",
            mentioned_user_ids=[user.id],
            deadline_at=datetime(2030, 1, 1),
        ))
        db.add(ChatMessage(
            task_id=messaged.id,
            workspace_id=workspace.id,
            creator_id=user.id,
            role="user",
            content="I sent this",
            message_type="text",
        ))
        db.add(SddTaskFollower(task_id=followed.id, workspace_id=workspace.id, user_id=user.id))
        db.commit()

        def ids(relation):
            items, total = task_service.list_tasks(
                db,
                workspace.id,
                relation=relation,
                current_user_id=user.id,
                page_size=20,
            )
            assert total == len(items)
            return {item.id for item in items}

        assert ids("created_by_me") == {created.id}
        assert ids("mentioned_me") == {mentioned.id}
        assert ids("messaged_by_me") == {messaged.id}
        assert ids("followed_by_me") == {followed.id}
        assert ids("created_by_me,followed_by_me") == {created.id, followed.id}
        assert cross_workspace.id not in ids("created_by_me")

        assert task_service.set_task_following(db, task=created, user_id=user.id, following=True) is True
        assert task_service.set_task_following(db, task=created, user_id=user.id, following=True) is True
        assert db.query(SddTaskFollower).filter(
            SddTaskFollower.task_id == created.id,
            SddTaskFollower.user_id == user.id,
        ).count() == 1
        assert task_service.set_task_following(db, task=created, user_id=user.id, following=False) is False

        task_service.save_chat_message(
            db,
            task_id=followed.id,
            workspace_id=workspace.id,
            creator_id=other.id,
            role="assistant",
            content="A new task message",
        )
        notification = db.query(SddUserNotification).filter(
            SddUserNotification.recipient_user_id == user.id,
            SddUserNotification.type == "task_message",
        ).one()
        assert notification.payload_json["task_id"] == followed.id
    finally:
        db.close()
        engine.dispose()
