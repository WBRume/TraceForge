import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.core.feature_settings import feature_settings
from app.dependencies import get_current_user
from app.domains.ai.routers import speech
from app.domains.auth.providers.github import GitHubProvider
from app.domains.system_config.models.feature_config import FeatureConfig
from app.domains.system_config.routers import features
from app.domains.system_config.services import capability_probe as probes
from app.domains.system_config.services import feature_config_service as configs
from app.domains.system_config.services import feature_runtime, search_configuration
from app.domains.system_config.services.system_config_service import SystemConfigError


@pytest.fixture(autouse=True)
def clean_snapshot(monkeypatch):
    feature_settings.replace({})
    monkeypatch.setattr(settings, "FEATURE_CONFIG_MASTER_KEY", SecretStr(""))
    monkeypatch.setattr(settings, "SPEECH_MODE", None)
    yield
    feature_settings.replace({})


def save(db, feature, values, revision=0, reset=False):
    result = configs.save(db, feature, values, revision, "admin", reset)
    db.commit()
    return result


def publish(db):
    feature_settings.replace(configs.environment_snapshot(configs.snapshot(db)))


def test_environment_fallback_and_encrypted_db_precedence(db, monkeypatch):
    monkeypatch.setattr(settings, "SPEECH_API_ENABLED", True)
    monkeypatch.setattr(settings, "SPEECH_API_KEY", SecretStr("env-private-key"))
    assert configs.read(db, "speech")[0]["api_key"] == "env-private-key"
    public = save(db, "speech", {"api_key": "db-private-key", "region": "singapore"})
    encrypted = db.get(FeatureConfig, "speech").encrypted_values
    assert "db-private-key" not in encrypted
    assert "env-private-key" not in json.dumps(public)
    assert "db-private-key" not in json.dumps(public)
    assert next(field for field in public["fields"] if field["key"] == "api_key")["value"] == "db-p********-key"
    publish(db)
    assert feature_settings.SPEECH_API_KEY.get_secret_value() == "db-private-key"
    assert feature_settings.SPEECH_API_REGION == "singapore"
    assert settings.SPEECH_API_KEY.get_secret_value() == "env-private-key"
    assert configs.read(db, "speech")[0]["mode"] == "api"


@pytest.mark.parametrize(
    "feature,key,value,expected",
    [
        ("speech", "api_key", "", ""),
        ("speech", "api_key", "tiny", "********"),
        ("speech", "api_key", "123456789012", "********"),
        ("speech", "api_key", "1234567890123", "1234********0123"),
        ("search", "embedding_api_key", "sk-0123456789abcd", "sk-0********abcd"),
        ("oauth", "client_secret", "abcd-secret-hidden-wxyz", "********"),
        ("search", "es_password", "abcd-password-hidden-wxyz", "********"),
    ],
)
def test_secret_previews_never_reveal_complete_credentials(db, feature, key, value, expected):
    result = save(db, feature, {key: value})
    field = next(field for field in result["fields"] if field["key"] == key)
    assert field["value"] == expected
    assert field["has_value"] == bool(value)
    assert configs.read(db, feature)[0][key] == value
    if value:
        assert value not in json.dumps(result)


@pytest.mark.parametrize(
    "feature,key,env",
    [("speech", "api_key", "SPEECH_API_KEY"), ("search", "embedding_api_key", "SEARCH_EMBEDDING_API_KEY")],
)
def test_api_key_environment_preview_and_database_replacement(db, monkeypatch, feature, key, env):
    value = "env-credential-hidden-abcd"
    monkeypatch.setattr(settings, env, SecretStr(value) if feature == "speech" else value)
    field = next(field for field in configs.public(db, feature)["fields"] if field["key"] == key)
    assert field["value"] == "env-********abcd" and field["source"] == "environment"
    result = save(db, feature, {key: "new-credential-hidden-wxyz"})
    field = next(field for field in result["fields"] if field["key"] == key)
    assert field["value"] == "new-********wxyz" and field["source"] == "database"
    result = save(db, feature, {key: ""}, 1)
    field = next(field for field in result["fields"] if field["key"] == key)
    assert field["value"] == "" and not field["has_value"]


