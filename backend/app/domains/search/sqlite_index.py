"""Local, disposable FTS5 index; relational source remains authoritative."""

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.feature_settings import feature_settings as settings

from .projection import es_version
from .rrf import fuse_rankings
from .storage import CORPORA, SCHEMA_VERSION, corpora_for, corpus_for


def tokens(text):
    parts = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", str(text).lower())
    return [
        token
        for part in parts
        for token in (
            [part[i : i + 2] for i in range(len(part) - 1)] if re.fullmatch(r"[\u3400-\u9fff]{2,}", part) else [part]
        )
    ]


def index_path(corpus):
    if corpus not in CORPORA:
        raise ValueError("SEARCH_INVALID_CORPUS")
    path = Path(settings.SEARCH_SQLITE_PATH).resolve()
    return path.with_name(f"{path.stem}-v{SCHEMA_VERSION}-{corpus}{path.suffix}")


@contextmanager
def connection(corpus):
    path = index_path(corpus)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, entity_key TEXT UNIQUE, version INTEGER, "
            "workspace_id TEXT, kind TEXT, task_id TEXT, message_id TEXT, role TEXT, created_at TEXT, deleted INTEGER, "
            "source_version INTEGER, projection_hash TEXT, title TEXT, content TEXT, symbols TEXT)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS documents_scope ON documents(workspace_id, kind)")
        db.execute("CREATE VIEW IF NOT EXISTS indexed_documents AS SELECT * FROM documents WHERE deleted=0")
        # One token copy supports deletes and BM25; FTS stores no second text copy or word offsets.
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS terms USING fts5(title, content, symbols, "
            "content='indexed_documents', content_rowid='id', detail='column', tokenize='unicode61 tokenchars _')"
        )
        db.execute("CREATE TABLE IF NOT EXISTS checkpoints (name TEXT PRIMARY KEY, cursor TEXT)")
        yield db
        db.commit()
    finally:
        db.close()


def write(documents):
    for corpus in CORPORA:
        batch = [doc for doc in documents if corpus_for(doc["kind"]) == corpus]
        if batch:
            _write(corpus, batch)


def _write(corpus, documents):
    with connection(corpus) as db:
        db.execute("BEGIN IMMEDIATE")
        for doc in documents:
            version = es_version(doc["source_version"], int(bool(doc.get("deleted"))))
            row = db.execute(
                "SELECT id, version, deleted, title, content, symbols FROM documents WHERE entity_key=?",
                (doc["entity_key"],),
            ).fetchone()
            if row and row[1] >= version:
                continue
            if row:
                if not row[2]:
                    db.execute(
                        "INSERT INTO terms(terms,rowid,title,content,symbols) VALUES('delete',?,?,?,?)",
                        (row[0], *row[3:]),
                    )
                db.execute("DELETE FROM documents WHERE id=?", (row[0],))
            fields = []
            for value in (doc.get("title", ""), doc.get("content_text", ""), " ".join(doc.get("symbols", []))):
                terms = [] if doc.get("deleted") else tokens(value)
                # Repeated log lines must not create repeated stored token strings.
                fields.append(" ".join(dict.fromkeys(terms) if corpus == "history" else terms))
            cursor = db.execute(
                "INSERT INTO documents(entity_key,version,workspace_id,kind,task_id,message_id,role,created_at,"
                "deleted,source_version,projection_hash,title,content,symbols) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc["entity_key"],
                    version,
                    doc["workspace_id"],
                    doc["kind"],
                    doc.get("task_id"),
                    doc.get("message_id"),
                    doc.get("role"),
                    doc.get("created_at"),
                    bool(doc.get("deleted")),
                    doc["source_version"],
                    doc.get("projection_hash"),
                    *fields,
                ),
            )
            if not doc.get("deleted"):
                db.execute(
                    "INSERT INTO terms(rowid,title,content,symbols) VALUES(?,?,?,?)",
                    (cursor.lastrowid, *fields),
                )


