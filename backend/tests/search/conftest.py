from unittest.mock import AsyncMock
import pytest
from app.config import settings
from app.domains.search import sqlite_index


@pytest.fixture(autouse=True)
def isolate_local_index(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'SEARCH_SQLITE_PATH', str(tmp_path / 'search.sqlite3'))
    # Runtime lifecycle tests must never start a backfill against the developer DB.
    monkeypatch.setattr(sqlite_index, 'bootstrap', AsyncMock())
