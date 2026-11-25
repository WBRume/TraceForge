from collections.abc import Collection
from hashlib import sha256

from sqlalchemy import func, literal, or_
from sqlalchemy.orm import Session, aliased, joinedload

from app.domains.asset.models.asset import SddAsset, SddAssetVersion
from app.domains.auth.models.user import Workspace
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import PlaybookSpec
from app.domains.task.models.task import SddTask
from app.domains.task.services.task_workspace import documents as task_documents
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocument
from app.domains.workspace_asset.models.workspace_asset import SddRequirement
from app.domains.workspace_asset.services.requirements import documents as requirement_docs
from app.domains.workspace_canvas import documents
from app.domains.workspace_canvas.quarter_calendar import FiscalCalendar
from app.domains.workspace_canvas.schemas import (
    AssetQuarter,
    CanvasAsset,
    DocumentReference,
    ObjectReference,
    PlanDocumentReference,
    PlanFilesPage,
    RequirementDocumentReference,
    SourceDetails,
    SourceItem,
    SourceKind,
    SourceReference,
)

OBJECT_MODELS = {
    "requirement": (SddRequirement, SddRequirement.title, SddRequirement.body),
    "task": (SddTask, SddTask.name, SddTask.description),
    "case": (SddCase, SddCase.title, SddCase.problem_description),
}
PLAN_TASKS_PER_PAGE = 6
PLAN_FILES_PER_TASK = 24


def _object_query(db: Session, workspace_id: str, kind: SourceKind):
    model, title, description = OBJECT_MODELS[kind]
    task_type = SddTask.task_type if kind == "task" else literal(None)
    parent_id, has_children = literal(None), literal(False)
    if kind == "requirement":
        child = aliased(SddRequirement)
        parent_id = SddRequirement.parent_requirement_id
        has_children = (
            db.query(child.id)
            .filter(child.workspace_id == workspace_id, child.parent_requirement_id == SddRequirement.id)
            .exists()
        )
    return db.query(
        model.id,
        title,
        model.status,
        func.substr(description, 1, 600),
        task_type,
        model.created_at,
        parent_id,
        has_children,
    ).filter(model.workspace_id == workspace_id)


def _source_item(kind: SourceKind, row, *, previews: bool = True) -> SourceItem:
    source_id, title, status, text, task_type, created_at, parent_id, has_children = row
    return SourceItem(
        reference=ObjectReference(kind=kind, id=source_id),
        details=SourceDetails(
            title=title,
            status=status,
            task_type=task_type,
            created_at=created_at,
            parent_requirement_id=parent_id,
            has_children=bool(has_children),
            detail=documents.excerpt(text) if previews else None,
        ),
    )


def _playbook_query(db: Session, workspace_id: str):
    spec = PlaybookSpec.spec_json["spec"]
    return db.query(
        PlaybookSpec.id,
        PlaybookSpec.spec_key,
        PlaybookSpec.version,
        PlaybookSpec.validation_state,
        spec["metadata"]["title"].as_string(),
        func.substr(spec["context"]["summary"].as_string(), 1, 600),
        PlaybookSpec.created_at,
    ).filter(PlaybookSpec.workspace_id == workspace_id)


def _playbook_item(row, *, previews: bool = True) -> SourceItem:
    spec_id, key, version, status, title, summary, created_at = row
    return SourceItem(
        reference=ObjectReference(kind="playbook", id=spec_id),
        details=SourceDetails(
            title=title or key,
            context=version,
            status=status,
            detail=documents.excerpt(summary) if previews else None,
            created_at=created_at,
        ),
    )


def catalog_node_id(reference: SourceReference, scope_id: str | None = None) -> str:
    identifier = sha256(reference.model_dump_json().encode()).hexdigest()[:32]
    return f"asset-{scope_id[-26:]}-{identifier[-26:]}" if scope_id else f"asset-{identifier}"


def _canvas_asset(item: SourceItem) -> CanvasAsset:
    return CanvasAsset(node_id=catalog_node_id(item.reference), reference=item.reference, details=item.details)


