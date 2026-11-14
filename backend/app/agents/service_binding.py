"""Routing for server Agent attempts and their native sessions."""

import json
import ntpath
import posixpath
from dataclasses import dataclass, field

from app.agents.registry import backend_config_kwargs, create_agent_backend
from app.domains.system_config.models.feature_config import FeatureConfig
from app.domains.system_config.services import feature_config_service as configs

SERVER_AGENTS = frozenset({"opencode", "dsh"})
OLD_SERVICE_UNKNOWN = "OLD_AGENT_SERVICE_UNKNOWN"
OLD_SERVICE_MESSAGE = "旧服务不可达，执行结果未知"


@dataclass(frozen=True)
class AgentService:
    name: str
    generation: int
    kwargs: dict = field(repr=False)

    def adapter(self):
        return create_agent_backend(self.name, **self.kwargs)

    def persist(self) -> dict:
        return {
            "backend": self.name,
            "generation": self.generation,
            "connection": configs.cipher().encrypt(json.dumps(self.kwargs).encode()).decode(),
        }

    @classmethod
    def restore(cls, binding):
        kwargs = json.loads(configs.cipher().decrypt(binding["connection"].encode()))
        return cls(binding["backend"], binding["generation"], kwargs)


def configured_service(db, name: str, *, lock=False) -> AgentService:
    # Read the committed configuration even if this worker's hot-reload is lagging.
    row = (
        db.query(FeatureConfig).filter_by(feature="agent").populate_existing().with_for_update(read=True).first()
        if lock
        else db.get(FeatureConfig, "agent")
    )
    values = configs.effective("agent", configs.decrypt(row))
    generation = _address_generation(row, name)
    return AgentService(name, generation, backend_config_kwargs(name, values))


def _address_generation(row, name):
    return (row.agent_address_generations or {}).get(name, 0) if row else 0


def agent_address_generation(db, name: str) -> int:
    return _address_generation(db.get(FeatureConfig, "agent"), name)


def same_directory(actual: str, expected: str) -> bool:
    if not actual or not expected:
        return False
    if ntpath.splitdrive(expected)[0]:
        return ntpath.normcase(ntpath.normpath(actual)) == ntpath.normcase(ntpath.normpath(expected))
    return posixpath.normpath(actual) == posixpath.normpath(expected)


async def matches_native_session(backend, identity, session_id):
    native = await backend.native_session(session_id)
    return bool(
        native
        and native.get("readable", True)
        and identity.get("id") == session_id
        and same_directory(native.get("directory"), identity.get("directory"))
        and (identity.get("created") is None or native.get("created") == identity["created"])
    )
