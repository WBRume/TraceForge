import asyncio

import httpx
import pytest

from app.agents.domain_tools import DomainTool, DomainToolError, DomainToolRun
from app.agents.domain_tools.contracts import DocumentRewrite, RequirementSubmission, SkillReview
from app.agents.domain_tools.validators import skill_review_validator, validate_mock_cases, validate_openapi
from app.agents.tool_transports.mcp import create_app, serve_tools


def requirement(title="Login"):
    return {
        "items": [
            {
                "title": title,
                "body": "Allow users to sign in",
                "acceptance_criteria": ["Valid credentials sign in"],
                "task_prompt": "Implement sign in",
                "priority": "P1",
            }
        ]
    }


def make_run(**kwargs):
    return DomainToolRun(DomainTool("submit_requirements", "需求草案", RequirementSubmission), **kwargs)


@pytest.mark.asyncio
async def test_invalid_then_valid_submission_repairs_in_the_same_run():
    run = make_run()
    invalid = requirement()
    invalid["items"][0]["priority"] = "urgent"
    rejected = await run.invoke(run.tool.name, invalid, "bad")
    assert rejected.is_error is True
    assert rejected.data["issues"][0]["path"] == ["items", 0, "priority"]
    assert rejected.data["action"] == "correct_arguments"
    assert run.value is None
    accepted = await run.invoke(run.tool.name, requirement(), "good")
    assert not accepted.is_error
    assert run.require_result().items[0].title == "Login"
    assert [event.stage for event in run.events] == ["validating", "repairing", "validating", "accepted"]
    assert {event.run_id for event in run.events} == {run.run_id}
    assert not any(event.stage == "persisted" for event in run.events)


@pytest.mark.asyncio
async def test_duplicate_and_conflicting_submissions_cannot_replace_result():
    run = make_run()
    first, duplicate = await asyncio.gather(
        run.invoke(run.tool.name, requirement(), "one"), run.invoke(run.tool.name, requirement(), "two")
    )
    assert first == duplicate
    assert len(run.events) == 2
    assert (await run.invoke(run.tool.name, requirement("different"), "three")).is_error
    assert run.require_result().items[0].title == "Login"


@pytest.mark.asyncio
async def test_cancel_during_validation_discards_result():
    cancelled = False

    async def validate(_):
        nonlocal cancelled
        cancelled = True

    run = DomainToolRun(
        DomainTool("submit", "Submit", RequirementSubmission, validate), should_cancel=lambda: cancelled
    )
    result = await run.invoke("submit", requirement(), "one")
    assert result.is_error
    assert run.value is None
    with pytest.raises(DomainToolError, match="REVOKED"):
        run.require_result()


@pytest.mark.asyncio
async def test_operational_failure_is_not_a_correctable_or_successful_result():
    def validate(_):
        raise OSError("database unavailable")

    run = DomainToolRun(DomainTool("submit", "Submit", RequirementSubmission, validate))
    result = await run.invoke("submit", requirement(), "one")
    assert result.data["action"] == "report_defect"
    assert result.data["diagnostic_id"]
    with pytest.raises(OSError, match="database unavailable"):
        run.require_result()


@pytest.mark.asyncio
async def test_no_tool_call_never_accepts_prose_or_an_empty_result():
    with pytest.raises(DomainToolError, match="DOMAIN_RESULT_MISSING"):
        make_run().require_result()


@pytest.mark.asyncio
async def test_mcp_authorization_scope_and_real_socket_lifecycle(tmp_path):
    run = make_run()
    run.project_path = str(tmp_path)
    async with serve_tools(run) as binding:
        async with httpx.AsyncClient(trust_env=False) as client:
            from app.agents.tool_transports.protocol import CAPABILITIES_KEY, MCP_VERSION, VERSION_KEY

            headers = {
                **binding["headers"],
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": MCP_VERSION,
                "mcp-method": "server/discover",
            }
            meta = {VERSION_KEY: MCP_VERSION, CAPABILITIES_KEY: {}}
            rpc = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": meta}}
            assert (await client.post(binding["url"], json=rpc)).status_code == 401
            old = {"jsonrpc": "2.0", "id": "old", "method": "initialize", "params": {}}
            rejection = await client.post(binding["url"], headers=binding["headers"], json=old)
            assert rejection.status_code == 400 and rejection.json()["error"]["code"] == -32602
            wrong_version = {**rpc, "params": {"_meta": {**meta, VERSION_KEY: "2025-11-25"}}}
            rejection = await client.post(binding["url"], headers=headers, json=wrong_version)
            assert rejection.json()["error"]["code"] == -32022
            assert (
                await client.post(binding["url"], headers={**headers, "Origin": "https://hostile.invalid"}, json=rpc)
            ).status_code == 403
            assert (await client.post(binding["url"], headers=headers, json=rpc)).json()["result"][
                "supportedVersions"
            ] == [MCP_VERSION]
            rpc.update(id=2, method="tools/list")
            headers["mcp-method"] = "tools/list"
            response = await client.post(binding["url"], headers=headers, json=rpc)
            tools = response.json()["result"]["tools"]
            assert {t["name"] for t in tools} == {"submit_requirements", "read_workspace"}
            assert all(t["outputSchema"] for t in tools)
            rpc.update(
                id=3,
                method="tools/call",
                params={"_meta": meta, "name": "submit_requirements", "arguments": requirement()},
            )
            headers.update({"mcp-method": "tools/call", "mcp-name": "submit_requirements"})
            mismatched = await client.post(binding["url"], headers={**headers, "mcp-name": "read_workspace"}, json=rpc)
            assert mismatched.json()["error"]["code"] == -32020
            assert run.value is None
            result = (await client.post(binding["url"], headers=headers, json=rpc)).json()["result"]
            assert result["isError"] is False
            assert result["resultType"] == "complete"
            assert result["structuredContent"]["stage"] == "accepted"
            assert run.require_result().items
    async with httpx.AsyncClient(trust_env=False) as client:
        with pytest.raises(httpx.ConnectError):
            await client.post(binding["url"], headers=binding["headers"], json=rpc)


