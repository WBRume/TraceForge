"""Authenticated control client for the dedicated DSH playbook guard plugin."""
import os
import httpx
from app.agents.errors import AgentConfigurationError


async def guard_request(binding, path, payload=None):
    if not isinstance(binding, dict) or not binding.get("url") or not binding.get("token_env"):
        raise AgentConfigurationError("SOP_EXECUTOR_GUARD_NOT_BOUND")
    token = os.environ.get(binding["token_env"], "")
    if len(token) < 32:
        raise AgentConfigurationError("SOP_EXECUTOR_GUARD_CREDENTIAL_MISSING")
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        response = await client.request("GET" if payload is None else "POST", binding["url"].rstrip("/") + path,
            headers={"Authorization": "Bearer " + token}, json=payload)
        if response.status_code != 200:
            raise AgentConfigurationError("SOP_EXECUTOR_GUARD_REJECTED")
        return response.json()


async def apply_dsh_policy(request, session_id):
    policy = request.provider_options.get("execution_policy")
    if policy is None:
        return
    binding = request.provider_options.get("guard_control")
    receipt = await guard_request(binding, "/policy", {"session_id": session_id, **policy})
    if receipt.get("policy_epoch") != policy["policy_epoch"] or receipt.get("dispatch_ticket") != policy["dispatch_ticket"] or receipt.get("session_id") != session_id:
        raise AgentConfigurationError("SOP_EXECUTOR_POLICY_ACK_MISMATCH")
