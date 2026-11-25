from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.workspace_canvas.quarter_calendar import FiscalQuarter, QuarterKey

CanvasId = Annotated[str, Field(pattern=r"^[\w-]{1,64}$")]
SourceId = Annotated[str, Field(pattern=r"^[\w-]{1,36}$")]
WORLD_LIMIT = 1_000_000_000
Coordinate = Annotated[float, Field(ge=-WORLD_LIMIT, le=WORLD_LIMIT, allow_inf_nan=False)]
Dimension = Annotated[float, Field(ge=48, le=20_000)]
CanvasText = Annotated[str, Field(max_length=4_000)]
CanvasColor = Literal["yellow", "mint", "blue", "lilac", "rose"]
SourceKind = Literal["requirement", "task", "case", "playbook", "document", "requirement_document", "plan_document"]
RelationType = Literal[
    "COVERS",
    "RELATES_TO",
    "DOCUMENT_TASK",
    "DOCUMENT_REQUIREMENT",
    "CASE_TASK",
    "CASE_PROMOTION",
    "CASE_PLAYBOOK",
    "TASK_PLAYBOOK",
    "SUB_REQUIREMENT",
    "PREREQUISITE",
]


class CanvasModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObjectReference(CanvasModel):
    kind: Literal["requirement", "task", "case", "playbook"]
    id: SourceId


class LegacyEndpointReference(CanvasModel):
    # Older layouts may contain API Mock cards and arrows attached to them.
    kind: Literal["endpoint"] = "endpoint"
    id: SourceId
    method: Annotated[str, Field(pattern=r"^[A-Z]{1,16}$")]
    path: Annotated[str, Field(min_length=1, max_length=800)]


class DocumentReference(CanvasModel):
    kind: Literal["document"] = "document"
    id: SourceId
    version_id: SourceId | None = None
    block: CanvasId | None = None

    @model_validator(mode="after")
    def require_version_for_paragraph(self):
        if self.block and not self.version_id:
            raise ValueError("Document paragraphs must specify a version")
        return self


class PlanDocumentReference(CanvasModel):
    kind: Literal["plan_document"] = "plan_document"
    id: SourceId
    section: Literal["plans", "specs"]
    path: Annotated[str, Field(min_length=1, max_length=1_500)]
    block: CanvasId | None = None


class RequirementDocumentReference(CanvasModel):
    kind: Literal["requirement_document"] = "requirement_document"
    id: SourceId
    block: CanvasId | None = None


SourceReference = Annotated[
    ObjectReference | DocumentReference | PlanDocumentReference | RequirementDocumentReference,
    Field(discriminator="kind"),
]
StoredSourceReference = Annotated[
    ObjectReference
    | DocumentReference
    | PlanDocumentReference
    | RequirementDocumentReference
    | LegacyEndpointReference,
    Field(discriminator="kind"),
]
DocumentSource = Annotated[
    DocumentReference | PlanDocumentReference | RequirementDocumentReference, Field(discriminator="kind")
]


class SourceDetails(CanvasModel):
    title: str
    detail: str | None = None
    context: str | None = None
    status: str | None = None
    version: int | None = None
    historical: bool = False
    task_id: str | None = None
    task_type: str | None = None
    created_at: datetime | None = None
    has_children: bool = False
    parent_requirement_id: SourceId | None = None


class SourceItem(CanvasModel):
    reference: SourceReference
    details: SourceDetails


class CanvasAsset(SourceItem):
    node_id: CanvasId
    quarter: "AssetQuarter | None" = None
    has_related: bool | None = None


class AssetQuarter(CanvasModel):
    id: QuarterKey
    label_year: int
    number: int


class PlanFilesPage(CanvasModel):
    items: list[CanvasAsset]
    next_cursor: str | None


class SourcePage(CanvasModel):
    items: list[SourceItem]
    has_more: bool


class CanvasPosition(CanvasModel):
    x: Coordinate
    y: Coordinate


class CanvasSize(CanvasModel):
    width: Dimension
    height: Dimension


class CanvasNode(CanvasModel):
    id: CanvasId
    kind: Literal["card", "note", "frame"]
    position: CanvasPosition
    size: CanvasSize
    text: CanvasText = ""
    color: CanvasColor = "yellow"
    reference: StoredSourceReference | None = None
    scope_id: Annotated[str, Field(pattern=r"^(asset-[a-f0-9]{32}|quarter-[1-9]\d{3}-Q[1-4])$")] | None = None

    @model_validator(mode="after")
    def validate_kind(self):
        if (self.kind == "card") != (self.reference is not None):
            raise ValueError("Only source cards have a source reference")
        if self.kind == "card" and self.text:
            raise ValueError("Source cards use the original object's text")
        return self


class CanvasNodeView(CanvasNode):
    reference: SourceReference | None = None
    details: SourceDetails | None = None


