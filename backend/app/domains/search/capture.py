"""Transactional source capture, including explicit bulk/range invalidation."""
from datetime import datetime
import threading
from sqlalchemy import event, select, update, func
from app.domains.search.models import SearchDocumentState, SearchOutbox
from app.domains.search.projection import build_search_projection

_install_lock = threading.RLock()
_installed = False


def mark_connection(conn, source, kind, deleted=False):
    table = SearchDocumentState.__table__
    key = f"{kind}:{source.id}"
    projection = None if deleted else build_search_projection(source, kind)
    row = conn.execute(select(table).where(table.c.entity_key == key).with_for_update()).mappings().first()
    if projection is None and row is None and not deleted:
        return
    hashed = projection["projection_hash"] if projection else None
    dead = projection is None
    if row and row["projection_hash"] == hashed and row["deleted"] == dead:
        return
    version = row["source_version"] + 1 if row else 1
    fields = dict(kind=kind, workspace_id=source.workspace_id,
                  task_id=source.task_id if kind == "message" else (source.source_task_id or source.id) if kind == "case" else source.id, source_id=source.id,
                  source_version=version, projection_hash=hashed, deleted=dead, updated_at=datetime.utcnow())
    if row:
        conn.execute(update(table).where(table.c.entity_key == key).values(**fields))
    else:
        conn.execute(table.insert().values(entity_key=key, **fields))
    conn.execute(SearchOutbox.__table__.insert().values(entity_key=key, source_version=version,
                 workspace_id=fields["workspace_id"], task_id=fields["task_id"], event_kind="entity_changed"))


def enqueue_scope(db, *, task_id=None, workspace_id=None):
    db.add(SearchOutbox(event_kind="task_rescan" if task_id else "workspace_rescan", task_id=task_id, workspace_id=workspace_id))


def allocate_chat_seq(db, task_id):
    from app.domains.task.models.task import SddTask
    from app.domains.task.models.chat import ChatMessage
    task = db.query(SddTask).filter(SddTask.id == task_id).with_for_update().one()
    if task.next_chat_seq is None:
        maximum = db.query(func.max(func.coalesce(ChatMessage.sort_seq, ChatMessage.metadata_json["order_index"].as_integer(), 0))).filter(ChatMessage.task_id == task_id).scalar()
        task.next_chat_seq = int(maximum) + 1 if maximum is not None else 0
    seq = task.next_chat_seq
    task.next_chat_seq += 1
    return seq


def install_capture():
    global _installed
    if _installed:
        return
    with _install_lock:
        if _installed:
            return
        _register_capture()
        _installed = True


def _register_capture():
    from app.domains.task.models.task import SddTask
    from app.domains.task.models.chat import ChatMessage
    from app.domains.auth.models.user import Workspace
    from app.domains.case_center.models.case import SddCase
    from app.domains.diagnosis_playbook.models import PlaybookSpec
    for model, kind in ((SddTask, "task"), (ChatMessage, "message"), (SddCase, "case"), (PlaybookSpec, "playbook")):
        def changed(mapper, connection, target, kind=kind):
            mark_connection(connection, target, kind)
        def deleted(mapper, connection, target, kind=kind):
            mark_connection(connection, target, kind, True)
            if kind == "task":
                connection.execute(SearchOutbox.__table__.insert().values(event_kind="task_rescan", task_id=target.id, workspace_id=target.workspace_id))
        event.listen(model, "after_insert", changed)
        event.listen(model, "after_update", changed)
        event.listen(model, "after_delete", deleted)
    def workspace_deleted(mapper, connection, target):
        connection.execute(SearchOutbox.__table__.insert().values(event_kind="workspace_rescan", workspace_id=target.id))
    event.listen(Workspace, "after_delete", workspace_deleted)
