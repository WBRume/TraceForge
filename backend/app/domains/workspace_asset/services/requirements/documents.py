from collections.abc import Collection

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.asset.models.asset import DOCUMENT_ASSET_TYPES, SddAsset
from app.domains.task.models.task import SddTask
from app.domains.workspace_asset.models.requirement_document import SddRequirementDocument, SddRequirementDocumentLink
from app.domains.workspace_asset.models.workspace_asset import SddRequirement


def store_document(
    db: Session,
    workspace_id: str,
    actor_id: str | None,
    requirement_ids: Collection[str],
    filename: str,
    markdown: str,
    content: bytes | None = None,
) -> SddRequirementDocument:
    document = SddRequirementDocument(
        workspace_id=workspace_id,
        creator_id=actor_id,
        filename=filename.replace("\\", "/").rsplit("/", 1)[-1][-300:],
        markdown=markdown,
        content=content,
    )
    db.add(document)
    db.flush()
    db.add_all(
        SddRequirementDocumentLink(requirement_id=requirement_id, document_id=document.id, creator_id=actor_id)
        for requirement_id in set(requirement_ids)
    )
    return document


def requirement_links(db: Session, workspace_id: str):
    return (
        db.query(SddRequirementDocumentLink)
        .join(SddRequirement, SddRequirement.id == SddRequirementDocumentLink.requirement_id)
        .filter(SddRequirement.workspace_id == workspace_id)
    )


def workspace_documents(db: Session, workspace_id: str):
    linked_document = requirement_links(db, workspace_id).filter(
        SddRequirementDocumentLink.document_id == SddRequirementDocument.id
    )
    return db.query(SddRequirementDocument).filter(
        SddRequirementDocument.workspace_id == workspace_id, linked_document.exists()
    )


def get_document(db: Session, workspace_id: str, document_id: str) -> SddRequirementDocument | None:
    return workspace_documents(db, workspace_id).filter(SddRequirementDocument.id == document_id).one_or_none()


def requirement_documents(db: Session, workspace_id: str, requirement_id: str):
    link = SddRequirementDocumentLink
    rows = (
        requirement_links(db, workspace_id)
        .with_entities(
            link.id,
            link.document_id,
            link.task_asset_id,
            SddRequirementDocument.filename,
            SddAsset.name,
            SddAsset.task_id,
        )
        .outerjoin(
            SddRequirementDocument,
            (SddRequirementDocument.id == link.document_id) & (SddRequirementDocument.workspace_id == workspace_id),
        )
        .outerjoin(SddAsset, (SddAsset.id == link.task_asset_id) & (SddAsset.workspace_id == workspace_id))
        .filter(link.requirement_id == requirement_id)
        .order_by(link.created_at, link.id)
        .all()
    )
    return [
        {
            "id": document_id or asset_id,
            "link_id": link_id,
            "name": filename or asset_name,
            "task_id": task_id,
        }
        for link_id, document_id, asset_id, filename, asset_name, task_id in rows
        if filename or asset_name
    ]


def attach_task_document(
    db: Session, workspace_id: str, requirement_id: str, asset_id: str, actor_id: str
) -> SddRequirementDocumentLink | None:
    asset = (
        db.query(SddAsset.id)
        .join(SddTask, SddTask.id == SddAsset.task_id)
        .filter(
            SddAsset.id == asset_id,
            SddAsset.workspace_id == workspace_id,
            SddTask.workspace_id == workspace_id,
            SddAsset.asset_type.in_(DOCUMENT_ASSET_TYPES),
        )
        .one_or_none()
    )
    if not asset:
        return None
    query = requirement_links(db, workspace_id).filter(
        SddRequirementDocumentLink.requirement_id == requirement_id,
        SddRequirementDocumentLink.task_asset_id == asset_id,
    )
    existing = query.one_or_none()
    if existing:
        return existing
    link = SddRequirementDocumentLink(requirement_id=requirement_id, task_asset_id=asset_id, creator_id=actor_id)
    try:
        with db.begin_nested():
            db.add(link)
            db.flush()
    except IntegrityError:
        existing = query.one_or_none()
        if existing is None:
            raise
        return existing
    return link
