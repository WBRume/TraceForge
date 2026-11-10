"""Desktop commands are discriminated before any journal or filesystem write."""

from functools import reduce
from operator import or_
from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter, create_model

from .base import Contract

Id = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
Path = Annotated[str, Field(min_length=1, max_length=2000)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class File(Contract):
    path: Path
    content: str
    sha256: Digest


class Repository(Contract):
    repository_id: Id
    local_path: Path
    configured_git_url: str
    repo_url: str
    repo_name: str
    rel_path: str
    branch_name: str


class RepositoryTarget(Contract):
    repository_id: Id
    rel_path: str
    branch: str
    target: str | None = None


class PatchRepository(Contract):
    repository_id: Id
    local_path: Path
    configured_git_url: str
    repo_slug: str
    patch: str
    sha256: Digest
    base_commit_sha: str
    base_branch: str


def variant(name, fields):
    return create_model(name, __base__=Contract, **fields)


def actions(name, variants):
    models = [
        variant(name + action.title().replace("_", ""), {"action": (Literal[action], ...), **fields})
        for action, fields in variants.items()
    ]
    return Annotated[reduce(or_, models), Field(discriminator="action")]


INITIALIZE = actions(
    "Initialize",
    {
        "clean": {"protected": (list[str], ...)},
        "fetch": {"repository": (RepositoryTarget, ...)},
        "reset": {"repository": (RepositoryTarget, ...)},
    },
)
SKILLS = actions(
    "Skills",
    {
        "replace": {"files": (list[File], ...), "preserve": (bool, False)},
        "manifest": {},
        "tree": {"folder": (Path, ...)},
        "read": {"folder": (Path, ...), "path": (Path, ...)},
        "write": {"folder": (Path, ...), "path": (Path, ...), "content": (str, ...)},
    },
)
DOCUMENTS = actions(
    "Documents",
    {
        "list": {"roots": (list[str], ...), "initial_checkpoint": (str | None, None)},
        "read": {
            "roots": (list[str], ...),
            "initial_checkpoint": (str | None, None),
            "path": (Path, ...),
            "section": (Literal["plans", "specs"], ...),
        },
        "save": {
            "roots": (list[str], ...),
            "initial_checkpoint": (str | None, None),
            "path": (Path, ...),
            "section": (Literal["plans", "specs"], ...),
            "content": (str, ...),
        },
    },
)
SNAPSHOT = actions(
    "Snapshot",
    {
        "create": {
            "provider": (Literal["opencode", "dsh"], "opencode"),
            "session_id": (str | None, None),
            "initial_checkpoint": (str | None, None),
        },
        "exists": {"checkpoint_root": (Path, ...)},
        "restore_worktree": {"checkpoint_root": (Path, ...), "backup_path": (Path, ...)},
        "backup_provider": {
            "checkpoint_root": (Path, ...),
            "provider": (Literal["opencode", "dsh"], ...),
            "session_id": (str | None, None),
        },
        "restore_provider": {"checkpoint_root": (Path, ...)},
        "restore_provider_backup": {"checkpoint_root": (Path, ...)},
        "fork_dsh": {"checkpoint_root": (Path, ...), "session_id": (Path, ...)},
        "cleanup_dsh": {"checkpoint_root": (Path, ...), "session_id": (Path, ...)},
        "cleanup": {"checkpoint_root": (Path, ...)},
    },
)
PARAMETERS = {
    "initialize": INITIALIZE,
    "skills": SKILLS,
    "documents": DOCUMENTS,
    "snapshot": SNAPSHOT,
    "provision": variant("Provision", {"workspace_root": (Path, ...), "repositories": (list[Repository], ...)}),
    "materialize": variant("Materialize", {"files": (list[File], ...)}),
    "provider_fork": variant("ProviderFork", {"session_id": (Path, ...), "drill": (bool, False)}),
    "release": Contract,
    "repository_details": Contract,
    "generate_patch": Contract,
    "apply_patch": variant("ApplyPatch", {"workspace_root": (Path, ...), "repositories": (list[PatchRepository], ...)}),
}
COMMANDS = {
    kind: variant(
        kind.title().replace("_", "") + "Command",
        {
            "contract_version": (Literal[2], ...),
            "operation_id": (Id, ...),
            "resource_id": (Id, ...),
            "task_id": (Id, ...),
            "payload_hash": (Digest, ...),
            "kind": (Literal[kind], ...),
            "payload": (payload, ...),
        },
    )
    for kind, payload in PARAMETERS.items()
}
RESOURCE_COMMAND = TypeAdapter(Annotated[reduce(or_, COMMANDS.values()), Field(discriminator="kind")])


class OperationReceipt(Contract):
    contract_version: Literal[2]
    operation_id: Id
    resource_id: Id
    task_id: Id
    kind: Literal[tuple(PARAMETERS)]
    state: Literal["RUNNING", "SUCCEEDED", "FAILED", "UNKNOWN"]
    result: JsonValue


# Result schemas belong to each operation, including the action variants. Git
# trees and provider checkpoint metadata remain JSON content, never commands.
RESOURCE_RESULTS = {
    "provision": variant(
        "Provisioned",
        {
            "task_id": (Id, ...),
            "task_root": (Path, ...),
            "repositories_input": (list[dict[str, JsonValue]], ...),
            "repositories": (list[dict[str, JsonValue]], ...),
        },
    ),
    "materialize": variant("Materialized", {"written": (int, ...), "paths": (list[str], ...)}),
    "provider_fork": variant("Forked", {"session_id": (Path, ...)}),
    "release": variant("Released", {"released": (Literal[True], ...)}),
    "repository_details": variant("RepositoryDetails", {"repositories": (list[dict[str, JsonValue]], ...)}),
    "generate_patch": variant("GeneratedPatch", {"repositories": (list[dict[str, JsonValue]], ...)}),
    "apply_patch": variant(
        "AppliedPatch",
        {"repositories": (list[dict[str, JsonValue]], ...), "status": (Literal["applied", "conflict"], ...)},
    ),
}

OK = variant("OperationOk", {"ok": (Literal[True], ...)})
TEXT_FILE = variant(
    "SkillFile", {"path": (str, ...), "content": (str | None, ...), "is_binary": (bool, ...), "size": (int, ...)}
)
RESULT_ACTIONS = {
    "initialize:clean": variant("Cleaned", {"cleaned": (Literal[True], ...)}),
    "initialize:fetch": variant("Fetched", {"target": (str, ...), "fetch_seconds": (float, ...)}),
    "initialize:reset": variant("Reset", {"completed": (Literal[True], ...), "reset_seconds": (float, ...)}),
    "skills:replace": OK,
    "skills:write": TEXT_FILE,
    "skills:read": TEXT_FILE,
    "skills:tree": variant("SkillTree", {"tree": (list[dict[str, JsonValue]], ...)}),
    "skills:manifest": variant(
        "SkillManifest", {"items": (list[dict[str, JsonValue]], ...), "folders": (list[str], ...)}
    ),
    "documents:list": variant(
        "DocumentList",
        {
            "task_id": (Id, ...),
            "root_relative_path": (str, ...),
            "configured": (bool, ...),
            "baseline_available": (bool, ...),
            "plans": (list[dict[str, JsonValue]], ...),
            "specs": (list[dict[str, JsonValue]], ...),
        },
    ),
    "snapshot:create": variant(
        "CheckpointCreated",
        {"root": (Path, ...), "worktree": (dict[str, JsonValue], ...), "provider": (dict[str, JsonValue], ...)},
    ),
    "snapshot:exists": variant("CheckpointExists", {"exists": (bool, ...)}),
    "snapshot:fork_dsh": RESOURCE_RESULTS["provider_fork"],
    **{
        f"snapshot:{action}": OK
        for action in ["restore_worktree", "restore_provider", "restore_provider_backup", "cleanup_dsh", "cleanup"]
    },
}
DOCUMENT_RESULT = variant(
    "DocumentContent",
    {
        "task_id": (Id, ...),
        "section": (Literal["plans", "specs"], ...),
        "name": (str, ...),
        "section_path": (str, ...),
        "relative_path": (str, ...),
        "size": (int, ...),
        "updated_at": (str, ...),
        "content": (str, ...),
    },
)
RESULT_ACTIONS.update({"documents:read": DOCUMENT_RESULT, "documents:save": DOCUMENT_RESULT})
# Native provider backup objects are stored content, validated by their owning
# provider when restoring. They cannot dispatch an operation on their own.
RESULT_ACTIONS["snapshot:backup_provider"] = dict[str, JsonValue]


def resource_result_key(command) -> str:
    return command.kind + (":" + command.payload.action if hasattr(command.payload, "action") else "")


def validate_resource_result(command, value):
    TypeAdapter((RESOURCE_RESULTS | RESULT_ACTIONS)[resource_result_key(command)]).validate_python(value, strict=True)
    return value