@pytest.mark.asyncio
async def test_workspace_reader_rejects_escape_and_does_not_expose_secrets(tmp_path):
    run = make_run()
    run.project_path = str(tmp_path)
    (tmp_path / "source.py").write_text("hello\nworld\n", encoding="utf-8")
    result = await run.invoke("read_workspace", {"path": "source.py", "start_line": 2}, "read")
    assert result.data["text"] == "world"
    for path in ("../outside", ".env", ".git/config"):
        assert (await run.invoke("read_workspace", {"path": path}, "bad")).is_error


@pytest.mark.asyncio
async def test_http_rejects_malformed_and_oversized_input():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(make_run(), "token")), base_url="http://test"
    ) as client:
        headers = {"Authorization": "Bearer token"}
        assert (await client.post("/mcp", headers=headers, content=b"x" * 2_000_001)).status_code == 413
        assert (await client.post("/mcp", headers=headers, content=b"bad json")).json()["error"]["code"] == -32700


def test_document_scope_and_skill_evidence_are_validated(tmp_path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DocumentRewrite.model_validate({"scope": "document", "anchor_text": "partial", "change_summary": "updated"})
    with pytest.raises(ValidationError):
        SkillReview.model_validate(
            {
                "risk_level": "HIGH",
                "complexity": "LOW",
                "review_priority": "HIGH",
                "risk_items": [],
                "review_suggestions": [],
            }
        )
    review = SkillReview.model_validate(
        {"risk_level": "LOW", "complexity": "LOW", "review_priority": "LOW", "risk_items": [], "review_suggestions": []}
    )
    skill_review_validator(tmp_path)(review)


def test_openapi_schema_and_internal_references():
    from app.agents.domain_tools.contracts import OpenAPISubmission

    document = {
        "openapi": "3.0.3",
        "info": {"title": "Example", "version": "1"},
        "paths": {"/test": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    validate_openapi(OpenAPISubmission(document=document))
    document["paths"]["/test"]["get"]["responses"] = {"200": {"$ref": "https://example.com/secret"}}
    with pytest.raises(DomainToolError, match="internal"):
        validate_openapi(OpenAPISubmission(document=document))
    document["paths"]["/test"]["get"]["responses"] = {}
    with pytest.raises(DomainToolError):
        validate_openapi(OpenAPISubmission(document=document))


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef", "$id"])
def test_openapi_cannot_resolve_external_schema_resources(keyword):
    from app.agents.domain_tools.contracts import OpenAPISubmission

    value = OpenAPISubmission(
        document={
            "openapi": "3.1.0",
            "info": {"title": "Test", "version": "1"},
            "paths": {},
            "components": {"schemas": {"Test": {keyword: "https://external.invalid/schema"}}},
        }
    )
    with pytest.raises(DomainToolError):
        validate_openapi(value)


@pytest.mark.asyncio
async def test_mockjs_validates_with_real_runtime():
    from app.agents.domain_tools.contracts import MockSubmission

    valid = MockSubmission(
        cases=[
            {"name": "Success", "mode": "MOCKJS", "status_code": 200, "mockjs_template": '{"items|1-2":[{"id|+1":1}]}'}
        ]
    )
    await validate_mock_cases(valid)
    valid.cases[0].mockjs_template = "{ broken }"
    with pytest.raises(DomainToolError, match="JSON Mock.js"):
        await validate_mock_cases(valid)