def test_preserve_clear_inherit_and_full_reset_are_distinct(db, monkeypatch):
    monkeypatch.setattr(settings, "SPEECH_API_KEY", SecretStr("env-key"))
    save(db, "speech", {"api_key": "stored-key", "mode": "api"})
    save(db, "speech", {"region": "singapore"}, 1)
    assert configs.read(db, "speech")[0]["api_key"] == "stored-key"
    save(db, "speech", {"api_key": ""}, 2)
    assert configs.read(db, "speech")[0]["api_key"] == ""
    save(db, "speech", {"api_key": None}, 3)
    assert configs.read(db, "speech")[0]["api_key"] == "env-key"
    reset = save(db, "speech", {}, 4, True)
    assert reset["revision"] == 5 and not reset["configured"]
    assert configs.read(db, "speech")[0]["region"] == settings.SPEECH_API_REGION


def test_concurrent_admin_revision_conflicts_and_reset_does_not_reuse_revision(db):
    save(db, "speech", {"mode": "api"})
    with pytest.raises(SystemConfigError, match="其他管理员") as exc:
        save(db, "speech", {"mode": "off"})
    assert exc.value.status_code == 409
    save(db, "speech", {}, 1, True)
    with pytest.raises(SystemConfigError) as exc:
        save(db, "speech", {"mode": "api"}, 1)
    assert exc.value.status_code == 409


@pytest.mark.parametrize(
    "feature,values",
    [
        ("speech", {"api_key": "********"}),
        ("speech", {"api_key": "sk-0********abcd"}),
        ("search", {"embedding_api_key": "sk-0********abcd"}),
        ("speech", {"token_ttl": True}),
        ("speech", {"region": "secret-invalid-region"}),
        ("search", {"es_url": "http://user:secret@host:9200"}),
        ("search", {"es_url": "http://["}),
        ("search", {"embedding_endpoint": "http://host/embeddings"}),
        ("agent", {"backend": "unsupported-private-value"}),
        ("speech", {"JWT_SECRET_KEY": "private-value"}),
    ],
)
def test_invalid_or_infrastructure_fields_are_rejected_without_value_echo(db, feature, values):
    with pytest.raises(SystemConfigError) as exc:
        save(db, feature, values)
    assert exc.value.status_code == 422
    assert all(str(value) not in str(exc.value) for value in values.values())
    assert db.query(FeatureConfig).count() == 0


def test_wrong_key_fails_closed_and_admin_can_restore_environment(db, monkeypatch):
    from cryptography.fernet import Fernet

    save(db, "speech", {"mode": "api", "api_key": "private-key"})
    monkeypatch.setattr(settings, "FEATURE_CONFIG_MASTER_KEY", SecretStr(Fernet.generate_key().decode()))
    overrides, errors = feature_runtime.load_runtime(db)
    assert overrides["speech"]["mode"] == "off"
    assert "speech" in errors
    public = configs.public(db, "speech")
    assert public["fields"] == [] and public["revision"] == 1
    assert "private-key" not in str(public)
    save(db, "speech", {}, 1, True)
    assert configs.read(db, "speech")[1] == {}


