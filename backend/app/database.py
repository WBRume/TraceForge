"""
TraceForge Platform - Database Engine & Session
"""

from sqlalchemy import create_engine
from sqlalchemy import event as _event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.orm import Session as _Session

from app.config import settings

# connect/read/write timeout 防止 offload 线程被无超时查询永久占用
# （connect_args 直接透传 PyMySQL：connect_timeout / read_timeout / write_timeout）
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=int(settings.DB_POOL_RECYCLE_SECONDS),
    connect_args={
        "connect_timeout": int(settings.DB_CONNECT_TIMEOUT),
        "read_timeout": int(settings.DB_READ_TIMEOUT),
        "write_timeout": int(settings.DB_WRITE_TIMEOUT),
    },
    echo=settings.SQL_ECHO,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """SQLAlchemy 声明基类"""


# Register search tables before metadata-based tests/migrations create the schema.

from app.domains.search import models as _search_models  # noqa: E402,F401


@_event.listens_for(_Session, "before_flush")
def _install_search_capture(session, flush_context, instances):
    from app.domains.search.capture import install_capture

    install_capture()
    from app.domains.notification.services.task_awareness import capture_flush

    capture_flush(session)
