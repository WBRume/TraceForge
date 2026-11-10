from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .base import Contract


class FieldIssue(Contract):
    path: list[str | int]
    code: str
    message: str


class ToolFailure(Contract):
    kind: Literal["error"] = "error"
    code: str = Field(min_length=1, max_length=100)
    category: Literal["input", "condition", "conflict", "revoked", "transient", "uncertain", "internal"]
    message: str = Field(min_length=1, max_length=2000)
    action: Literal["correct_arguments", "read_context", "stop", "query_receipt", "execution_policy", "report_defect"]
    run_id: str
    call_id: str
    diagnostic_id: str | None = None
    issues: list[FieldIssue] = Field(default_factory=list, max_length=100)


class SubmissionAccepted(Contract):
    kind: Literal["accepted"] = "accepted"
    run_id: str
    call_id: str
    receipt_id: str
    stage: Literal["accepted"] = "accepted"


class WorkspaceDirectory(Contract):
    kind: Literal["directory"] = "directory"
    entries: list[str] = Field(max_length=1000)
    truncated: bool


class WorkspaceFile(Contract):
    kind: Literal["file"] = "file"
    path: str
    start_line: int = Field(ge=1)
    total_lines: int = Field(ge=0)
    text: str


SubmissionReply = Annotated[SubmissionAccepted | ToolFailure, Field(discriminator="kind")]
WorkspaceReply = Annotated[WorkspaceDirectory | WorkspaceFile | ToolFailure, Field(discriminator="kind")]
SUBMISSION_REPLY = TypeAdapter(SubmissionReply)
WORKSPACE_REPLY = TypeAdapter(WorkspaceReply)
