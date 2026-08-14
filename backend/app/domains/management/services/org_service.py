"""
Organization tree service: product lines -> project groups, hosting repositories.
"""

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.domains.management.models.management import (
    OrgNodeType,
    SddManagementOrgNode,
    SddManagementRepository,
)


class OrgServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _normalize_node_type(value: str) -> OrgNodeType:
    normalized = str(value or "").strip().upper()
    try:
        return OrgNodeType(normalized)
    except ValueError as exc:
        raise OrgServiceError(
            f"Invalid node_type '{value}'. Expected PRODUCT_LINE or PROJECT_GROUP",
            status_code=400,
        ) from exc


def get_node(db: Session, node_id: str) -> Optional[SddManagementOrgNode]:
    return db.query(SddManagementOrgNode).filter(SddManagementOrgNode.id == node_id).first()


def create_node(
    db: Session,
    *,
    parent_id: Optional[str],
    name: str,
    node_type: str,
    order_index: int = 0,
) -> SddManagementOrgNode:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise OrgServiceError("Node name is required", status_code=400)
    normalized_type = _normalize_node_type(node_type)

    if parent_id:
        parent = get_node(db, parent_id)
        if not parent:
            raise OrgServiceError("Parent node not found", status_code=404)
        # A product line nests project groups; a project group cannot nest further.
        if parent.node_type == OrgNodeType.PROJECT_GROUP:
            raise OrgServiceError("A project group cannot contain child nodes", status_code=409)
        if parent.node_type == OrgNodeType.PRODUCT_LINE and normalized_type != OrgNodeType.PROJECT_GROUP:
            raise OrgServiceError("Only project groups can be nested under a product line", status_code=409)

    node = SddManagementOrgNode(
        parent_id=parent_id or None,
        name=normalized_name,
        node_type=normalized_type,
        order_index=int(order_index or 0),
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def update_node(
    db: Session,
    node: SddManagementOrgNode,
    *,
    parent_id: Optional[str] = None,
    name: Optional[str] = None,
    order_index: Optional[int] = None,
) -> SddManagementOrgNode:
    if name is not None:
        normalized_name = str(name).strip()
        if not normalized_name:
            raise OrgServiceError("Node name is required", status_code=400)
        node.name = normalized_name

    if parent_id is not None and parent_id != node.parent_id:
        if parent_id == node.id:
            raise OrgServiceError("A node cannot be its own parent", status_code=409)
        if parent_id:
            parent = get_node(db, parent_id)
            if not parent:
                raise OrgServiceError("Parent node not found", status_code=404)
            if parent.node_type != OrgNodeType.PRODUCT_LINE or node.node_type != OrgNodeType.PROJECT_GROUP:
                raise OrgServiceError("Only project groups can be moved under a product line", status_code=409)
        node.parent_id = parent_id

    if order_index is not None:
        node.order_index = int(order_index)

    db.commit()
    db.refresh(node)
    return node


def delete_node(db: Session, node: SddManagementOrgNode) -> None:
    repo_count = (
        db.query(SddManagementRepository)
        .filter(SddManagementRepository.org_node_id == node.id)
        .count()
    )
    if repo_count > 0:
        raise OrgServiceError(
            "Cannot delete a node that still hosts repositories. Move the repositories first.",
            status_code=409,
        )
    db.delete(node)
    db.commit()


def build_org_tree(db: Session) -> List[Dict[str, object]]:
    nodes = (
        db.query(SddManagementOrgNode)
        .order_by(SddManagementOrgNode.order_index.asc(), SddManagementOrgNode.name.asc())
        .all()
    )
    repos = db.query(SddManagementRepository).order_by(SddManagementRepository.name.asc()).all()
    repos_by_node: Dict[str, List[Dict[str, object]]] = {}
    for repo in repos:
        key = str(repo.org_node_id or "")
        repos_by_node.setdefault(key, []).append(
            {
                "id": repo.id,
                "name": repo.name,
                "git_url": repo.git_url,
                "repo_type": repo.repo_type.value if hasattr(repo.repo_type, "value") else str(repo.repo_type),
            }
        )

    payloads_by_id: Dict[str, Dict[str, object]] = {}
    roots: List[Dict[str, object]] = []
    for node in nodes:
        node_type = node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type)
        payload = {
            "id": node.id,
            "parent_id": node.parent_id,
            "name": node.name,
            "node_type": node_type,
            "order_index": node.order_index,
            "repositories": repos_by_node.get(node.id, []),
            "children": [],
        }
        payloads_by_id[node.id] = payload
        if not node.parent_id:
            roots.append(payload)

    for node in nodes:
        if node.parent_id and node.parent_id in payloads_by_id:
            payloads_by_id[node.parent_id]["children"].append(payloads_by_id[node.id])

    tree = roots
    if repos_by_node.get(""):
        tree = [
            *tree,
            {
                "id": None,
                "parent_id": None,
                "name": "Unassigned",
                "node_type": "UNASSIGNED",
                "order_index": 9999,
                "repositories": repos_by_node[""],
                "children": [],
            },
        ]
    return tree


__all__ = [
    "OrgServiceError",
    "get_node",
    "create_node",
    "update_node",
    "delete_node",
    "build_org_tree",
]
