from dataclasses import dataclass
from json import dumps

from fastapi import HTTPException
from sqlalchemy import Text, case, cast, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.auth.models.user import WorkspacePermission, WorkspaceRole
from app.domains.workspace.services import workspace_service
from app.domains.workspace_canvas import quarters, sources
from app.domains.workspace_canvas.models import WorkspaceCanvas
from app.domains.workspace_canvas.quarter_calendar import FiscalCalendar, FiscalQuarter
from app.domains.workspace_canvas.schemas import (
    WORLD_LIMIT,
    AddEdge,
    AddNode,
    CanvasAccess,
    CanvasContents,
    CanvasEdge,
    CanvasNode,
    CanvasNodePatch,
    CanvasNodeView,
    CanvasOperation,
    CanvasPosition,
    CanvasReceipt,
    CanvasView,
    RemoveEdge,
    RemoveNode,
    SourceKind,
    UpdateNode,
)

MAX_ANNOTATION_BYTES = 512 * 1024
MAX_ANNOTATION_NODES = 256
MAX_ANNOTATION_EDGES = 512


@dataclass(frozen=True)
class CanvasMember:
    access: CanvasAccess
    can_edit_calendar: bool

    def can_view_node(self, node: CanvasNode) -> bool:
        return node.reference is None or node.reference.kind in self.access.source_kinds


