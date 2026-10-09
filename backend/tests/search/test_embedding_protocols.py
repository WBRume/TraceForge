import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.domains.search.embedding import EmbeddingError, embed, encrypt_key
from app.domains.search.embedding_protocols import PROTOCOLS, profile_fingerprint, validate_vectors
from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget
from app.domains.search.router import ProfileInput, save_profile
from app.domains.system_config.services import feature_config_service as configs


class AlternateProtocol:
    label = "Test protocol"

    def request(self, model, texts, *, query):
        return {"texts": texts, "model": model, "purpose": "query" if query else "document"}

    def parse(self, payload, count, dimension):
        return validate_vectors(
            {"data": [{"index": i, "embedding": row} for i, row in enumerate(payload["vectors"])]}, count, dimension
        )


def test_protocol_dispatch_covers_query_and_document(monkeypatch):
    monkeypatch.setitem(PROTOCOLS, "alternate", AlternateProtocol())
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"vectors": [[1.0, 2.0]]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            profile = {
                "endpoint": "https://vector.example/encode",
                "model_id": "model",
                "protocol": "alternate",
                "encrypted_api_key": encrypt_key("test-key"),
                "query_prefix": "query: ",
                "dimension": 2,
            }
            assert await embed(client, profile, ["text"], runtime_credentials=False) == [[1.0, 2.0]]
            await embed(client, profile, ["text"], query=True, runtime_credentials=False)
            with pytest.raises(EmbeddingError, match="UNSUPPORTED_PROTOCOL"):
                await embed(client, profile | {"protocol": "unknown"}, ["text"])

    asyncio.run(scenario())
    assert requests == [
        {"texts": ["text"], "model": "model", "purpose": "document"},
        {"texts": ["query: text"], "model": "model", "purpose": "query"},
    ]


def test_bound_profile_is_forked_when_protocol_changes(db, monkeypatch):
    monkeypatch.setitem(PROTOCOLS, "alternate", AlternateProtocol())
    profile = SearchEmbeddingProfile(
        endpoint="https://vector.example/encode",
        model_id="model",
        status="tested",
        dimension=2,
        encrypted_api_key=encrypt_key("key"),
    )
    db.add(profile)
    db.flush()
    db.add(SearchIndexTarget(physical_index="traceforge-search-protocol", embedding_profile_id=profile.id))
    db.flush()
    result = save_profile(
        db,
        ProfileInput(
            id=profile.id,
            revision=profile.revision,
            endpoint=profile.endpoint,
            model_id=profile.model_id,
            protocol="alternate",
        ),
    )
    assert result["id"] != profile.id
    assert result["protocol"] == "alternate"
    assert profile.protocol == "openai_compatible"
    assert profile.dimension == 2
    assert result["dimension"] is None
    updated = save_profile(
        db,
        ProfileInput(
            id=result["id"],
            revision=result["revision"],
            endpoint=profile.endpoint,
            model_id=profile.model_id,
            api_key="rotated",
        ),
    )
    assert updated["protocol"] == "alternate"
    values = {"endpoint": profile.endpoint, "model_id": profile.model_id, "dimension": 2}
    assert profile_fingerprint(values) == profile_fingerprint(values | {"protocol": "openai_compatible"})
    assert profile_fingerprint(values) != profile_fingerprint(values | {"protocol": "alternate"})


def test_protocol_appears_in_settings_and_unknown_values_are_rejected(db):
    public = configs.public(db, "search")
    field = next(f for f in public["fields"] if f["key"] == "embedding_protocol")
    assert field["value"] == "openai_compatible"
    assert field["option_labels"]["openai_compatible"] == "OpenAI 兼容"


def test_migration_preserves_existing_profiles_and_supplies_legacy_protocol():
    path = Path(__file__).parents[2] / "alembic/versions/c9a13f75d802_embedding_protocol.py"
    spec = importlib.util.spec_from_file_location("protocol_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE search_embedding_profiles (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO search_embedding_profiles (id) VALUES ('existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(text("SELECT id, protocol FROM search_embedding_profiles")).one() == (
            "existing",
            "openai_compatible",
        )
    engine.dispose()
