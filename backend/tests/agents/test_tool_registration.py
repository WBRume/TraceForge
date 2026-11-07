"""A third-party native adapter must work without modifying any business caller."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from app.agents import registry
from app.agents.adapters.mock.mock_adapter import MockAdapter
from app.agents.contract import AgentCapabilities, AgentRunResult
from app.agents.domain_tools import DomainTool, DomainToolRun
from app.agents.domain_tools.contracts import RequirementSubmission
from app.agents.domain_tools.invocation import active_domain_run, invoke_domain
from app.agents.errors import AgentConfigurationError
from app.agents.events import AgentEvent
from app.agents.model_selection import validate_selection
from app.agents.registration import AgentSetting
from app.agents.selection import create_agent_backend_by_name, list_agent_backends
from app.core.feature_settings import feature_settings
from app.domains.ai.services.jobs.domain_turn import run_domain_turn
from app.domains.system_config.services import capability_probe
from app.domains.system_config.services import feature_config_service as configs
from app.domains.system_config.services.config_fields import ConfigField

SUBMISSION = {
    "items": [
        {
            "title": "Native tool result",
            "body": "Business artifact",
            "acceptance_criteria": ["validated"],
            "task_prompt": "Implement",
            "priority": "P1",
        }
    ]
}


class NativeAdapter(MockAdapter):
    name = "native-fixture"
    capabilities = AgentCapabilities(preferred_mode="sdk", execution_kind="REMOTE_SESSION")
    contexts = []

    def __init__(self, endpoint="http://native.invalid", api_key=""):
        super().__init__()
        self.endpoint = endpoint
        self.api_key = api_key
        self.tools = None

    @asynccontextmanager
    async def bind_tools(self, request, tools):
        self.tools = tools
        self.contexts.append(tools)
        try:
            yield request
        finally:
            self.tools = None

    async def run(self, request, on_event):
        tools = self.tools
        assert tools is not None
        name = next(tool.name for tool in tools.definitions if tool.name != "read_workspace")
        assert (await tools.invoke(name, {}, "invalid")).data["code"] == "VALIDATION_FAILED"
        accepted = await tools.invoke(name, SUBMISSION, "valid")
        assert not accepted.is_error
        assert accepted == await tools.invoke(name, SUBMISSION, "duplicate")
        await on_event(
            AgentEvent(type="session_started", provider=self.name, payload={"provider_session_id": "native-session"})
        )
        await on_event(
            AgentEvent(type="result", provider=self.name, payload={"success": True, "result": "not the artifact"})
        )
        return AgentRunResult(
            run_id=request.run_id, session_id="native-session", success=True, result_text="not the artifact"
        )


@pytest.fixture
def native(monkeypatch):
    # Import-time feature catalogues already exist before this registration.
    registered = registry.registered_backends()
    monkeypatch.setattr(registry, "AGENT_BACKENDS", dict(registered))
    NativeAdapter.contexts = []
    registry.register_backend(
        NativeAdapter.name,
        NativeAdapter,
        label="Native fixture",
        settings=(
            AgentSetting(
                "endpoint",
                ConfigField(
                    "native_url", "Native URL", "NATIVE_FIXTURE_URL", "url", default_value="http://native.invalid"
                ),
            ),
            AgentSetting("api_key", ConfigField("native_key", "Native key", "NATIVE_FIXTURE_KEY", "secret")),
        ),
    )
    previous = dict(feature_settings._overrides)
    feature_settings.replace({})
    yield NativeAdapter.name
    feature_settings.replace(previous)


@pytest.mark.asyncio
async def test_registered_native_adapter_runs_existing_domain_turn_without_mcp(native, monkeypatch, tmp_path):
    from app.agents.tool_transports import mcp

    def unexpected_listener(*_):
        pytest.fail("Native tools must not create an MCP listener")

    monkeypatch.setattr(mcp, "serve_tools", unexpected_listener)
    result = await run_domain_turn(
        "Generate requirements",
        str(tmp_path),
        backend_name=native,
        tool=DomainTool("submit_requirements", "Requirements", RequirementSubmission),
        timeout_seconds=5,
    )
    assert result["artifact"].items[0].title == "Native tool result"
    assert result["text"] == "not the artifact"
    assert [event["stage"] for event in result["domain_milestones"]] == [
        "started",
        "validating",
        "repairing",
        "validating",
        "accepted",
    ]
    assert active_domain_run.get() is None
    late = await NativeAdapter.contexts[0].invoke("submit_requirements", SUBMISSION, "late")
    assert late.data == {"code": "DOMAIN_RUN_REVOKED", "retryable": False}


def test_one_registration_drives_settings_construction_models_and_probe(native, db, monkeypatch):
    monkeypatch.setenv("NATIVE_FIXTURE_KEY", "environment-secret")
    assert native in registry.selectable_backend_names()
    assert next(item for item in list_agent_backends() if item["value"] == native)["label"] == "Native fixture"
    assert native in configs.fields_for("agent")[0].options
    assert configs.effective("agent", {})["native_key"] == "environment-secret"
    values = {"backend": native, "native_url": "http://saved.invalid", "native_key": "saved-secret"}
    public = configs.save(db, "agent", values, 0, "admin")
    db.commit()
    assert "saved-secret" not in json.dumps(public)
    feature_settings.replace(configs.environment_snapshot(configs.snapshot(db)))
    backend = create_agent_backend_by_name()
    assert isinstance(backend, NativeAdapter)
    assert (backend.endpoint, backend.api_key) == ("http://saved.invalid", "saved-secret")
    probe = capability_probe.make_agent({**values, "native_key": "draft-secret"})
    assert probe.api_key == "draft-secret" and backend.api_key == "saved-secret"
    assert validate_selection({"backend": native, "model": "native-model"}, native)["model"] == "native-model"


def test_registration_rejects_claimed_tool_support_without_binding(native):
    class Incomplete(MockAdapter):
        name = "incomplete-fixture"
        capabilities = AgentCapabilities()

    with pytest.raises(AgentConfigurationError, match="bind_tools"):
        registry.register_backend(Incomplete.name, Incomplete)
    assert Incomplete.name not in registry.registered_backends()


def test_registered_fields_read_dotenv_without_global_settings_changes(monkeypatch, tmp_path):
    from app.domains.system_config.services import config_fields

    env_file = tmp_path / ".env"
    env_file.write_text("PLUGIN_URL=http://file.invalid\nPLUGIN_ENABLED=true\nPLUGIN_LIMIT=12\n", encoding="utf-8")
    monkeypatch.setitem(config_fields.settings.model_config, "env_file", str(env_file))
    config_fields._registered_env_defaults.cache_clear()
    try:
        url = ConfigField("plugin_url", "URL", "PLUGIN_URL", "url")
        assert url.default() == "http://file.invalid"
        assert ConfigField("enabled", "Enabled", "PLUGIN_ENABLED", "boolean").default() is True
        assert ConfigField("limit", "Limit", "PLUGIN_LIMIT", "number").default() == 12
        monkeypatch.setenv("PLUGIN_URL", "http://process.invalid")
        assert url.default() == "http://process.invalid"
    finally:
        config_fields._registered_env_defaults.cache_clear()


def test_catalogue_preserves_runtime_factory_fork_capability(native):
    class ForkAdapter(NativeAdapter):
        name = "fork-fixture"
        capabilities = AgentCapabilities(supports_fork=True)

    registry.register_backend(ForkAdapter.name, ForkAdapter, runtime_factory=NativeAdapter)
    option = next(item for item in list_agent_backends() if item["value"] == ForkAdapter.name)
    assert option["supports_fork"] is False


def test_registration_rejects_duplicate_configuration_keys(native):
    class Conflict(NativeAdapter):
        name = "conflict-fixture"

    with pytest.raises(AgentConfigurationError, match="keys must be unique"):
        registry.register_backend(
            Conflict.name,
            Conflict,
            settings=(AgentSetting("endpoint", ConfigField("native_url", "Conflicting URL", "CONFLICT_URL")),),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failure", "timeout", "cancel"])
async def test_tool_callbacks_revoked_on_every_exit(outcome, tmp_path):
    run = DomainToolRun(DomainTool("submit_requirements", "Requirements", RequirementSubmission))

    async def operation():
        assert active_domain_run.get() is run
        if outcome == "failure":
            raise RuntimeError("provider failed")
        if outcome == "timeout":
            raise TimeoutError("provider timed out")
        raise asyncio.CancelledError

    with pytest.raises((RuntimeError, TimeoutError, asyncio.CancelledError)):
        await invoke_domain(run, operation, project_path=str(tmp_path))
    assert active_domain_run.get() is None
    assert (await run.invoke(run.tool.name, SUBMISSION, "late")).data["code"] == "DOMAIN_RUN_REVOKED"


@pytest.mark.asyncio
async def test_concurrent_native_turns_keep_separate_contexts(native, tmp_path):
    async def turn():
        return await run_domain_turn(
            "Generate",
            str(tmp_path),
            backend_name=native,
            tool=DomainTool("submit_requirements", "Requirements", RequirementSubmission),
            timeout_seconds=5,
        )

    results = await asyncio.gather(turn(), turn())
    assert results[0]["domain_milestones"][0]["run_id"] != results[1]["domain_milestones"][0]["run_id"]
    assert len(NativeAdapter.contexts) == 2
    assert NativeAdapter.contexts[0] is not NativeAdapter.contexts[1]
