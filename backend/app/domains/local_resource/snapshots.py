"""Opaque checkpoint locators route undo to the task's bound resource host."""
import base64
from urllib.parse import urlsplit
from app.core.offload import run_file_job
from app.domains.local_resource.client import ResourceClient
from app.domains.local_resource.service import task_profile

PREFIX = "resource-checkpoint://"


def encode(task_id, path):
    return PREFIX + task_id + "/" + base64.urlsafe_b64encode(path.encode()).decode()


def decode(locator):
    parsed = urlsplit(locator.replace("\\", "/"))
    encoded, _, suffix = parsed.path.lstrip("/").partition("/")
    path = base64.urlsafe_b64decode(encoded).decode()
    if suffix:
        path = path.rstrip("/\\") + "/" + suffix
    return parsed.netloc, path


def _call(task_id, payload):
    config = task_profile(task_id)
    return ResourceClient(config).operation(task_id, "snapshot", payload)


async def create(task_id, provider, session_id):
    result = await run_file_job(_call, task_id, {"action": "create", "provider": provider, "session_id": session_id})
    result["root"] = encode(task_id, result["root"])
    return result


async def action(locator, action, **kwargs):
    task_id, path = decode(locator)
    if kwargs.get("backup_path", "").startswith(PREFIX):
        _, kwargs["backup_path"] = decode(kwargs["backup_path"])
    return await run_file_job(_call, task_id, {"action": action, "checkpoint_root": path, **kwargs})
