from collections.abc import Collection
from hashlib import sha256

from sqlalchemy import func, literal, or_
from sqlalchemy.orm import Session, joinedload

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
from app.domains.workspace_canvas.schemas import (
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


def _object_query(db: Session, workspace_id: str, kind: SourceKind):
    model, title, description = OBJECT_MODELS[kind]
    task_type = SddTask.task_type if kind == "task" else literal(None)
    return db.query(model.id, title, model.status, func.substr(description, 1, 600), task_type).filter(
        model.workspace_id == workspace_id
    )


def _source_item(kind: SourceKind, row, *, previews: bool = True) -> SourceItem:
    source_id, title, status, text, task_type = row
    return SourceItem(
        reference=ObjectReference(kind=kind, id=source_id),
        details=SourceDetails(
            title=title,
            status=status,
            task_type=task_type,
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
    ).filter(PlaybookSpec.workspace_id == workspace_id)


def _playbook_item(row, *, previews: bool = True) -> SourceItem:
    spec_id, key, version, status, title, summary = row
    return SourceItem(
        reference=ObjectReference(kind="playbook", id=spec_id),
        details=SourceDetails(
            title=title or key, context=version, status=status, detail=documents.excerpt(summary) if previews else None
        ),
    )


def catalog_node_id(reference: SourceReference) -> str:
    return "asset-" + sha256(reference.model_dump_json().encode()).hexdigest()[:32]


def _canvas_asset(item: SourceItem) -> CanvasAsset:
    return CanvasAsset(node_id=catalog_node_id(item.reference), reference=item.reference, details=item.details)


def workspace_assets(db: Session, workspace_id: str, kinds: Collection[SourceKind]) -> list[CanvasAsset]:
    items = []
    for kind, (model, _, _) in OBJECT_MODELS.items():
        if kind in kinds:
            rows = _object_query(db, workspace_id, kind).order_by(model.created_at, model.id).all()
            items.extend(_source_item(kind, row) for row in rows)
    if "playbook" in kinds:
        rows = _playbook_query(db, workspace_id).order_by(PlaybookSpec.created_at, PlaybookSpec.id).all()
        items.extend(_playbook_item(row) for row in rows)
    if "requirement_document" in kinds:
        doc = SddRequirementDocument
        rows = (
            requirement_docs.workspace_documents(db, workspace_id)
            .with_entities(doc.id, doc.filename, func.substr(doc.markdown, 1, 600))
            .order_by(doc.created_at, doc.id)
            .all()
        )
        items.extend(
            SourceItem(
                reference=RequirementDocumentReference(id=doc_id),
                details=SourceDetails(
                    title=filename,
                    detail=documents.excerpt(preview),
                ),
            )
            for doc_id, filename, preview in rows
        )
    if "document" in kinds:
        rows = (
            documents.asset_query(db, workspace_id)
            .with_entities(
                SddAsset.id,
                SddAsset.name,
                SddTask.name,
                SddAsset.task_id,
                SddAssetVersion.version_no,
                func.substr(SddAsset.content_text, 1, 600),
            )
            .outerjoin(SddAssetVersion, SddAssetVersion.id == SddAsset.active_version_id)
            .order_by(SddAsset.created_at, SddAsset.id)
            .all()
        )
        items.extend(
            SourceItem(
                reference=DocumentReference(id=asset_id),
                details=SourceDetails(
                    title=title, context=task_name, task_id=task_id, version=version, detail=documents.excerpt(preview)
                ),
            )
            for asset_id, title, task_name, task_id, version, preview in rows
        )
    return [_canvas_asset(item) for item in items]


def workspace_plan_files(db: Session, workspace_id: str, cursor: str | None) -> PlanFilesPage:
    workspace = db.get(Workspace, workspace_id)
    if not workspace or not workspace.plan_doc_roots:
        return PlanFilesPage(items=[], next_cursor=None)
    query = (
        db.query(SddTask)
        .options(joinedload(SddTask.workspace))
        .filter(
            SddTask.workspace_id == workspace_id,
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
        for file in [*payload["plans"], *payload["specs"]]:
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
