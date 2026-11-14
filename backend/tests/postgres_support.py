"""Opt-in PostgreSQL fixtures using temporary schemas on the configured server."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url


@contextmanager
def temporary_postgres_schema() -> Iterator[Engine]:
    value = os.environ.get("TRACEFORGE_TEST_POSTGRES_URL", "").strip()
    if not value:
        pytest.skip("TRACEFORGE_TEST_POSTGRES_URL not set")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise ValueError("TRACEFORGE_TEST_POSTGRES_URL must point to PostgreSQL")
    url = url.set(drivername="postgresql+psycopg")
    schema = f"tf_test_{uuid4().hex}"
    admin = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with admin.begin() as conn:
            conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
        try:
            engine = create_engine(
                url,
                isolation_level="READ COMMITTED",
                connect_args={
                    "connect_timeout": 5,
                    "options": f"-c search_path={schema} -c timezone=UTC -c statement_timeout=30000",
                },
            )
            try:
                yield engine
            finally:
                engine.dispose()
        finally:
            with admin.begin() as conn:
                conn.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
    finally:
        admin.dispose()
