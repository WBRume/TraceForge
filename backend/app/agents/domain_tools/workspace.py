"""Bounded read access to an explicitly mounted workspace; no shell or writes."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.agents.tools import AgentToolDefinition
from app.protocols.tools import WORKSPACE_REPLY

from .runtime import DomainToolError


class ReadWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default=".", max_length=1000)
    start_line: int = Field(default=1, ge=1)
    max_lines: int = Field(default=200, ge=1, le=500)


READ_TOOL = AgentToolDefinition(
    "read_workspace",
    "只读查看挂载工作区内的目录或文件。目录返回直接子项；文件按行分页，禁止读取工作区外路径。",
    ReadWorkspace.model_json_schema(),
    WORKSPACE_REPLY.json_schema(),
)


def read_workspace(root: str, arguments: dict) -> dict:
    request = ReadWorkspace.model_validate(arguments, strict=True)
    base = Path(root).resolve()
    relative = Path(request.path)
    target = (base / relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(base):
        raise DomainToolError("WORKSPACE_PATH_OUTSIDE_MOUNT")
    blocked = {".git", ".ssh", ".aws", "node_modules", ".venv", "venv"}
    if any(
        p.lower() in blocked or p.lower().startswith(".env") for p in (*relative.parts, *target.relative_to(base).parts)
    ):
        raise DomainToolError("WORKSPACE_PATH_RESTRICTED")
    if target.is_dir():
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
        return {"kind": "directory", "entries": entries[:1000], "truncated": len(entries) > 1000}
    if not target.is_file():
        raise DomainToolError("WORKSPACE_FILE_NOT_FOUND")
    if target.stat().st_size > 2_000_000:
        raise DomainToolError("WORKSPACE_FILE_TOO_LARGE")
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise DomainToolError("WORKSPACE_FILE_NOT_UTF8") from exc
    start = request.start_line - 1
    return {
        "kind": "file",
        "path": request.path,
        "start_line": request.start_line,
        "total_lines": len(lines),
        "text": "\n".join(lines[start : start + request.max_lines]),
    }