@pytest.fixture
def feature_api(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SEARCH_SQLITE_PATH", str(tmp_path / "search.sqlite3"))

    async def transaction(fn):
        try:
            response = fn(db)
            db.commit()
            return response
        except Exception:
            db.rollback()
            raise

    for module in (features, feature_runtime, search_configuration, probes):
        monkeypatch.setattr(module, "run_db_txn", transaction)
    app = FastAPI()
    app.include_router(features.router, prefix="/api")
    app.include_router(speech.router, prefix="/api")
    user = SimpleNamespace(id="admin", is_admin=True)
    app.dependency_overrides[get_current_user] = lambda: user
    requests = []
    original = httpx.AsyncClient

    def upstream(request):
        requests.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.5]}]})
        return httpx.Response(200, json={"token": "st-probe", "expires_at": int(time.time()) + 120})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(upstream), **kwargs)
    )
    redis = SimpleNamespace(eval=AsyncMock(return_value=1))
    monkeypatch.setattr(speech, "get_redis_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(probes, "get_redis_client", AsyncMock(return_value=redis))
    with TestClient(app) as client:
        yield client, app, user, requests


def test_saved_credentials_apply_to_running_speech_without_restart(feature_api):
    client, app, _, requests = feature_api
    original_client = app.state.speech_http_client
    response = client.put(
        "/api/system-configs/features/speech",
        json={
            "revision": 0,
            "values": {"mode": "api", "api_key": "new-secret", "region": "singapore"},
        },
    )
    assert response.status_code == 200 and response.json()["applied"]
    assert "new-secret" not in response.text
    response = client.post("/api/speech/sessions")
    assert response.status_code == 201
    assert requests[-1].headers["Authorization"] == "Bearer new-secret"
    assert requests[-1].url.host == "dashscope-intl.aliyuncs.com"
    assert app.state.speech_http_client is original_client
    capability = client.get("/api/speech/capabilities")
    assert capability.json()["mode"] == "api" and "new-secret" not in capability.text
    client.put("/api/system-configs/features/speech", json={"revision": 1, "values": {"mode": "off"}})
    assert client.post("/api/speech/sessions").status_code == 503


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/system-configs/features"),
        ("get", "/api/system-configs/features/speech"),
        ("get", "/api/system-configs/capabilities"),
        ("put", "/api/system-configs/features/speech"),
        ("post", "/api/system-configs/features/speech/test"),
    ],
)
def test_feature_management_and_probes_are_admin_only(feature_api, method, path):
    client, app, user, requests = feature_api
    user.is_admin = False
    assert getattr(client, method)(path).status_code == 403
    app.dependency_overrides.clear()
    assert getattr(client, method)(path).status_code == 401
    assert requests == []