def workspace_assets(
    db: Session,
    workspace_id: str,
    kinds: Collection[SourceKind],
    limit: int,
    identifiers: dict[SourceKind, set[str]] | None = None,
) -> list[CanvasAsset]:
    def select(query, kind, model, total):
        if identifiers is not None:
            query = query.filter(model.id.in_(identifiers.get(kind, set())))
        return query.order_by(model.created_at, model.id).limit(limit - total)

    items = []
    for kind, (model, _, _) in OBJECT_MODELS.items():
        if kind in kinds:
            rows = select(_object_query(db, workspace_id, kind), kind, model, len(items))
            items.extend(_source_item(kind, row) for row in rows)
    if "playbook" in kinds:
        rows = select(_playbook_query(db, workspace_id), "playbook", PlaybookSpec, len(items))
        items.extend(_playbook_item(row) for row in rows)
    if "requirement_document" in kinds:
        doc = SddRequirementDocument
        query = requirement_docs.workspace_documents(db, workspace_id).with_entities(
            doc.id, doc.filename, func.substr(doc.markdown, 1, 600), doc.created_at
        )
        rows = select(query, "requirement_document", doc, len(items))
        items.extend(
            SourceItem(
                reference=RequirementDocumentReference(id=doc_id),
                details=SourceDetails(
                    title=filename,
                    detail=documents.excerpt(preview),
                    created_at=created_at,
                ),
            )
            for doc_id, filename, preview, created_at in rows
        )
    if "document" in kinds:
        query = (
            documents.asset_query(db, workspace_id)
            .with_entities(
                SddAsset.id,
                SddAsset.name,
                SddTask.name,
                SddAsset.task_id,
                SddAssetVersion.version_no,
                func.substr(SddAsset.content_text, 1, 600),
                SddAsset.created_at,
            )
            .outerjoin(SddAssetVersion, SddAssetVersion.id == SddAsset.active_version_id)
        )
        rows = select(query, "document", SddAsset, len(items))
        items.extend(
            SourceItem(
                reference=DocumentReference(id=asset_id),
                details=SourceDetails(
                    title=title,
                    context=task_name,
                    task_id=task_id,
                    version=version,
                    detail=documents.excerpt(preview),
                    created_at=created_at,
                ),
            )
            for asset_id, title, task_name, task_id, version, preview, created_at in rows
        )
    return [_canvas_asset(item) for item in items]


def assign_quarters(assets: list[CanvasAsset], calendar: FiscalCalendar) -> list[CanvasAsset]:
    for asset in assets:
        if asset.details.created_at is not None:
            period = calendar.at(asset.details.created_at)
            asset.quarter = AssetQuarter(id=period.id, label_year=period.label_year, number=period.number)
    return assets


def catalog_queries(db: Session, workspace_id: str, kinds: Collection[SourceKind]):
    """ID-only queries let size probes and search avoid loading asset bodies."""
    for kind, (model, title, _) in OBJECT_MODELS.items():
        if kind in kinds:
            yield kind, model, title, db.query(model.id).filter(model.workspace_id == workspace_id)
    if "playbook" in kinds:
        title = func.coalesce(PlaybookSpec.spec_json["spec"]["metadata"]["title"].as_string(), PlaybookSpec.spec_key)
        yield (
            "playbook",
            PlaybookSpec,
            title,
            db.query(PlaybookSpec.id).filter(PlaybookSpec.workspace_id == workspace_id),
        )
    if "requirement_document" in kinds:
        doc = SddRequirementDocument
        yield (
            "requirement_document",
            doc,
            doc.filename,
            requirement_docs.workspace_documents(db, workspace_id).with_entities(doc.id),
        )
    if "document" in kinds:
        yield "document", SddAsset, SddAsset.name, documents.asset_query(db, workspace_id).with_entities(SddAsset.id)


def reference_for(kind: SourceKind, identifier: str) -> SourceReference:
    if kind == "document":
        return DocumentReference(id=identifier)
    if kind == "requirement_document":
        return RequirementDocumentReference(id=identifier)
    return ObjectReference(kind=kind, id=identifier)