class CanvasEdge(CanvasModel):
    id: CanvasId
    source: CanvasId
    target: CanvasId


class CanvasSettings(CanvasModel):
    show_status: bool = True
    show_previews: bool = True
    show_relations: bool = True


class CanvasContents(CanvasModel):
    nodes: dict[str, CanvasNode] = Field(default_factory=dict)
    edges: dict[str, CanvasEdge] = Field(default_factory=dict)
    # Existing boards can have workspace display settings from the earlier UI.
    settings: CanvasSettings = Field(default_factory=CanvasSettings)
    recent_operations: list[str] = Field(default_factory=list)


class CanvasAccess(CanvasModel):
    source_kinds: list[SourceKind]
    can_link_requirements: bool


class CanvasRelation(CanvasModel):
    source: SourceReference
    target: SourceReference
    relation_type: RelationType
    link_id: SourceId | None = None


class CanvasAssetWindow(CanvasModel):
    assets: list[CanvasAsset]
    relations: list[CanvasRelation]
    next_cursor: str | None = None


BranchKind = Literal["requirements", "requirement_tasks", "cross_quarter", "standalone", "knowledge"]
RequirementLinkType = Literal["COVERS", "RELATES_TO"]
SliceKey = Annotated[str, Field(pattern=r"^[MW][1-9][0-9]{0,2}$")]
RootKind = Literal["requirement", "task", "case", "playbook", "document", "requirement_document"]


class CanvasRootQuery(CanvasModel):
    quarter: QuarterKey
    kind: RootKind | None = None
    slice: SliceKey | None = None
    task_type: Literal["DEVELOPMENT", "DIAGNOSIS"] | None = None
    status: str | None = Field(default=None, max_length=48)
    creator_id: SourceId | None = None
    q: str | None = Field(default=None, max_length=120)
    cursor: str | None = Field(default=None, max_length=1024)


class CanvasBranch(CanvasModel):
    id: CanvasId
    kind: BranchKind
    count: int
    exact: bool = True
    requirement_id: SourceId | None = None
    relation_type: RequirementLinkType | None = None
    slice: SliceKey | None = None


class CanvasBranchQuery(CanvasModel):
    quarter: QuarterKey
    kind: BranchKind
    requirement_id: SourceId | None = None
    relation_type: RequirementLinkType | None = None
    slice: SliceKey | None = None
    cursor: str | None = Field(default=None, max_length=128)
    task_type: Literal["DEVELOPMENT", "DIAGNOSIS"] | None = None
    status: str | None = Field(default=None, max_length=48)
    creator_id: SourceId | None = None
    q: str | None = Field(default=None, max_length=120)
    source_kind: Literal["document", "requirement_document", "case", "playbook"] | None = None

    @model_validator(mode="after")
    def valid_anchor(self):
        linked = self.requirement_id is not None and self.relation_type is not None
        if (self.kind == "requirement_tasks") != linked:
            raise ValueError("A requirement task branch needs a requirement and relationship type")
        return self


class CanvasBranchWindow(CanvasModel):
    assets: list[CanvasAsset]
    relations: list[CanvasRelation]
    branches: list[CanvasBranch] = Field(default_factory=list)
    next_cursor: str | None = None
    loaded_count: int = 0
    root_tree: bool = False


class CanvasView(CanvasModel):
    revision: int
    assets: list[CanvasAsset]
    nodes: list[CanvasNodeView]
    edges: list[CanvasEdge]
    relations: list[CanvasRelation]
    access: CanvasAccess
    quarter: FiscalQuarter
    branches: list[CanvasBranch] = Field(default_factory=list)
    root_tree: bool = False
    root_cursor: str | None = None
    annotations_limited: bool = False


class CanvasNodePatch(CanvasModel):
    position: CanvasPosition | None = None
    size: CanvasSize | None = None
    text: CanvasText | None = None
    expected_text: CanvasText | None = None
    color: CanvasColor | None = None


class AddNode(CanvasModel):
    type: Literal["add_node"]
    node: CanvasNode


class UpdateNode(CanvasModel):
    type: Literal["update_node"]
    id: CanvasId
    patch: CanvasNodePatch


class RemoveNode(CanvasModel):
    type: Literal["remove_node"]
    id: CanvasId


class AddEdge(CanvasModel):
    type: Literal["add_edge"]
    edge: CanvasEdge


class RemoveEdge(CanvasModel):
    type: Literal["remove_edge"]
    id: CanvasId


CanvasEdit = Annotated[AddNode | UpdateNode | RemoveNode | AddEdge | RemoveEdge, Field(discriminator="type")]


class CanvasOperation(CanvasModel):
    id: CanvasId
    edit: CanvasEdit
    anchors: list[CanvasNode] = Field(default_factory=list, max_length=128)


class CanvasReceipt(CanvasModel):
    revision: int