def test_draft_probe_is_redacted_and_does_not_write_or_change_runtime(feature_api, db):
    client, _, _, requests = feature_api
    response = client.post(
        "/api/system-configs/features/speech/test",
        json={
            "revision": 0,
            "values": {"mode": "api", "api_key": "draft-private", "region": "singapore"},
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "READY"
    assert "draft-private" not in response.text and "st-probe" not in response.text
    assert requests[-1].headers["Authorization"] == "Bearer draft-private"
    assert db.query(FeatureConfig).count() == 0
    assert not feature_settings.has_override("SPEECH_MODE")


@pytest.mark.parametrize(
    "body",
    [
        {"revision": "private-secret", "values": {}},
        {"revision": 0, "values": {"api_key": ["private-secret"]}},
        {"revision": 0, "values": {"api_key": "********"}},
        {"revision": 0, "values": {}, "secret-extra": "private-secret"},
    ],
)
def test_invalid_requests_never_echo_sensitive_input(feature_api, body):
    client, _, _, _ = feature_api
    response = client.put("/api/system-configs/features/speech", json=body)
    assert response.status_code == 422
    assert "private-secret" not in response.text


def test_oauth_and_agent_parameters_resolve_dynamic_settings(db, monkeypatch):
    from app.agents.selection import create_agent_backend_by_name, default_backend_name, opencode_server_kwargs

    save(db, "oauth", {"enabled": True, "client_id": "app-id", "client_secret": "app-secret"})
    save(
        db,
        "agent",
        {
            "backend": "opencode",
            "opencode_url": "http://127.0.0.1:9999",
            "opencode_username": "runtime",
            "opencode_password": "runtime-secret",
        },
    )
    publish(db)
    assert GitHubProvider().is_configured()
    assert default_backend_name() == "opencode"
    assert opencode_server_kwargs() == {
        "server_url": "http://127.0.0.1:9999",
        "username": "runtime",
        "password": "runtime-secret",
    }
    backend = create_agent_backend_by_name()
    assert backend.server_url == "http://127.0.0.1:9999"
    save(db, "oauth", {"enabled": False}, 1)
    publish(db)
    assert not GitHubProvider().is_configured()


def test_stronger_diagnosis_policy_is_enforced_at_execution_boundary(db):
    from app.agents.errors import AgentConfigurationError
    from app.agents.runtime_control import BackendRuntimeControl

    save(db, "diagnosis", {"enforcement": "CONTAINER_SANDBOX"})
    publish(db)
    control = BackendRuntimeControl(SimpleNamespace(name="opencode", probe=AsyncMock(return_value="2.0")))
    with pytest.raises(AgentConfigurationError, match="ENFORCEMENT_UNAVAILABLE"):
        asyncio.run(control.negotiate({"enforcement": "ADVISORY_GUARD"}))


def test_runtime_refresh_rebuilds_search_and_respects_disable(feature_api, db, monkeypatch):
    _, app, _, _ = feature_api
    from app.domains.search import router as search_router

    runtime = feature_runtime.FeatureRuntime(app)
    app.state.feature_runtime = runtime
    app.state.search_runtime = SimpleNamespace(start=Mock(), stop=AsyncMock())
    replace = AsyncMock()
    monkeypatch.setattr(search_router, "replace_client", replace)

    async def scenario():
        await runtime.refresh()
        save(db, "search", {"backend": "sqlite", "es_password": "new-password"})
        await runtime.refresh()
        assert feature_settings.SEARCH_BACKEND == "sqlite"
        assert feature_settings.SEARCH_ES_PASSWORD == "new-password"
        replace.assert_awaited_once()
        await runtime.refresh()
        replace.assert_awaited_once()
        save(db, "search", {"enabled": False}, 1)
        await runtime.refresh()
        assert not feature_settings.SEARCH_ENABLED
        assert replace.await_count == 2
        await runtime.close()

    asyncio.run(scenario())


def test_vector_space_change_creates_new_profile_and_index(feature_api, db, monkeypatch):
    _, app, _, _ = feature_api
    from app.domains.search.embedding import decrypt_key
    from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget

    indices = set()

    async def exists(*, index):
        return index in indices

    async def create(*, index, body):
        indices.add(index)

    app.state.search_es = SimpleNamespace(indices=SimpleNamespace(exists=exists, create=create))
    app.state.search_http = SimpleNamespace()
    monkeypatch.setattr(search_configuration, "embed", AsyncMock(return_value=[[1.0, 0.5]]))
    values = configs.effective(
        "search",
        {
            "enabled": True,
            "backend": "auto",
            "es_url": "http://engine:9200",
            "embedding_api_key": "vector-private",
            "embedding_model": "space-a",
        },
    )

    async def scenario():
        first = await search_configuration.prepare_search(app, values)
        values["embedding_model"] = "space-b"
        second = await search_configuration.prepare_search(app, values)
        assert first != second
        assert db.query(SearchIndexTarget).count() == 2
        profiles = db.query(SearchEmbeddingProfile).all()
        assert len(profiles) == 2
        assert all(decrypt_key(p.encrypted_api_key) == "vector-private" for p in profiles)
        assert all("vector-private" not in p.encrypted_api_key for p in profiles)

    asyncio.run(scenario())


def test_probe_upstream_error_is_redacted(monkeypatch):
    async def failed(values, app, draft):
        raise RuntimeError("secret-upstream-response")

    monkeypatch.setitem(probes.PROBES, "speech", failed)
    response = asyncio.run(probes.probe("speech", {"mode": "api"}, SimpleNamespace()))
    assert response["status"] == "DEGRADED"
    assert "secret-upstream-response" not in str(response)


def test_speech_probe_identifies_rate_limiter_failure_without_upstream_secret_echo(monkeypatch):
    monkeypatch.setattr(probes, "get_redis_client", AsyncMock(side_effect=ConnectionError("private-redis-connection")))
    response = asyncio.run(probes.probe("speech", {"mode": "api", "api_key": "private-key"}, SimpleNamespace()))
    assert response["status"] == "DEGRADED" and response["facts"]["rate_limiter"] is False
    assert "限流组件" in response["explanation"]
    assert "private-redis" not in str(response) and "private-key" not in str(response)


@pytest.mark.parametrize(
    "backend_name,key,url_key",
    [
        ("opencode", "opencode_password", "opencode_url"),
        ("dsh", "dsh_browser_cookie", "dsh_url"),
    ],
)
def test_existing_agent_connection_refreshes_credentials_without_rebinding_session(db, backend_name, key, url_key):
    from app.agents.selection import create_agent_backend_by_name

    save(db, "agent", {"backend": backend_name, url_key: "http://agent:4097", key: "credential-one"})
    publish(db)

    async def scenario():
        backend = create_agent_backend_by_name()
        first = await backend._ensure_client()
        save(db, "agent", {key: "credential-two"}, 1)
        publish(db)
        second = await backend._ensure_client()
        assert second is not first
        assert not first.is_closed
        if backend_name == "opencode":
            assert backend._auth[1] == "credential-two"
        else:
            assert second.headers["Cookie"] == "credential-two"
        save(db, "agent", {url_key: "http://other-agent:4097", key: "credential-three"}, 2)
        publish(db)
        assert await backend._ensure_client() is second
        assert backend.server_url == "http://agent:4097"
        new_backend = create_agent_backend_by_name()
        assert new_backend.server_url == "http://other-agent:4097"
        await new_backend.close()
        await backend.close()
        assert first.is_closed and second.is_closed

    asyncio.run(scenario())


def test_search_cluster_binding_keeps_old_targets_out_of_new_cluster_work(db, monkeypatch):
    from app.domains.search import worker
    from app.domains.search.models import SearchIndexTarget
    from app.domains.search.projection import digest
    from app.domains.search.service import configuration

    monkeypatch.setattr(settings, "SEARCH_ES_URL", "http://cluster-a:9200")
    old = SearchIndexTarget(physical_index="old-index", status="active")
    db.add(old)
    db.commit()
    search_configuration.bind_existing_targets(db, settings.SEARCH_ES_URL)
    db.commit()
    feature_settings.replace({"SEARCH_ES_URL": "http://cluster-b:9200"})
    assert configuration(db) == (None, None)
    new = SearchIndexTarget(
        physical_index="new-index", status="active", connection_fingerprint=digest("http://cluster-b:9200")
    )
    db.add(new)
    db.commit()
    assert configuration(db)[0]["physical_index"] == "new-index"
    monkeypatch.setattr(worker, "owns", lambda *args: True)
    monkeypatch.setattr(worker, "current_document", lambda *args: None)
    work = worker.read_work(db, {"event_kind": "entity_changed", "entity_key": "task:missing"})
    assert [target["physical_index"] for target in work[1]] == ["new-index"]


def test_existing_vector_profile_is_a_masked_database_default(db, monkeypatch):
    from app.domains.search.embedding import encrypt_key
    from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget

    monkeypatch.setattr(settings, "SEARCH_EMBEDDING_API_KEY", "env-fallback-private")
    profile = SearchEmbeddingProfile(
        id="legacy-profile",
        endpoint="https://legacy.test/embeddings",
        model_id="legacy-space",
        encrypted_api_key=encrypt_key("legacy-private"),
    )
    db.add(profile)
    db.add(SearchIndexTarget(physical_index="legacy-index", status="active", embedding_profile_id=profile.id))
    db.commit()
    values, overrides, revision = configs.read(db, "search")
    assert values["embedding_api_key"] == "legacy-private"
    assert values["embedding_model"] == "legacy-space"
    assert not overrides and revision == 0
    public = configs.public(db, "search")
    key = next(field for field in public["fields"] if field["key"] == "embedding_api_key")
    assert key["source"] == "database" and key["value"] == "lega********vate"
    assert "legacy-private" not in str(public) and "env-fallback-private" not in str(public)
    save(db, "search", {"es_password": "new-es-secret"})
    assert configs.read(db, "search")[0]["embedding_api_key"] == "legacy-private"
    save(db, "search", {"embedding_api_key": ""}, 1)
    assert configs.read(db, "search")[0]["embedding_api_key"] == ""


def test_draft_vector_probe_uses_draft_credential_instead_of_published_credential(feature_api, monkeypatch):
    from contextlib import asynccontextmanager

    client, _, _, requests = feature_api
    feature_settings.replace(
        {
            "SEARCH_EMBEDDING_API_KEY": "published-private",
            "SEARCH_EMBEDDING_ENDPOINT": "https://vector.test/embeddings",
            "SEARCH_EMBEDDING_MODEL": "draft-space",
        }
    )

    @asynccontextmanager
    async def es_context(values):
        yield SimpleNamespace(
            cluster=SimpleNamespace(health=AsyncMock(return_value={"status": "green"})),
            indices=SimpleNamespace(exists=AsyncMock(return_value=False)),
        )

    monkeypatch.setattr(probes, "make_search_client", es_context)
    response = client.post(
        "/api/system-configs/features/search/test",
        json={
            "revision": 0,
            "values": {
                "backend": "auto",
                "es_url": "http://es:9200",
                "embedding_api_key": "draft-private",
                "embedding_model": "draft-space",
                "embedding_endpoint": "https://vector.test/embeddings",
            },
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "READY"
    request = next(request for request in requests if request.url.path.endswith("/embeddings"))
    assert request.headers["Authorization"] == "Bearer draft-private"
    assert "draft-private" not in response.text and "published-private" not in response.text
    assert feature_settings.SEARCH_EMBEDDING_API_KEY == "published-private"


def test_running_vector_calls_use_rotated_credentials_without_waiting_for_reindex():
    from app.domains.search.embedding import EmbeddingError, encrypt_key, profile_key

    profile = {
        "endpoint": "https://vector.test/embeddings",
        "model_id": "same-space",
        "encrypted_api_key": encrypt_key("old-private"),
    }
    feature_settings.replace(
        {
            "SEARCH_EMBEDDING_ENDPOINT": profile["endpoint"],
            "SEARCH_EMBEDDING_MODEL": profile["model_id"],
            "SEARCH_EMBEDDING_API_KEY": "new-private",
        }
    )
    assert profile_key(profile, True) == "new-private"
    assert profile_key(profile, False) == "old-private"
    feature_settings.replace({"SEARCH_EMBEDDING_API_KEY": ""})
    with pytest.raises(EmbeddingError, match="KEY_MISSING"):
        profile_key(profile, True)


def test_legacy_environment_url_does_not_expose_embedded_credentials(db, monkeypatch):
    monkeypatch.setattr(
        settings, "SEARCH_ES_URL", "https://user:inline-private@engine.test:9200/path?token=query-private"
    )
    public = configs.public(db, "search")
    url = next(field["value"] for field in public["fields"] if field["key"] == "es_url")
    assert url == "https://engine.test:9200/path"
    assert "inline-private" not in str(public) and "query-private" not in str(public)


def test_reset_search_does_not_inherit_managed_index_credentials(db, monkeypatch):
    from app.domains.search.embedding import encrypt_key
    from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget

    monkeypatch.setattr(settings, "SEARCH_EMBEDDING_API_KEY", "env-private")
    profile = SearchEmbeddingProfile(
        id="managed-profile",
        endpoint="https://managed.test/embeddings",
        model_id="managed-space",
        encrypted_api_key=encrypt_key("managed-private"),
    )
    db.add(profile)
    db.add(
        SearchIndexTarget(
            physical_index="traceforge-search-runtime-managed", status="active", embedding_profile_id=profile.id
        )
    )
    db.commit()
    save(db, "search", {"embedding_api_key": "managed-private", "embedding_model": "managed-space"})
    save(db, "search", {}, 1, True)
    values, overrides, _ = configs.read(db, "search")
    assert values["embedding_api_key"] == "env-private"
    assert values["embedding_model"] == settings.SEARCH_EMBEDDING_MODEL
    assert overrides == {}


def test_adopting_legacy_vector_profile_preserves_space_and_original_credential(feature_api, db, monkeypatch):
    from app.domains.search.embedding import decrypt_key, encrypt_key
    from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget

    _, app, _, _ = feature_api
    profile = SearchEmbeddingProfile(
        id="custom-profile",
        endpoint="https://custom.test/embeddings",
        model_id="custom-space",
        encrypted_api_key=encrypt_key("original-private"),
        dimension=2,
        fingerprint="custom-fingerprint",
        query_prefix="query: ",
        status="tested",
    )
    db.add(profile)
    db.add(SearchIndexTarget(physical_index="custom-index", status="active", embedding_profile_id=profile.id))
    db.commit()
    app.state.search_http = SimpleNamespace()
    app.state.search_es = SimpleNamespace(
        indices=SimpleNamespace(exists=AsyncMock(return_value=False), create=AsyncMock())
    )
    monkeypatch.setattr(search_configuration, "embed", AsyncMock(return_value=[[1.0, 0.5]]))
    save(db, "search", {"embedding_api_key": "replacement-private"})
    values = configs.read(db, "search")[0]
    asyncio.run(search_configuration.prepare_search(app, values))
    assert db.query(SearchEmbeddingProfile).count() == 1
    db.refresh(profile)
    assert profile.query_prefix == "query: "
    assert decrypt_key(profile.encrypted_api_key) == "original-private"
    save(db, "search", {}, 1, True)
    assert configs.read(db, "search")[0]["embedding_api_key"] == settings.SEARCH_EMBEDDING_API_KEY


def test_vector_secret_inherit_explicitly_uses_environment_over_legacy_db(db, monkeypatch):
    from app.domains.search.embedding import encrypt_key
    from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget

    monkeypatch.setattr(settings, "SEARCH_EMBEDDING_API_KEY", "env-private")
    profile = SearchEmbeddingProfile(
        id="legacy-inherit",
        endpoint="https://legacy.test/embeddings",
        model_id="legacy-space",
        encrypted_api_key=encrypt_key("legacy-private"),
    )
    db.add(profile)
    db.add(SearchIndexTarget(physical_index="legacy-inherit-index", status="active", embedding_profile_id=profile.id))
    db.commit()
    save(db, "search", {"embedding_api_key": None})
    assert configs.read(db, "search")[0]["embedding_api_key"] == "env-private"
    public = configs.public(db, "search")
    field = next(field for field in public["fields"] if field["key"] == "embedding_api_key")
    assert field["source"] == "environment" and field["value"] == "********"


def test_additive_migration_preserves_existing_search_targets():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, select

    engine = create_engine("sqlite://")
    metadata = MetaData()
    existing = Table("search_index_targets", metadata, Column("target_id", String(36), primary_key=True))
    metadata.create_all(engine)
    path = Path(__file__).resolve().parents[2] / "alembic/versions/a7c81d39e602_runtime_feature_configs.py"
    spec = importlib.util.spec_from_file_location("feature_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.execute(existing.insert().values(target_id="keep-existing"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert "feature_configs" in inspect(connection).get_table_names()
        assert "connection_fingerprint" in {
            column["name"] for column in inspect(connection).get_columns("search_index_targets")
        }
        assert connection.execute(select(existing.c.target_id)).scalar() == "keep-existing"
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.execute(select(existing.c.target_id)).scalar() == "keep-existing"
    engine.dispose()
