"""Strong contracts for business artifacts; JSON is allowed only where it is domain data."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domains.task.schemas.diagnosis import DiagnosisResultPayload

Text = Annotated[str, Field(min_length=1, max_length=100000)]


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DiagnosisSubmission(DiagnosisResultPayload):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: Text
    root_cause: Text
    evidence_chain: Text
    fix_suggestion: Text


class ReviewProposal(Artifact):
    analysis: Text
    rationale: Text
    proposal_text: Text


class DocumentRewrite(Artifact):
    scope: Literal["anchor", "document"]
    anchor_text: str = Field(default="", max_length=100000)
    document_markdown: str = Field(default="", max_length=1000000)
    change_summary: Text

    @model_validator(mode="after")
    def scope_matches_content(self):
        if self.scope == "anchor" and (not self.anchor_text or self.document_markdown):
            raise ValueError("anchor scope requires only anchor_text")
        if self.scope == "document" and (not self.document_markdown or self.anchor_text):
            raise ValueError("document scope requires only document_markdown")
        return self


class RequirementSource(Artifact):
    split_reason: str = ""
    functional_area: str = ""


class RequirementDraft(Artifact):
    title: str = Field(min_length=1, max_length=300)
    body: Text
    acceptance_criteria: list[Text]
    priority: Literal["P0", "P1", "P2", "P3"] | None = None
    source_ref: str | None = Field(default=None, max_length=300)
    source_metadata: RequirementSource = Field(default_factory=RequirementSource)
    task_prompt: Text


class RequirementSubmission(Artifact):
    items: list[RequirementDraft] = Field(min_length=1, max_length=100)


class MockCase(Artifact):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    mode: Literal["STATIC", "MOCKJS"]
    status_code: int = Field(ge=100, le=599)
    delay_ms: int = Field(default=0, ge=0, le=60000)
    headers_json: dict[str, str] = Field(default_factory=dict)
    request_path_params_json: dict[str, JsonValue] | None = None
    request_query_json: dict[str, JsonValue] | None = None
    request_body_json: JsonValue = None
    static_body_json: JsonValue = None
    mockjs_template: str | None = None

    @model_validator(mode="after")
    def mode_matches_body(self):
        if self.mode == "MOCKJS" and (not self.mockjs_template or self.static_body_json is not None):
            raise ValueError("MOCKJS requires mockjs_template and no static_body_json")
        if self.mode == "STATIC" and self.mockjs_template:
            raise ValueError("STATIC does not accept mockjs_template")
        return self


class MockSubmission(Artifact):
    cases: list[MockCase] = Field(min_length=1, max_length=50)


class OpenAPISubmission(Artifact):
    # OpenAPI and JSON Schema contain extensible keyword dictionaries. They are
    # checked against the official schema by the tool's domain validator.
    document: dict[str, JsonValue]


Level = Literal["LOW", "MEDIUM", "HIGH"]


class SkillRisk(Artifact):
    risk_type: Text
    risk_level: Level
    file_path: Text
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    title: Text
    description: Text
    evidence_summary: Text
    evidence_detail: Text
    matched_text: str = ""
    recommendation: Text
    confidence: float = Field(ge=0, le=1)


class SkillReview(Artifact):
    risk_level: Level
    complexity: Level
    review_priority: Level
    risk_items: list[SkillRisk] = Field(max_length=300)
    review_suggestions: list[Text]

    @model_validator(mode="after")
    def evidence_required(self):
        if self.risk_level != "LOW" and not self.risk_items:
            raise ValueError("MEDIUM/HIGH risk requires concrete file-level evidence in risk_items")
        return self
