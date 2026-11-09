"""Document write locks and original-file ownership across database transactions."""

from __future__ import annotations

from sqlalchemy import event, update
from sqlalchemy.orm import Session, SessionTransaction

from app.domains.asset.models.asset import SddAsset
from app.domains.asset.services.document import storage
from app.domains.task.models.task import SddTask

_FILES_KEY = "document_original_files"


class DocumentVersionConflict(ValueError):
    """The document changed after the caller selected its base version."""

    status_code = 409


def lock_asset(db: Session, asset: SddAsset) -> None:
    """Refresh the asset under a write lock held until the caller ends its transaction."""
    with db.no_autoflush:
        if db.get_bind().dialect.name == "sqlite":
            # SQLite ignores FOR UPDATE; acquire its writer lock before reading.
            db.execute(update(SddAsset).where(SddAsset.id == asset.id).values(id=SddAsset.id))
        locked = db.query(SddAsset).filter(SddAsset.id == asset.id).populate_existing().with_for_update().first()
    if locked is None:
        raise ValueError(f"Asset not found: {asset.id}")


def lock_task_for_document_write(db: Session, task: SddTask) -> None:
    """Lock the parent before assets, for first uploads and transactional task spec pointers."""
    with db.no_autoflush:
        if db.get_bind().dialect.name == "sqlite":
            db.execute(update(SddTask).where(SddTask.id == task.id).values(id=SddTask.id))
        db.query(SddTask.id).filter(SddTask.id == task.id).with_for_update().one()


def track_original_file(db: Session, path: str) -> None:
    """Keep a new original only if its owning outer transaction commits."""
    transaction = db.get_nested_transaction() or db.get_transaction()
    if transaction is None:
        raise RuntimeError("Document files require an active database transaction")
    db.info.setdefault(_FILES_KEY, {}).setdefault(transaction, set()).add(path)


@event.listens_for(Session, "after_commit")
def _files_committed(db: Session) -> None:
    transaction = db.get_nested_transaction() or db.get_transaction()
    files = db.info.get(_FILES_KEY, {})
    paths = files.pop(transaction, set())
    if transaction is not None and transaction.parent is not None:
        # Releasing a SAVEPOINT is not a durable commit.
        files.setdefault(transaction.parent, set()).update(paths)


@event.listens_for(Session, "after_rollback")
def _files_rolled_back(db: Session) -> None:
    transaction = db.get_nested_transaction() or db.get_transaction()
    for path in db.info.get(_FILES_KEY, {}).pop(transaction, set()):
        storage.remove_original_file(path)


@event.listens_for(Session, "after_transaction_end")
def _files_transaction_ended(db: Session, transaction: SessionTransaction) -> None:
    # Session.close() ends uncommitted transactions without after_rollback.
    files = db.info.get(_FILES_KEY, {})
    for path in files.pop(transaction, set()):
        storage.remove_original_file(path)
    if not files:
        db.info.pop(_FILES_KEY, None)