def visible_references(tokens, kinds) -> list[SourceReference]:
    references = []
    for token in tokens or ():
        kind, _, identifier = token.partition(":")
        if kind in kinds:
            references.append(reference_for(kind, identifier))
    return references


def assets_for_references(db: Session, workspace_id: str, references: Collection[SourceReference]) -> list[CanvasAsset]:
    identifiers = {}
    for ref in references:
        identifiers.setdefault(ref.kind, set()).add(ref.id)
    return workspace_assets(db, workspace_id, identifiers.keys(), len(references), identifiers)


def workspace_plan_files(
    db: Session,
    workspace_id: str,
    cursor: str | None,
    task_ids: list[str] | None = None,
) -> PlanFilesPage:
    if not task_ids:
        return PlanFilesPage(items=[], next_cursor=None)
    workspace = db.get(Workspace, workspace_id)
    if not workspace or not workspace.plan_doc_roots:
        return PlanFilesPage(items=[], next_cursor=None)
    query = (
        db.query(SddTask)
        .options(joinedload(SddTask.workspace))
        .filter(
            SddTask.workspace_id == workspace_id,
            SddTask.id.in_(task_ids),
            SddTask.task_meta_json["initial_workspace_checkpoint"].as_string().is_not(None),
            or_(SddTask.project_path.is_not(None), SddTask.execution_location == "LOCAL"),
        )
    )
    if cursor:
        query = query.filter(SddTask.id > cursor)
    tasks = query.order_by(SddTask.id).limit(PLAN_TASKS_PER_PAGE + 1).all()
    items: list[CanvasAsset] = []
    for task in tasks[:PLAN_TASKS_PER_PAGE]:
        try:
            payload = task_documents.list_plan_docs(task, local_timeout=documents.LOCAL_DOCUMENT_TIMEOUT)
        except (OSError, ValueError):
            continue
        for file in [*payload["plans"][:PLAN_FILES_PER_TASK], *payload["specs"][:PLAN_FILES_PER_TASK]][
            :PLAN_FILES_PER_TASK
        ]:
            path = file["section_path"]
            items.append(
                _canvas_asset(
                    SourceItem(
                        reference=PlanDocumentReference(id=task.id, section=file["section"], path=path),
                        details=SourceDetails(title=file["name"], context=path, task_id=task.id),
                    )
                )
            )
    next_cursor = tasks[PLAN_TASKS_PER_PAGE - 1].id if len(tasks) > PLAN_TASKS_PER_PAGE else None
    return PlanFilesPage(items=items, next_cursor=next_cursor)


def resolve_sources(
    db: Session, workspace_id: str, references: Collection[SourceReference], *, previews: bool
) -> dict[str, SourceDetails]:
    result = documents.resolve_assets(
        db, workspace_id, [ref for ref in references if isinstance(ref, DocumentReference)], previews=previews
    )
    result.update(
        documents.resolve_plan_files(
            db, workspace_id, [ref for ref in references if isinstance(ref, PlanDocumentReference)], previews=previews
        )
    )
    result.update(
        documents.resolve_requirement_documents(
            db,
            workspace_id,
            [ref for ref in references if isinstance(ref, RequirementDocumentReference)],
            previews=previews,
        )
    )
    playbook_ids = {ref.id for ref in references if ref.kind == "playbook"}
    if playbook_ids:
        for row in _playbook_query(db, workspace_id).filter(PlaybookSpec.id.in_(playbook_ids)).all():
            item = _playbook_item(row, previews=previews)
            result[item.reference.model_dump_json()] = item.details
    for kind in OBJECT_MODELS:
        ids = {ref.id for ref in references if ref.kind == kind}
        if ids:
            model, *_ = OBJECT_MODELS[kind]
            for row in _object_query(db, workspace_id, kind).filter(model.id.in_(ids)).all():
                item = _source_item(kind, row, previews=previews)
                result[item.reference.model_dump_json()] = item.details
    return result
