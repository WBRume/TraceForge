"""Inject MCP into a private OpenCode directory and a forked session.

OpenCode's dynamic MCP configuration is directory-scoped, not session-scoped.
Never configure it on a shared task working directory.
"""

import asyncio
import tempfile
from contextlib import asynccontextmanager
from dataclasses import replace
from urllib.parse import urlparse

from app.agents.errors import AgentConfigurationError


@asynccontextmanager
async def scoped_request(backend, request, binding, *, tool_names):
    # The MCP listener and the workspace reader run on this application host.
    # A remote host cannot reach our loopback endpoint; do not leak credentials
    # or silently configure an unusable tool in a shared remote environment.
    if urlparse(backend.server_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AgentConfigurationError("DOMAIN_TOOLS_REQUIRE_COLOCATED_OPENCODE")
    client = await backend._ensure_client()
    with tempfile.TemporaryDirectory(prefix="traceforge-domain-") as directory:
        location = {"location[directory]": directory}
        endpoint = backend.server_url + "/api/experimental/mcp/traceforge_domain"
        session_id = request.session_id
        permissions = []
        if session_id:
            response = await client.get(backend._session_url(session_id))
            backend._check_response(response, "domain source permissions")
            permissions = response.json()["data"].get("permissions") or []
            session_id = await backend.fork_session(session_id, source_dir=request.project_path, target_dir=directory)
        scoped = replace(
            request,
            project_path=directory,
            session_id=session_id,
            provider_options={
                **request.provider_options,
                "domain_mcp": binding,
                "domain_tool_names": tuple(tool_names),
            },
        )
        configured = False
        try:
            response = await client.put(
                endpoint,
                params=location,
                json={
                    "config": {
                        "type": "remote",
                        "url": binding["url"],
                        "headers": binding["headers"],
                        "oauth": False,
                        "codemode": False,
                    }
                },
            )
            backend._check_response(response, "domain MCP configuration")
            configured = True
            await wait_connected(backend, client, location)
            yield scoped
            # A successful child can become a document thread's next session.
            # Restore its directory and original permissions before exposing
            # it to ordinary follow-up chat; never retain a deleted temp cwd.
            completed_session = getattr(backend, "_session_id", None) or session_id
            if completed_session:
                await restore_session(backend, client, completed_session, request.project_path, permissions)
        finally:
            if configured:
                # Revocation of the endpoint remains authoritative even if the
                # provider goes offline during cleanup.
                try:
                    response = await client.delete(endpoint, params=location)
                    backend._check_response(response, "domain MCP cleanup")
                except Exception:
                    # The listener is revoked by the outer invocation in all
                    # cases; no remote configuration can reuse its credentials.
                    from app.core.logging import get_logger

                    get_logger(__name__).warning("Could not remove expired domain MCP configuration")


async def restore_session(backend, client, session_id, directory, permissions):
    await backend._fork_move(client, session_id, directory)
    response = await client.patch(backend._session_url(session_id), json={"permissions": permissions})
    backend._check_response(response, "restore domain session permissions")
    await backend._ensure_workspace_permissions(session_id, directory)


async def wait_connected(backend, client, location):
    async with asyncio.timeout(20):
        while True:
            response = await client.get(backend.server_url + "/api/mcp", params=location)
            backend._check_response(response, "domain MCP status")
            status = next(
                (
                    item.get("status", {})
                    for item in response.json().get("data", [])
                    if item.get("name") == "traceforge_domain"
                ),
                {},
            )
            if status.get("status") == "connected":
                return
            if status.get("status") not in {"pending", None}:
                raise AgentConfigurationError(f"DOMAIN_MCP_NOT_CONNECTED: {status.get('status')}")
            await asyncio.sleep(0.2)