def require_member(db: Session, workspace_id: str, user_id: str) -> CanvasMember:
    member = workspace_service.get_workspace_member(db, workspace_id, user_id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    permissions = workspace_service.get_user_permissions(db, workspace_id, user_id)
    kinds: list[SourceKind] = ["case", "playbook"]
    can_view_assets = WorkspacePermission.VIEW_ASSETS in permissions
    if can_view_assets:
        kinds.extend(("requirement", "task", "document", "requirement_document", "plan_document"))
    return CanvasMember(
        access=CanvasAccess(
            source_kinds=kinds,
            can_link_requirements=can_view_assets and WorkspacePermission.MANAGE_REQUIREMENTS in permissions,
        ),
        can_edit_calendar=member.role == WorkspaceRole.OWNER,
    )


def contents_of(row: WorkspaceCanvas | None) -> CanvasContents:
    return CanvasContents.model_validate(row.contents) if row else CanvasContents()


def contents_size(db: Session):
    value = cast(WorkspaceCanvas.contents, Text)
    return func.octet_length(value) if db.get_bind().dialect.name == "postgresql" else func.length(value)


def read_canvas(
    db: Session, workspace_id: str, member: CanvasMember, calendar: FiscalCalendar, period: FiscalQuarter
) -> CanvasView:
    row = (
        db.query(
            WorkspaceCanvas.revision,
            case((contents_size(db) <= MAX_ANNOTATION_BYTES, WorkspaceCanvas.contents), else_=None),
        )
        .filter_by(workspace_id=workspace_id)
        .first()
    )
    contents = CanvasContents.model_validate(row[1]) if row and row[1] is not None else CanvasContents()
    visible = {
        node.id: node
        for node in contents.nodes.values()
        if member.can_view_node(node)
        and (not (node.scope_id or "").startswith("quarter-") or node.scope_id == f"quarter-{period.id}")
    }
    content = quarters.read_quarter(db, workspace_id, member.access.source_kinds, calendar, period)
    assets = content.assets
    visible = dict(list(visible.items())[:MAX_ANNOTATION_NODES])
    resolved = {asset.reference.model_dump_json(): asset.details for asset in assets}
    refs = [
        node.reference
        for node in visible.values()
        if node.reference is not None and node.reference.model_dump_json() not in resolved
    ]
    if refs:
        resolved.update(
            sources.resolve_sources(
                db, workspace_id, list({ref.model_dump_json(): ref for ref in refs}.values())[:16], previews=True
            )
        )
    return CanvasView(
        revision=row[0] if row else 0,
        assets=assets,
        nodes=[
            CanvasNodeView(
                **node.model_dump(), details=resolved.get(node.reference.model_dump_json()) if node.reference else None
            )
            for node in visible.values()
        ],
        edges=[edge for edge in contents.edges.values() if edge.source in visible and edge.target in visible][
            :MAX_ANNOTATION_EDGES
        ],
        relations=content.relations,
        access=member.access,
        quarter=period,
        root_tree=content.next_cursor is not None,
        root_cursor=content.next_cursor,
        root_ids=content.root_ids,
        preview_children=content.preview_children,
        annotations_limited=(
            bool(row and row[1] is None)
            or len(contents.nodes) > MAX_ANNOTATION_NODES
            or len(contents.edges) > MAX_ANNOTATION_EDGES
        ),
    )


def _lock_canvas(db: Session, workspace_id: str) -> WorkspaceCanvas:
    query = db.query(WorkspaceCanvas).filter(
        WorkspaceCanvas.workspace_id == workspace_id, contents_size(db) <= MAX_ANNOTATION_BYTES
    )
    row = query.populate_existing().with_for_update().first()
    if row is not None:
        return row
    if db.query(WorkspaceCanvas.revision).filter_by(workspace_id=workspace_id).first():
        raise HTTPException(409, "CANVAS_ANNOTATION_LIMIT")
    try:
        with db.begin_nested():
            created = WorkspaceCanvas(workspace_id=workspace_id, revision=0, contents={})
            db.add(created)
            db.flush()
        return created
    except IntegrityError:
        current = query.populate_existing().with_for_update().first()
        if current is None:
            raise HTTPException(409, "CANVAS_ANNOTATION_LIMIT") from None
        return current


def _containing_frame(node: CanvasNode, frames: list[CanvasNode]) -> CanvasNode | None:
    x = node.position.x + node.size.width / 2
    y = node.position.y + node.size.height / 2
    return next(
        (
            frame
            for frame in frames
            if (
                frame.position.x <= x <= frame.position.x + frame.size.width
                and frame.position.y <= y <= frame.position.y + frame.size.height
            )
        ),
        None,
    )


def _ordered_frames(contents: CanvasContents, scope_id: str | None) -> list[CanvasNode]:
    return sorted(
        (node for node in contents.nodes.values() if node.kind == "frame" and node.scope_id == scope_id),
        key=lambda node: (node.size.width * node.size.height, node.id),
    )


def _move_frame(contents: CanvasContents, frame: CanvasNode, target: CanvasPosition, member: CanvasMember) -> None:
    dx = target.x - frame.position.x
    dy = target.y - frame.position.y
    frames = _ordered_frames(contents, frame.scope_id)
    for node in contents.nodes.values():
        if (
            node.kind != "frame"
            and node.scope_id == frame.scope_id
            and member.can_view_node(node)
            and _containing_frame(node, frames) is frame
        ):
            node.position = CanvasPosition(
                x=max(-WORLD_LIMIT, min(WORLD_LIMIT, node.position.x + dx)),
                y=max(-WORLD_LIMIT, min(WORLD_LIMIT, node.position.y + dy)),
            )


def _need_node(contents: CanvasContents, node_id: str, member: CanvasMember) -> CanvasNode:
    node = contents.nodes.get(node_id)
    if node is None or not member.can_view_node(node):
        raise HTTPException(status_code=409, detail="This canvas item is no longer available")
    return node


def _update_node(contents: CanvasContents, node: CanvasNode, patch: CanvasNodePatch, member: CanvasMember) -> None:
    if patch.position is not None:
        if node.kind == "frame" and node.position != patch.position:
            _move_frame(contents, node, patch.position, member)
        node.position = patch.position
    if patch.size is not None:
        node.size = patch.size
    if patch.text is not None and node.kind != "card":
        if patch.expected_text is not None and node.text not in {patch.expected_text, patch.text}:
            raise HTTPException(status_code=409, detail="CANVAS_TEXT_CHANGED")
        node.text = patch.text
    if patch.color is not None and node.kind != "card":
        node.color = patch.color


def _add_edge(contents: CanvasContents, edge: CanvasEdge, member: CanvasMember) -> None:
    _need_node(contents, edge.source, member)
    _need_node(contents, edge.target, member)
    if edge.source == edge.target:
        raise HTTPException(status_code=422, detail="An arrow needs two different items")
    if any(link.source == edge.source and link.target == edge.target for link in contents.edges.values()):
        return
    contents.edges.setdefault(edge.id, edge)


def _apply_operation(contents: CanvasContents, operation: CanvasOperation, member: CanvasMember) -> None:
    edit = operation.edit
    if isinstance(edit, AddNode):
        contents.nodes.setdefault(edit.node.id, edit.node)
    elif isinstance(edit, UpdateNode):
        _update_node(contents, _need_node(contents, edit.id, member), edit.patch, member)
    elif isinstance(edit, RemoveNode):
        if edit.id in contents.nodes:
            _need_node(contents, edit.id, member)
            del contents.nodes[edit.id]
            contents.edges = {
                key: edge for key, edge in contents.edges.items() if edit.id not in (edge.source, edge.target)
            }
    elif isinstance(edit, AddEdge):
        _add_edge(contents, edit.edge, member)
    elif isinstance(edit, RemoveEdge) and edit.id in contents.edges:
        edge = contents.edges[edit.id]
        _need_node(contents, edge.source, member)
        _need_node(contents, edge.target, member)
        del contents.edges[edit.id]


def _store(row: WorkspaceCanvas, contents: CanvasContents) -> None:
    value = contents.model_dump(mode="json")
    if (
        len(contents.nodes) > MAX_ANNOTATION_NODES
        or len(contents.edges) > MAX_ANNOTATION_EDGES
        or len(dumps(value).encode()) > MAX_ANNOTATION_BYTES
    ):
        raise HTTPException(409, "CANVAS_ANNOTATION_LIMIT")
    row.revision += 1
    row.contents = value


def _validate_source_nodes(db: Session, workspace_id: str, member: CanvasMember, operation: CanvasOperation) -> None:
    nodes = list(operation.anchors)
    if nodes and not isinstance(operation.edit, (AddEdge, UpdateNode)):
        raise HTTPException(status_code=422, detail="This operation does not accept asset anchors")
    for node in nodes:
        if node.reference is None or node.id != sources.catalog_node_id(node.reference, node.scope_id):
            raise HTTPException(status_code=422, detail="Invalid asset anchor")
    if isinstance(operation.edit, AddNode):
        nodes.append(operation.edit.node)
    references = [node.reference for node in nodes if node.reference is not None]
    if not references:
        return
    if any(ref.kind not in member.access.source_kinds for ref in references):
        raise HTTPException(status_code=403, detail="No permission to view this canvas source")
    resolved = sources.resolve_sources(db, workspace_id, references, previews=False)
    for ref in references:
        details = resolved.get(ref.model_dump_json())
        if details is None or details.status == "EXCERPT_CHANGED":
            raise HTTPException(status_code=404, detail="This canvas source is no longer available")


def _attach_anchors(contents: CanvasContents, operation: CanvasOperation) -> None:
    if not operation.anchors:
        return
    edit = operation.edit
    if isinstance(edit, AddEdge):
        candidates = [node for node in operation.anchors if node.id in (edit.edge.source, edit.edge.target)]
    elif isinstance(edit, UpdateNode):
        frame = contents.nodes.get(edit.id)
        frames = _ordered_frames(contents, frame.scope_id) if frame and frame.kind == "frame" else []
        candidates = [
            node
            for node in operation.anchors
            if node.id == edit.id
            or (frames and node.scope_id == frame.scope_id and _containing_frame(node, frames) is frame)
        ]
    else:
        return
    for node in candidates:
        contents.nodes.setdefault(node.id, node)


def submit_operation(db: Session, workspace_id: str, actor_id: str, operation: CanvasOperation) -> CanvasReceipt:
    member = require_member(db, workspace_id, actor_id)
    operation_key = f"{actor_id}:{operation.id}"
    latest = (
        db.query(WorkspaceCanvas)
        .filter(WorkspaceCanvas.workspace_id == workspace_id, contents_size(db) <= MAX_ANNOTATION_BYTES)
        .first()
    )
    if latest and operation_key in contents_of(latest).recent_operations:
        return CanvasReceipt(revision=latest.revision)

    _validate_source_nodes(db, workspace_id, member, operation)
    row = _lock_canvas(db, workspace_id)
    contents = contents_of(row)
    if operation_key not in contents.recent_operations:
        _attach_anchors(contents, operation)
        _apply_operation(contents, operation, member)
        contents.recent_operations = [*contents.recent_operations[-255:], operation_key]
        _store(row, contents)
    return CanvasReceipt(revision=row.revision)
