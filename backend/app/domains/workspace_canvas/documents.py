from collections import Counter
from hashlib import sha256

from sqlalchemy.orm import Session, load_only

from app.domains.asset.models.asset import DOCUMENT_ASSET_TYPES, SddAsset, SddAssetVersion
from app.domains.asset.services.document import repository
from app.domains.asset.services.document.markdown_blocks import markdown_to_blocks
from app.domains.asset.services.review.documents import ensure_active_version
from app.domains.task.models.task import SddTask
from app.domains.task.services.task_workspace import documents as plan_docs
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocument
from app.domains.workspace_asset.services.requirements import documents as requirement_docs
from app.domains.workspace_canvas.schemas import (
    DocumentReference,
    DocumentSource,
    PlanDocumentReference,
    RequirementDocumentReference,
    SourceDetails,
    SourceItem,
    SourcePage,
)

PAGE_SIZE = 35
LOCAL_DOCUMENT_TIMEOUT = 2.0


def excerpt(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    return (text if len(text) <= 440 else text[:439] + "…") or None


def asset_query(db: Session, workspace_id: str):
    return (
        db.query(SddAsset, SddTask.name)
        .join(SddTask, SddTask.id == SddAsset.task_id)
        .filter(
            SddAsset.workspace_id == workspace_id,
            SddTask.workspace_id == workspace_id,
            SddAsset.asset_type.in_(DOCUMENT_ASSET_TYPES),
        )
    )


def asset_details(asset: SddAsset, task_name: str, version: SddAssetVersion | None = None) -> SourceDetails:
    return SourceDetails(
        title=asset.name,
        context=task_name,
        task_id=asset.task_id,
        version=version.version_no if version else None,
        historical=bool(version and version.id != asset.active_version_id),
    )


def asset_blocks(version: SddAssetVersion) -> dict[str, str]:
    return {
        block["id"]: description
        for block in version.blocks_json or []
        if block.get("id") and (description := excerpt(block.get("text")))
    }


def plan_blocks(content: str) -> dict[str, str]:
    occurrences: Counter[str] = Counter()
    blocks: dict[str, str] = {}
    for block in markdown_to_blocks(content):
        text = block["text"]
        key = sha256(text.encode()).hexdigest()[:32]
        occurrences[key] += 1
        if description := excerpt(text):
            blocks[f"{key}-{occurrences[key]}"] = description
    return blocks


def plan_file(task: SddTask, reference: PlanDocumentReference) -> tuple[SourceDetails, dict[str, str]]:
    payload = plan_docs.read_plan_doc(
        task, section=reference.section, path=reference.path, local_timeout=LOCAL_DOCUMENT_TIMEOUT
    )
    details = SourceDetails(title=payload["name"], context=reference.path, task_id=task.id)
    return details, plan_blocks(payload["content"])


def find_task(db: Session, workspace_id: str, task_id: str) -> SddTask | None:
    return db.query(SddTask).filter_by(workspace_id=workspace_id, id=task_id).first()


def select_document_paragraphs(
    db: Session, workspace_id: str, reference: DocumentSource, keyword: str, page: int
) -> SourcePage | None:
    if isinstance(reference, RequirementDocumentReference):
        document = requirement_docs.get_document(db, workspace_id, reference.id)
        if document is None:
            return None
        details, blocks = SourceDetails(title=document.filename), plan_blocks(document.markdown)
    elif isinstance(reference, PlanDocumentReference):
        task = find_task(db, workspace_id, reference.id)
        if not task:
            return None
        details, blocks = plan_file(task, reference)
    else:
        row = asset_query(db, workspace_id).filter(SddAsset.id == reference.id).first()
        if not row:
            return None
        asset, task_name = row
        version = (
            repository.get_asset_version(db, asset.id, reference.version_id)
            if reference.version_id
            else (ensure_active_version(db, asset))
        )
        if reference.version_id and version is None:
            return None
        details = asset_details(asset, task_name, version)
        blocks = asset_blocks(version) if version else {}
        if version:
            reference = reference.model_copy(update={"version_id": version.id})

    matches = [(key, text) for key, text in blocks.items() if keyword.casefold() in text.casefold()]
    offset = (page - 1) * PAGE_SIZE
    return SourcePage(
        items=[
            SourceItem(
                reference=reference.model_copy(update={"block": key}),
                details=details.model_copy(update={"detail": text}),
            )
            for key, text in matches[offset : offset + PAGE_SIZE]
        ],
        has_more=offset + PAGE_SIZE < len(matches),
    )


def resolve_requirement_documents(
    db: Session, workspace_id: str, refs: list[RequirementDocumentReference], *, previews: bool
) -> dict[str, SourceDetails]:
    if not refs:
        return {}
    documents = {
        doc.id: doc
        for doc in requirement_docs.workspace_documents(db, workspace_id)
        .filter(SddRequirementDocument.id.in_({ref.id for ref in refs}))
        .all()
    }
    blocks_by_document: dict[str, dict[str, str]] = {}
    result = {}
    for ref in refs:
        document = documents.get(ref.id)
        if document is None:
            continue
        if ref.block:
            if document.id not in blocks_by_document:
                blocks_by_document[document.id] = plan_blocks(document.markdown)
            text = blocks_by_document[document.id].get(ref.block)
            if text is None:
                continue
        else:
            text = excerpt(document.markdown)
        result[ref.model_dump_json()] = SourceDetails(title=document.filename, detail=text if previews else None)
    return result


def resolve_assets(
    db: Session, workspace_id: str, refs: list[DocumentReference], *, previews: bool
) -> dict[str, SourceDetails]:
    if not refs:
        return {}
    assets = {
        asset.id: (asset, task_name)
        for asset, task_name in asset_query(db, workspace_id)
        .options(load_only(SddAsset.id, SddAsset.task_id, SddAsset.name, SddAsset.active_version_id))
        .filter(SddAsset.id.in_({ref.id for ref in refs}))
        .all()
    }
    version_ids = {ref.version_id or assets[ref.id][0].active_version_id for ref in refs if ref.id in assets} - {None}
    columns = [SddAssetVersion.id, SddAssetVersion.asset_id, SddAssetVersion.version_no]
    if previews or any(ref.block for ref in refs):
        columns.append(SddAssetVersion.blocks_json)
    versions = (
        {
            row.id: row
            for row in db.query(SddAssetVersion)
            .options(load_only(*columns))
            .filter(SddAssetVersion.id.in_(version_ids))
            .all()
        }
        if version_ids
        else {}
    )
    indexed_blocks: dict[str, dict[str, str]] = {}
    result = {}
    for ref in refs:
        if ref.id not in assets:
            continue
        asset, task_name = assets[ref.id]
        version = versions.get(ref.version_id or asset.active_version_id)
        if version is not None and version.asset_id != asset.id:
            version = None
        if ref.version_id and version is None:
            continue
        details = asset_details(asset, task_name, version)
        if ref.block:
            if version.id not in indexed_blocks:
                indexed_blocks[version.id] = asset_blocks(version)
            text = indexed_blocks[version.id].get(ref.block)
            if not text:
                continue
            details.detail = text if previews else None
        result[ref.model_dump_json()] = details
    return result


def resolve_plan_files(
    db: Session, workspace_id: str, refs: list[PlanDocumentReference], *, previews: bool
) -> dict[str, SourceDetails]:
    if not refs:
        return {}
    tasks = {
        task.id: task
        for task in db.query(SddTask)
        .filter(SddTask.workspace_id == workspace_id, SddTask.id.in_({ref.id for ref in refs}))
        .all()
    }
    files: dict[tuple[str, str, str], tuple[SourceDetails, dict[str, str]] | None] = {}
    result = {}
    for ref in refs:
        task = tasks.get(ref.id)
        if task is None:
            continue
        key = (ref.id, ref.section, ref.path)
        if key not in files:
            try:
                files[key] = plan_file(task, ref)
            except (ValueError, OSError):
                files[key] = None
        if (found := files[key]) is None:
            continue
        details, blocks = found
        text = blocks.get(ref.block) if ref.block else None
        result[ref.model_dump_json()] = details.model_copy(
            update={
                "detail": text if previews else None,
                "status": "EXCERPT_CHANGED" if ref.block and text is None else None,
            }
        )
    return result