def search(query, scope, *, kind="all", task_id=None, role=None, date_from=None, date_to=None, limit=200):
    rankings = [
        _search(
            corpus,
            query,
            scope,
            kind=kind,
            task_id=task_id,
            role=role,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        for corpus in corpora_for(kind)
    ]
    # BM25 scores from independent corpora are not comparable.
    return fuse_rankings(rankings[0], rankings[1], window=limit) if len(rankings) == 2 else rankings[0]


def _search(corpus, query, scope, *, kind, task_id, role, date_from, date_to, limit):
    terms = list(dict.fromkeys(tokens(query)))[:100]
    if not terms or not scope:
        return []
    where = ["terms MATCH ?", "d.deleted=0", "d.workspace_id IN (" + ",".join("?" for _ in scope) + ")"]
    args = [" OR ".join('"' + word + '"' for word in terms), *scope]
    for column, value in [("kind", kind if kind != "all" else None), ("task_id", task_id)]:
        if value:
            where.append(f"d.{column}=?")
            args.append(value)
    if role:
        where.append("(d.kind='task' OR d.role=?)")
        args.append(role)
    for op, stamp in [(">=", date_from), ("<", date_to)]:
        if stamp:
            where.append(f"julianday(d.created_at) {op} julianday(?)")
            args.append(str(stamp))
    fields = ("entity_key", "kind", "source_version", "projection_hash", "workspace_id", "task_id", "message_id")
    with connection(corpus) as db:
        rows = db.execute(
            "SELECT "
            + ",".join(f"d.{field}" for field in fields)
            + ",bm25(terms,4.0,1.0,2.0) FROM terms JOIN documents d ON d.id=terms.rowid WHERE "
            + " AND ".join(where)
            + " ORDER BY bm25(terms,4.0,1.0,2.0),d.entity_key LIMIT ?",
            [*args, limit],
        ).fetchall()
    return [{"_id": row[0], "_source": dict(zip(fields, row[:-1], strict=True)), "_score": -row[-1]} for row in rows]


def ready():
    return all(checkpoint(kind) == "__done__" for kinds in CORPORA.values() for kind in kinds)


def invalidate_checkpoints():
    """A later ES-to-auto switch must backfill writes skipped by the local index."""
    for corpus in CORPORA:
        if index_path(corpus).exists():
            with connection(corpus) as db:
                db.execute("DELETE FROM checkpoints")


def local_only():
    return settings.SEARCH_BACKEND == "sqlite" or (
        settings.SEARCH_BACKEND == "auto" and not settings.SEARCH_ES_URL.strip()
    )


def checkpoint(kind, cursor=None):
    with connection(corpus_for(kind)) as db:
        if cursor is not None:
            db.execute("INSERT OR REPLACE INTO checkpoints(name,cursor) VALUES(?,?)", (kind, cursor))
        row = db.execute("SELECT cursor FROM checkpoints WHERE name=?", (kind,)).fetchone()
        return row[0] if row else ""


async def bootstrap(stop_event):
    """Keyset backfill per source, resumable even when this index file is recreated."""
    import asyncio

    from app.core.offload import run_db_txn
    from app.domains.case_center.models.case import SddCase
    from app.domains.diagnosis_playbook.models import PlaybookSpec
    from app.domains.task.models.chat import ChatMessage
    from app.domains.task.models.task import SddTask

    from .worker import current_document

    for kind, model in [("task", SddTask), ("message", ChatMessage), ("case", SddCase), ("playbook", PlaybookSpec)]:
        cursor = await asyncio.to_thread(checkpoint, kind)
        if cursor == "__done__":
            continue
        while not stop_event.is_set():

            def batch(db, *, cursor=cursor, kind=kind, model=model):
                ids = [r[0] for r in db.query(model.id).filter(model.id > cursor).order_by(model.id).limit(100)]
                return ids, [doc for identity in ids if (doc := current_document(db, f"{kind}:{identity}")) is not None]

            ids, documents = await run_db_txn(batch)
            await asyncio.to_thread(write, documents)
            cursor = ids[-1] if ids else "__done__"
            await asyncio.to_thread(checkpoint, kind, cursor)
            if not ids:
                break
