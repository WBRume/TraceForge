from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domains.task.routers import public_session_shares
from app.domains.task.routers.task import session_shares
from app.domains.websocket.ws.public_share_manager import PublicShareConnectionManager, public_share_ws_manager


def test_revocation_evicts_only_the_deleted_share_and_is_idempotent():
    manager = PublicShareConnectionManager()
    removed, retained = Mock(), Mock()
    manager.registry = SimpleNamespace(
        rooms={"share:deleted": {"visitor": removed}, "share:retained": {"visitor": retained}}
    )
    manager.revoke("deleted")
    removed.evict.assert_called_once_with("share_revoked")
    retained.evict.assert_not_called()
    manager.revoke("missing")


@pytest.mark.asyncio
async def test_delete_route_revokes_after_successful_database_transaction(monkeypatch):
    from contextlib import asynccontextmanager

    share = SimpleNamespace(creator_id="u")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = share
    monkeypatch.setattr(session_shares, "verify_workspace_access", Mock())
    monkeypatch.setattr(session_shares, "get_task_or_404", Mock())

    @asynccontextmanager
    async def unlocked(*args):
        yield

    monkeypatch.setattr(session_shares, "lock_task", unlocked)
    transaction = AsyncMock(return_value=share)
    monkeypatch.setattr(session_shares, "run_route_db_txn", transaction)
    revoke = Mock(side_effect=lambda _: transaction.assert_awaited_once())
    monkeypatch.setattr(public_share_ws_manager, "revoke", revoke)
    result = await session_shares.revoke_session_share("w", "t", "s", current_user=SimpleNamespace(id="u"), db=db)
    assert result == {"msg": "Share deleted"}
    revoke.assert_called_once_with("s")


@pytest.mark.asyncio
async def test_deleted_during_websocket_registration_is_evicted(monkeypatch):
    from app.core import offload

    resolver = AsyncMock(side_effect=[SimpleNamespace(id="s"), None])
    monkeypatch.setattr(offload, "run_db", resolver)
    connection = Mock()
    monkeypatch.setattr(public_share_ws_manager, "connect", AsyncMock(return_value=connection))
    socket = Mock(query_params={"access": "test-only-token"})
    await public_session_shares.public_share_websocket_endpoint(socket, "s")
    connection.evict.assert_called_once_with("share_revoked")
    assert resolver.await_count == 2
