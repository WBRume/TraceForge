import pytest

from app.domains.search import sqlite_index
from app.domains.search.service import hydrate
from app.domains.search.sqlite_index import bootstrap as backfill_local
from app.domains.search.worker import current_document

from .test_search_contracts import _seed_task
from .test_search_contracts import db_session as db_session


def doc(key, text, version=1, workspace="w", **extra):
    return dict(
        entity_key=key,
        kind="task",
        workspace_id=workspace,
        task_id=key,
        title=text,
        content_text=text,
        source_version=version,
        deleted=False,
        created_at="2026-09-01T00:00:00",
        **extra,
    )


def test_bm25_chinese_scope_updates_and_tombstones():
    sqlite_index.write(
        [
            doc("task:1", "支付回调空指针异常"),
            doc("task:2", "支付回调空指针异常", workspace="other"),
            doc("task:3", "布局溢出"),
        ]
    )
    assert [x["_source"]["entity_key"] for x in sqlite_index.search("空指针异常", ["w"])] == ["task:1"]
    sqlite_index.write([doc("task:1", "连接池耗尽", 2)])
    assert not sqlite_index.search("空指针异常", ["w"])
    dead = doc("task:1", "", 3)
    dead["deleted"] = True
    sqlite_index.write([dead, doc("task:1", "连接池耗尽", 2)])
    assert not sqlite_index.search("连接池耗尽", ["w"])
    assert sqlite_index.search('" OR * -', ["w"]) == []


def test_physical_partitions_store_tokens_once_and_merge_rankings():
    message = doc("message:1", "重复连接池日志 " * 1000) | {"kind": "message", "message_id": "1"}
    case = doc("case:1", "连接池解决方案") | {"kind": "case"}
    sqlite_index.write([message, case, *[doc(f"task:{i}", "连接池故障") for i in range(205)]])
    for corpus, expected_kinds in (("history", {"task", "message"}), ("knowledge", {"case"})):
        assert sqlite_index.index_path(corpus).is_file()
        with sqlite_index.connection(corpus) as db:
            assert {r[0] for r in db.execute("SELECT DISTINCT kind FROM documents")} == expected_kinds
            assert "body" not in {r[1] for r in db.execute("PRAGMA table_info(documents)")}
            assert not db.execute("SELECT name FROM sqlite_master WHERE name='terms_content'").fetchone()
            db.execute("INSERT INTO terms(terms,rank) VALUES('integrity-check',1)")
    with sqlite_index.connection("history") as db:
        text = db.execute("SELECT content FROM documents WHERE entity_key='message:1'").fetchone()[0]
        assert len(text) < 100
    hits = sqlite_index.search("连接池", ["w"])
    assert "case:1" in [h["_id"] for h in hits[:2]]
    assert len(hits) == 200
    assert [h["_id"] for h in sqlite_index.search("连接池", ["w"], kind="case")] == ["case:1"]
    assert all(h["_score"] > 0 for h in hits)


def test_partition_updates_delete_old_tokens_and_readiness_requires_both_partitions():
    case = doc("case:1", "old_unique_term") | {"kind": "case"}
    sqlite_index.write(
        [case, case | {"source_version": 2, "title": "new_unique_term", "content_text": "new_unique_term"}]
    )
    assert not sqlite_index.search("old_unique_term", ["w"])
    assert sqlite_index.search("new_unique_term", ["w"])
    sqlite_index.write([case | {"source_version": 3, "deleted": True}, case])
    assert not sqlite_index.search("new_unique_term", ["w"])
    with sqlite_index.connection("knowledge") as db:
        db.execute("INSERT INTO terms(terms,rank) VALUES('integrity-check',1)")
    for kind in ("task", "message", "case"):
        sqlite_index.checkpoint(kind, "__done__")
    assert not sqlite_index.ready()
    sqlite_index.checkpoint("playbook", "__done__")
    assert sqlite_index.ready()
    sqlite_index.invalidate_checkpoints()
    assert not sqlite_index.ready()


def test_local_results_still_recheck_source_authorization_and_version(db_session):
    db = db_session
    task = _seed_task(db)
    from app.domains.auth.models.user import WorkspaceMember

    db.add(WorkspaceMember(workspace_id=task.workspace_id, user_id=task.creator_id, role="OWNER"))
    task.name = "连接池耗尽"
    db.commit()
    projection = current_document(db, f"task:{task.id}")
    db.commit()
    sqlite_index.write([projection])
    hits = sqlite_index.search("连接池", [task.workspace_id])
    candidates = [h["_source"] for h in hits]
    assert hydrate(db, task.creator_id, candidates, 0, 20, "连接池", [task.workspace_id])[0]
    task.name = "已经修改"
    db.commit()
    assert hydrate(db, task.creator_id, candidates, 0, 20, "连接池", [task.workspace_id])[0] == []


@pytest.mark.asyncio
async def test_existing_sources_are_backfilled_once_and_can_rebuild_without_es(db_session, monkeypatch):
    import asyncio

    from app.core import offload

    db = db_session
    task = _seed_task(db)
    task.name = "历史连接池异常"
    db.commit()
    calls = []

    async def transaction(fn):
        calls.append(1)
        result = fn(db)
        db.commit()
        return result

    monkeypatch.setattr(offload, "run_db_txn", transaction)
    await backfill_local(asyncio.Event())
    assert sqlite_index.ready()
    assert sqlite_index.search("连接池", [task.workspace_id])
    count = len(calls)
    await backfill_local(asyncio.Event())
    assert len(calls) == count
