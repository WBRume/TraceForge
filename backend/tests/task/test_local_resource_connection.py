from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domains.local_resource import service
from app.domains.local_resource.client import ResourceError
from app.domains.local_resource.schemas import ConnectionInput


@pytest.mark.parametrize("existing", [False, True])
def test_connection_check_uses_draft_without_saving_or_inspecting_repositories(monkeypatch, existing):
    db = Mock()
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    monkeypatch.setattr(service, "require_member", lambda *args: None)
    owned = Mock(return_value=SimpleNamespace(encrypted_credentials="saved"))
    monkeypatch.setattr(service, "owned", owned)
    monkeypatch.setattr(service, "decrypt_credentials", lambda _: {"host_token": "saved-token"})
    encrypt = Mock(side_effect=lambda value: value)
    monkeypatch.setattr(service, "encrypt_credentials", encrypt)
    monkeypatch.setattr(service, "validate_url", lambda value: value)
    client = Mock()
    client.identity.return_value = {"host_id": "host"}
    monkeypatch.setattr(service, "ResourceClient", Mock(return_value=client))
    probe = AsyncMock()
    monkeypatch.setattr(service, "probe_provider", probe)
    data = ConnectionInput(
        resource_id="resource" if existing else None,
        backend="opencode", service_url="http://10.0.0.2:4096",
        resource_service_url="http://10.0.0.2:4098",
        host_token=None if existing else "draft-token",
    )
    assert service.check_connection(db, "ws", "user", data) == {"ready": True, "host_id": "host"}
    assert encrypt.call_args.args[0]["host_token"] == ("saved-token" if existing else "draft-token")
    if existing:
        owned.assert_called_once_with(db, "resource", "user", "ws")
    probe.assert_awaited_once()
    assert probe.call_args.args[0]["service_url"] == data.service_url
    client.request.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_connection_check_propagates_agent_failure(monkeypatch):
    client = Mock()
    monkeypatch.setattr(service, "ResourceClient", Mock(return_value=client))
    monkeypatch.setattr(service, "probe_provider", AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(ResourceError, match="Agent 协议或认证检测失败"):
        service.verify_connection({"service_url": "http://10.0.0.2:4096", "resource_service_url": "http://10.0.0.2:4098"})
