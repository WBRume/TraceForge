from contextlib import contextmanager
from threading import BoundedSemaphore
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError, TimeoutError
from sqlalchemy.orm import Session

_read_slots = BoundedSemaphore(4)
_lookup_slots = BoundedSemaphore(2)


def busy() -> HTTPException:
    return HTTPException(503, "CANVAS_QUERY_BUSY", headers={"Retry-After": "3"})


def postgres_limits(db: Session):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT set_config('statement_timeout','650ms',true), set_config('lock_timeout','120ms',true)"))


@contextmanager
def budgeted_read(db: Session, *, lookup: bool = False):
    slots = _lookup_slots if lookup else _read_slots
    if not slots.acquire(blocking=False):
        raise busy()
    deadline = monotonic() + 1.85
    connection = None

    def require_time(*_args):
        if monotonic() >= deadline:
            raise busy()

    try:
        postgres_limits(db)
        connection = db.connection()
        event.listen(connection, "before_cursor_execute", require_time)
        yield
        require_time()
    except OperationalError as error:
        state = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
        if state not in {"57014", "55P03"}:
            raise
        raise busy() from error
    except TimeoutError as error:
        raise busy() from error
    finally:
        if connection is not None:
            event.remove(connection, "before_cursor_execute", require_time)
        slots.release()
