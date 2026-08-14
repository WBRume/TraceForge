"""
Organization tree API routes (product lines -> project groups -> repositories).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db, require_admin
from app.domains.auth.models.user import User
from app.domains.management.schemas.management import (
    OrgNodeCreate,
    OrgNodeUpdate,
    RepoMoveRequest,
)
from app.domains.management.services import org_service, repository_service

router = APIRouter(prefix="/management/org", tags=["Management Org"])


@router.get("/tree")
def get_org_tree(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": org_service.build_org_tree(db)}


@router.post("/nodes", status_code=201)
def create_org_node(
    data: OrgNodeCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        node = org_service.create_node(
            db,
            parent_id=data.parent_id,
            name=data.name,
            node_type=data.node_type,
            order_index=data.order_index,
        )
        audit_log(
            action="create_org_node",
            outcome="success",
            resource_type="org_node",
            resource_id=node.id,
            user_id=current_user.id,
        )
        return {
            "id": node.id,
            "parent_id": node.parent_id,
            "name": node.name,
            "node_type": node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type),
            "order_index": node.order_index,
        }
    except org_service.OrgServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.put("/nodes/{node_id}")
def update_org_node(
    node_id: str,
    data: OrgNodeUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    node = org_service.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Org node not found")
    try:
        updated = org_service.update_node(
            db,
            node,
            parent_id=data.parent_id,
            name=data.name,
            order_index=data.order_index,
        )
        return {
            "id": updated.id,
            "parent_id": updated.parent_id,
            "name": updated.name,
            "node_type": updated.node_type.value if hasattr(updated.node_type, "value") else str(updated.node_type),
            "order_index": updated.order_index,
        }
    except org_service.OrgServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/nodes/{node_id}")
def delete_org_node(
    node_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    node = org_service.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Org node not found")
    try:
        org_service.delete_node(db, node)
        return {"msg": "Org node deleted"}
    except org_service.OrgServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/repositories/{repository_id}/move")
def move_repository_to_node(
    repository_id: str,
    data: RepoMoveRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    if data.org_node_id:
        node = org_service.get_node(db, data.org_node_id)
        if not node:
            raise HTTPException(status_code=404, detail="Org node not found")
    try:
        updated = repository_service.update_repository(db, repository, org_node_id=data.org_node_id)
        return repository_service.serialize_repository(updated)
    except repository_service.RepositoryServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
