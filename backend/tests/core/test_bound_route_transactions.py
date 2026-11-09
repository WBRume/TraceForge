"""Route/service transaction boundaries always use independent worker sessions."""

import threading

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session

from app.domains.asset.routers.assets import transport
from app.domains.task.routers.task import deps
from app.domains.task.services import task_session_control_service as lifecycle


def run_session_transaction(request_db, bind, body):
    return lifecycle._bind_txn_runner(request_db, bind)(body)


BOUNDARIES = [
    pytest.param(deps.get_db_bind, deps.run_route_db_txn, id="task-route"),
    pytest.param(transport._get_db_bind, transport._run_asset_route_db_txn, id="review-route"),
    pytest.param(lifecycle._session_bind, run_session_transaction, id="task-session"),
]


@pytest.fixture
def transaction_store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'transactions.db'}", connect_args={"check_same_thread": False})
    records = Table("transaction_records", MetaData(), Column("id", Integer, primary_key=True))
    records.metadata.create_all(engine)
    try:
        yield engine, records
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("get_bind,run_transaction", BOUNDARIES)
@pytest.mark.parametrize("abort", [False, True], ids=["commit", "rollback"])
async def test_closed_request_session_runs_an_independent_worker_transaction(
    transaction_store, get_bind, run_transaction, abort
):
    engine, records = transaction_store
    event_loop_thread = threading.get_ident()
    with Session(bind=engine) as request_db:
        request_db.close()
        bind = get_bind(request_db)

        def write(db):
            assert db is not request_db
            assert threading.get_ident() != event_loop_thread
            db.execute(records.insert().values(id=1))
            if abort:
                raise RuntimeError("abort transaction")
            return "saved"

        if abort:
            with pytest.raises(RuntimeError, match="abort transaction"):
                await run_transaction(request_db, bind, write)
        else:
            assert await run_transaction(request_db, bind, write) == "saved"
    with engine.connect() as conn:
        assert conn.execute(select(records.c.id)).scalars().all() == ([] if abort else [1])


@pytest.mark.parametrize("get_bind,_run_transaction", BOUNDARIES)
def test_unbound_session_fails_before_transaction_execution(get_bind, _run_transaction):
    with Session() as db:
        with pytest.raises(UnboundExecutionError):
            get_bind(db)
