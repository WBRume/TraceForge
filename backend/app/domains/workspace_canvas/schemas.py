from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CanvasId = Annotated[str, Field(pattern=r"^[\w-]{1,64}$")]
SourceId = Annotated[str, Field(pattern=r"^[\w-]{1,36}$")]
WORLD_LIMIT = 1_000_000_000
Coordinate = Annotated[float, Field(ge=-WORLD_LIMIT, le=WORLD_LIMIT, allow_inf_nan=False)]
Dimension = Annotated[float, Field(ge=48, le=20_000)]
CanvasText = Annotated[str, Field(max_length=4_000)]
CanvasColor = Literal["yellow", "mint", "blue", "lilac", "rose"]
SourceKind = Literal["requirement", "task", "case", "document", "plan_document"]


class CanvasModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObjectReference(CanvasModel):
    kind: Literal["requirement", "task", "case"]
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


SourceReference = Annotated[ObjectReference | DocumentReference | PlanDocumentReference, Field(discriminator="kind")]
StoredSourceReference = Annotated[
    ObjectReference | DocumentReference | PlanDocumentReference | LegacyEndpointReference, Field(discriminator="kind")
]
DocumentSource = Annotated[DocumentReference | PlanDocumentReference, Field(discriminator="kind")]


class SourceDetails(CanvasModel):
    title: str
    detail: str | None = None
    context: str | None = None
    status: str | None = None
    version: int | None = None
    historical: bool = False
    task_id: str | None = None


class SourceItem(CanvasModel):
    reference: SourceReference
    details: SourceDetails


class CanvasAsset(SourceItem):
    node_id: CanvasId


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
    requirement_id: str
    task_id: str
    relation_type: str


class CanvasView(CanvasModel):
    revision: int
    assets: list[CanvasAsset]
    nodes: list[CanvasNodeView]
    edges: list[CanvasEdge]
    relations: list[CanvasRelation]
    access: CanvasAccess


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
    anchors: list[CanvasNode] = Field(default_factory=list)


class CanvasReceipt(CanvasModel):
    revision: int
