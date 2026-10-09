"""Task-directory boundaries for OpenCode session permissions."""

import ntpath
import posixpath

from app.agents.errors import AgentError


def normalize_directory(directory: str) -> str:
    """Normalize a provider-host path without resolving it on the API host."""
    value = directory.strip().replace("\\", "/")
    if value.startswith("//?/UNC/"):
        value = "//" + value[8:]
    elif value.startswith("//?/"):
        value = value[4:]
    drive, tail = ntpath.splitdrive(value)
    if (
        not value
        or any(char in value for char in "*?\x00\n\r")
        or (drive and not tail.startswith("/"))
        or (not drive and not value.startswith("/"))
    ):
        raise AgentError("OpenCode task directory must be an absolute path without wildcard characters")
    normalized = ntpath.normpath(value).replace("\\", "/") if drive else posixpath.normpath(value)
    if normalized in {"/", "//"} or (drive and normalized.rstrip("/") == drive):
        raise AgentError("OpenCode task directory cannot be a filesystem root")
    return normalized.rstrip("/")


def same_directory(first: str, second: str) -> bool:
    first, second = normalize_directory(first), normalize_directory(second)
    if ntpath.splitdrive(first)[0] or ntpath.splitdrive(second)[0]:
        return first.casefold() == second.casefold()
    return first == second


def workspace_permissions(directory: str) -> list[dict[str, str]]:
    """Restrict directory access while retaining existing in-task tool permissions."""
    root = normalize_directory(directory)
    rules = [
        {"action": "external_directory", "resource": "*", "effect": "deny"},
        {"action": "external_directory", "resource": root + "/*", "effect": "allow"},
    ]
    # OpenCode also treats the enclosing Git worktree as internal. Its paths
    # outside the session directory are normalized to ../ relative resources.
    rules.extend(
        {"action": action, "resource": resource, "effect": "deny"}
        for action in ("read", "edit")
        for resource in ("..", "../*")
    )
    return rules
