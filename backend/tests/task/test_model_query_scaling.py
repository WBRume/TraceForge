from datetime import datetime

from sqlalchemy import event

from app.domains.ai.models.ai_job import AiJobChannel, SddAiJob
from app.domains.notification.models.notification import SddUserNotification
from app.domains.notification.services.notification_service import delete_all_notifications, list_notifications
from app.domains.task.models.pre_input import SddTaskPreInput, SddTaskPreInputMention
from app.domains.task.services.task_records.queries import list_tasks
from app.domains.workspace_asset.services.tasks import list_query
from app.domains.workspace_asset.services.tasks.presenters import task_summary
from tests.task.test_task_chat_history_ordering import _seed_task


def test_aggregate_coverage_preserves_human_confirmation_rules(db):
    from app.domains.auth.models.user import User, Workspace
    from app.domains.task.models.task import SddTask
    from app.domains.workspace_asset.models.workspace_asset import (
        EvidenceSourceType,
        EvidenceStatus,
        EvidenceType,
        SddEvidence,
    )
    from tests.workspace_asset.test_workspace_asset_boundary import _seed_stats_fixtures

    task = _seed_task(db)
    _seed_stats_fixtures(db, db.get(Workspace, task.workspace_id), db.get(User, task.creator_id))
    evidence = SddEvidence(
        id="human-proof",
        task_id="task-a",
        workspace_id="ws-1",
        evidence_type=EvidenceType.CODE,
        status=EvidenceStatus.CONFIRMED,
        source_type=EvidenceSourceType.HUMAN_CONFIRMATION,
        confirmed_by_id="user-1",
        confirmed_at=datetime(2026, 10, 13),
    )
    db.add(evidence)
    db.commit()
    db.expunge_all()
    result = list_query.list_tasks(db, "ws-1")
    by_id = {item.id: item for item in result.items}
    assert by_id["task-a"].coverage_status == "verified"
    assert by_id["task-b"].coverage_status == "waiting_human_confirmation"
    assert by_id["task-c"].coverage_status == "not_available"
    db.expunge_all()
    for item in result.items:
        assert task_summary(db, db.get(SddTask, item.id)).model_dump() == item.model_dump()
    db.get(SddEvidence, "human-proof").confirmed_at = None
    db.commit()
    assert {item.id: item for item in list_query.list_tasks(db, "ws-1").items}[
        "task-a"
    ].coverage_status == "waiting_human_confirmation"


def test_mentions_are_authoritative_and_both_lists_use_sql(db):
    task = _seed_task(db)
    pre_input = SddTaskPreInput(
        id="pre-input",
        task_id=task.id,
        workspace_id=task.workspace_id,
        creator_id=task.creator_id,
        main_text="review",
        mentioned_user_ids=["user-1", "historic-user", "user-1"],
    )
    db.add(pre_input)
    db.commit()
    db.expire_all()
    assert pre_input.mentioned_user_ids == ["user-1", "historic-user"]
    assert db.query(SddTaskPreInputMention).count() == 2
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        items, count = list_tasks(db, "ws-1", relation="mentioned_me", current_user_id="user-1")
        assets = list_query.list_tasks(db, "ws-1", relation="mentioned_me", current_user_id="user-1")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert count == assets.total == 1
    assert items[0].id == assets.items[0].id == "task-1"
    assert not any("mentioned_user_ids" in sql for sql in statements)
    assert any("EXISTS" in sql and "sdd_task_pre_input_mentions" in sql for sql in statements)
    pre_input.mentioned_user_ids = ["historic-user"]
    db.commit()
    assert list_tasks(db, "ws-1", relation="mentioned_me", current_user_id="user-1")[1] == 0
    db.delete(pre_input)
    db.commit()
    assert db.query(SddTaskPreInputMention).count() == 0


def test_asset_task_list_counts_jobs_without_loading_their_payloads(db):
    task = _seed_task(db)
    db.execute(
        SddAiJob.__table__.insert(),
        [
            {
                "id": f"job-{i}",
                "task_id": task.id,
                "workspace_id": task.workspace_id,
                "creator_id": task.creator_id,
                "channel": AiJobChannel.TASK_CHAT,
                "queue_key": "task:test",
                "prompt_text": "large prompt " * 1000,
            }
            for i in range(120)
        ],
    )
    db.commit()
    db.expunge_all()
    result = list_query.list_tasks(db, "ws-1")
    assert result.items[0].ai_run_count == 120
    assert not any(isinstance(row, SddAiJob) for row in db.identity_map.values())
    db.expunge_all()
    from app.domains.task.models.task import SddTask

    detail = task_summary(db, db.get(SddTask, "task-1"))
    assert detail.model_dump() == result.items[0].model_dump()


def test_notifications_clear_is_bounded_and_pagination_is_stable(db):
    _seed_task(db)
    created = datetime(2026, 10, 13)
    db.execute(
        SddUserNotification.__table__.insert(),
        [
            {
                "id": f"notice-{i:04}",
                "recipient_user_id": "user-1",
                "title": "Notice",
                "type": "test",
                "created_at": created,
                "read_at": created if i % 2 else None,
                "body": "body" * 1000,
            }
            for i in range(200)
        ],
    )
    db.commit()
    first, total = list_notifications(db, "user-1", page_size=10)
    second, _ = list_notifications(db, "user-1", page=2, page_size=10)
    assert total == 200
    assert first[0]["id"] == "notice-0199"
    assert not {item["id"] for item in first} & {item["id"] for item in second}
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert delete_all_notifications(db, "user-1") == (200, 100)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 2
    assert all(sql.startswith("DELETE ") for sql in statements)
    assert delete_all_notifications(db, "user-1") == (0, 0)
