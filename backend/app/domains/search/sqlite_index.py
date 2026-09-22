"""Local, disposable FTS5 index; relational source remains authoritative."""
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app.config import settings
from .projection import es_version


def tokens(text):
    parts = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", str(text).lower())
    return [token for part in parts for token in (
        [part[i:i + 2] for i in range(len(part) - 1)] if re.fullmatch(r"[\u3400-\u9fff]{2,}", part) else [part])]


@contextmanager
def connection():
    path = Path(settings.SEARCH_SQLITE_PATH).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, entity_key TEXT UNIQUE, version INTEGER, workspace_id TEXT, kind TEXT, task_id TEXT, role TEXT, created_at TEXT, deleted INTEGER, body TEXT)')
        db.execute('CREATE INDEX IF NOT EXISTS documents_scope ON documents(workspace_id, kind)')
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS terms USING fts5(title, content, symbols)')
        db.execute('CREATE TABLE IF NOT EXISTS checkpoints (name TEXT PRIMARY KEY, cursor TEXT)')
        yield db
        db.commit()
    finally:
        db.close()


def write(documents):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for doc in documents:
            version = es_version(doc['source_version'], int(bool(doc.get('deleted'))))
            row = db.execute('SELECT id, version FROM documents WHERE entity_key=?', (doc['entity_key'],)).fetchone()
            if row and row[1] >= version:
                continue
            if row:
                db.execute('DELETE FROM terms WHERE rowid=?', (row[0],))
                db.execute('DELETE FROM documents WHERE id=?', (row[0],))
            clean = {k: v for k, v in doc.items() if k != 'semantic_passages'}
            if doc.get('deleted'):
                clean = {k: v for k, v in clean.items() if k not in {'title', 'content_text', 'symbols'}}
            cursor = db.execute('INSERT INTO documents(entity_key,version,workspace_id,kind,task_id,role,created_at,deleted,body) VALUES(?,?,?,?,?,?,?,?,?)',
                (doc['entity_key'], version, doc['workspace_id'], doc['kind'], doc.get('task_id'), doc.get('role'), doc.get('created_at'), bool(doc.get('deleted')), json.dumps(clean, ensure_ascii=False)))
            if not doc.get('deleted'):
                db.execute('INSERT INTO terms(rowid,title,content,symbols) VALUES(?,?,?,?)', (cursor.lastrowid,
                    ' '.join(tokens(doc.get('title', ''))), ' '.join(tokens(doc.get('content_text', ''))), ' '.join(tokens(' '.join(doc.get('symbols', []))))))


def search(query, scope, *, kind='all', task_id=None, role=None, date_from=None, date_to=None, limit=200):
    terms = list(dict.fromkeys(tokens(query)))[:100]
    if not terms or not scope:
        return []
    where = ['terms MATCH ?', 'd.deleted=0', 'd.workspace_id IN (' + ','.join('?' for _ in scope) + ')']
    args = [' OR '.join('"' + word + '"' for word in terms), *scope]
    for column, value in [('kind', kind if kind != 'all' else None), ('task_id', task_id)]:
        if value:
            where.append(f'd.{column}=?'); args.append(value)
    if role:
        where.append("(d.kind='task' OR d.role=?)"); args.append(role)
    for op, stamp in [('>=', date_from), ('<', date_to)]:
        if stamp:
            where.append(f'julianday(d.created_at) {op} julianday(?)'); args.append(str(stamp))
    with connection() as db:
        rows = db.execute('SELECT d.body, bm25(terms,4.0,1.0,2.0) FROM terms JOIN documents d ON d.id=terms.rowid WHERE ' + ' AND '.join(where) + ' ORDER BY bm25(terms,4.0,1.0,2.0),d.entity_key LIMIT ?', [*args, limit]).fetchall()
    fields = {'entity_key', 'kind', 'source_version', 'projection_hash', 'workspace_id', 'task_id', 'message_id'}
    return [{'_source': {k: v for k, v in json.loads(body).items() if k in fields}, '_score': -score} for body, score in rows]


def ready():
    with connection() as db:
        return db.execute("SELECT count(*) FROM checkpoints WHERE cursor='__done__'").fetchone()[0] == 4


def local_only():
    return settings.SEARCH_BACKEND == 'sqlite' or (settings.SEARCH_BACKEND == 'auto' and not settings.SEARCH_ES_URL.strip())


def checkpoint(kind, cursor=None):
    with connection() as db:
        if cursor is not None:
            db.execute('INSERT OR REPLACE INTO checkpoints(name,cursor) VALUES(?,?)', (kind, cursor))
        row = db.execute('SELECT cursor FROM checkpoints WHERE name=?', (kind,)).fetchone()
        return row[0] if row else ''


async def bootstrap(stop_event):
    """Keyset backfill per source, resumable even when this index file is recreated."""
    import asyncio
    from app.core.offload import run_db_txn
    from .worker import current_document
    from app.domains.task.models.task import SddTask
    from app.domains.task.models.chat import ChatMessage
    from app.domains.case_center.models.case import SddCase
    from app.domains.diagnosis_playbook.models import PlaybookSpec
    for kind, model in [('task', SddTask), ('message', ChatMessage), ('case', SddCase), ('playbook', PlaybookSpec)]:
        cursor = await asyncio.to_thread(checkpoint, kind)
        if cursor == '__done__':
            continue
        while not stop_event.is_set():
            def batch(db):
                ids = [r[0] for r in db.query(model.id).filter(model.id > cursor).order_by(model.id).limit(100)]
                return ids, [doc for identity in ids if (doc := current_document(db, f'{kind}:{identity}')) is not None]
            ids, documents = await run_db_txn(batch)
            await asyncio.to_thread(write, documents)
            cursor = ids[-1] if ids else '__done__'
            await asyncio.to_thread(checkpoint, kind, cursor)
            if not ids:
                break
