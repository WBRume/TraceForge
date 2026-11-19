"""Native document revision tool and review contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReplaceDocxText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["replace"]
    region_id: str = Field(min_length=1, max_length=120)
    start: int | None = Field(default=None, ge=0, description="Character offset, required for repeated matches")
    old_text: str = Field(min_length=1, max_length=20_000)
    new_text: str = Field(max_length=20_000, description="Empty text deletes the selected characters")


class AppendDocxChapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["append"]
    title: str = Field(min_length=1, max_length=500, pattern=r"^[^\r\n]+$")
    level: int = Field(default=1, ge=1, le=9)
    paragraphs: list[Annotated[str, Field(min_length=1, max_length=10_000, pattern=r"^[^\r\n]+$")]] = Field(
        min_length=1, max_length=60
    )


DocxOperation = Annotated[ReplaceDocxText | AppendDocxChapter, Field(discriminator="kind")]


class DocxRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["read", "apply"]
    query: str | None = Field(default=None, max_length=300, description="Find a literal phrase in editable regions")
    region_id: str | None = Field(default=None, max_length=120)
    changes: list[DocxOperation] = Field(default_factory=list, max_length=80)
    change_summary: str = Field(default="", max_length=6000)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "read" and (self.changes or self.change_summary):
            raise ValueError("Read accepts only a query or region_id")
        if self.action == "apply" and (
            self.query is not None or self.region_id is not None or not self.change_summary.strip()
        ):
            raise ValueError("Apply accepts changes and requires a change_summary")
        return self


class EditableDocxRegion(BaseModel):
    region_id: str
    block_id: str
    text: str
    start: int
    total_characters: int
    in_table: bool


class DocxRegionsReply(BaseModel):
    kind: Literal["docx_regions"] = "docx_regions"
    regions: list[EditableDocxRegion]
    more_matches: bool


class TextSourceRewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text: str = Field(max_length=1_000_000, description="Raw source text, with its spacing and line breaks")
    change_summary: str = Field(min_length=1, max_length=6000)


class RevisionSelection(BaseModel):
    revision_id: str = Field(min_length=1, max_length=36)
    change_ids: list[str] = Field(max_length=10_000)
