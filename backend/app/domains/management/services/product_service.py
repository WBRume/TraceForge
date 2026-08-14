"""
Product management service.

A product doubles as its version: it carries version_no/release_date and
binds directly to multiple repositories. Every binding records the git tag
or branch used for workspace checkout and is validated against the remote.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.domains.management.models.management import (
    ProductStatus,
    RepoRefType,
    SddManagementProduct,
    SddManagementProductRepo,
    SddManagementRepository,
)
from app.domains.management.services import git_ref_service


class ProductServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _normalize_status(enum_class, value: str):
    normalized = str(value or "").strip().upper()
    try:
        return enum_class(normalized)
    except ValueError as exc:
        raise ProductServiceError(f"Invalid status '{value}'", status_code=400) from exc


def _normalize_ref_type(value: str) -> RepoRefType:
    normalized = str(value or "BRANCH").strip().upper()
    try:
        return RepoRefType(normalized)
    except ValueError as exc:
        raise ProductServiceError("ref_type must be BRANCH or TAG", status_code=400) from exc


def serialize_product(product: SddManagementProduct, *, include_bindings: bool = False) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "id": product.id,
        "name": product.name,
        "code": product.code,
        "product_line": product.product_line,
        "version_no": product.version_no,
        "release_date": product.release_date,
        "description": product.description,
        "status": product.status.value if hasattr(product.status, "value") else str(product.status),
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }
    if include_bindings:
        payload["repo_bindings"] = [
            _serialize_binding(binding) for binding in product.repo_bindings
        ]
    return payload


def _serialize_binding(binding: SddManagementProductRepo) -> Dict[str, object]:
    repo = binding.repository
    return {
        "id": binding.id,
        "repository_id": binding.repository_id,
        "repository_name": repo.name if repo else binding.repository_id,
        "git_url": repo.git_url if repo else None,
        "repo_type": repo.repo_type.value if repo and hasattr(repo.repo_type, "value") else None,
        "ref_type": binding.ref_type.value if hasattr(binding.ref_type, "value") else str(binding.ref_type),
        "ref_name": binding.ref_name,
        "created_at": binding.created_at,
    }


def list_products(
    db: Session,
    *,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, object]], int]:
    query = db.query(SddManagementProduct)
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        query = query.filter(
            or_(
                SddManagementProduct.name.ilike(pattern),
                SddManagementProduct.code.ilike(pattern),
                SddManagementProduct.product_line.ilike(pattern),
                SddManagementProduct.version_no.ilike(pattern),
            )
        )
    if status:
        query = query.filter(SddManagementProduct.status == _normalize_status(ProductStatus, status))

    total = query.count()
    products = (
        query.order_by(SddManagementProduct.created_at.desc())
        .offset((max(1, page) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [serialize_product(product) for product in products], total


def get_product(db: Session, product_id: str) -> Optional[SddManagementProduct]:
    return (
        db.query(SddManagementProduct)
        .options(joinedload(SddManagementProduct.repo_bindings).joinedload(SddManagementProductRepo.repository))
        .filter(SddManagementProduct.id == product_id)
        .first()
    )


def serialize_product_detail(product: SddManagementProduct) -> Dict[str, object]:
    return serialize_product(product, include_bindings=True)


def create_product(
    db: Session,
    *,
    name: str,
    code: str,
    product_line: Optional[str] = None,
    version_no: str = "",
    release_date: Optional[datetime] = None,
    description: Optional[str] = None,
    status: str = "ACTIVE",
    creator_id: Optional[str] = None,
) -> SddManagementProduct:
    normalized_name = str(name or "").strip()
    normalized_code = str(code or "").strip()
    if not normalized_name or not normalized_code:
        raise ProductServiceError("Product name and code are required", status_code=400)
    existing = db.query(SddManagementProduct).filter(SddManagementProduct.code == normalized_code).first()
    if existing:
        raise ProductServiceError("A product with this code already exists", status_code=409)
    product = SddManagementProduct(
        name=normalized_name,
        code=normalized_code,
        product_line=(str(product_line or "").strip() or None),
        version_no=str(version_no or "").strip(),
        release_date=release_date,
        description=description,
        status=_normalize_status(ProductStatus, status or "ACTIVE"),
        created_by=creator_id,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def update_product(
    db: Session,
    product: SddManagementProduct,
    *,
    name: Optional[str] = None,
    code: Optional[str] = None,
    product_line: Optional[str] = None,
    version_no: Optional[str] = None,
    release_date: Optional[datetime] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
) -> SddManagementProduct:
    if name is not None:
        product.name = str(name).strip() or product.name
    if code is not None:
        normalized_code = str(code).strip()
        existing = (
            db.query(SddManagementProduct)
            .filter(SddManagementProduct.code == normalized_code, SddManagementProduct.id != product.id)
            .first()
        )
        if existing:
            raise ProductServiceError("A product with this code already exists", status_code=409)
        product.code = normalized_code
    if product_line is not None:
        product.product_line = str(product_line).strip() or None
    if version_no is not None:
        product.version_no = str(version_no).strip()
    if release_date is not None:
        product.release_date = release_date
    if description is not None:
        product.description = description
    if status is not None:
        product.status = _normalize_status(ProductStatus, status)
    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, product: SddManagementProduct) -> None:
    db.delete(product)
    db.commit()


def bind_product_repo(
    db: Session,
    product: SddManagementProduct,
    *,
    repository_id: str,
    ref_type: str,
    ref_name: str,
    creator_id: Optional[str] = None,
) -> SddManagementProductRepo:
    repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
    if not repository:
        raise ProductServiceError("Repository not found", status_code=404)

    normalized_ref_name = str(ref_name or "").strip()
    normalized_ref_type = _normalize_ref_type(ref_type or "BRANCH")
    if not normalized_ref_name:
        raise ProductServiceError("ref_name is required", status_code=400)

    # Binding validation: the remote must expose the branch/tag.
    git_ref_service.validate_ref_exists(
        repository.git_url,
        normalized_ref_type.value,
        normalized_ref_name,
    )

    existing = (
        db.query(SddManagementProductRepo)
        .filter(
            SddManagementProductRepo.product_id == product.id,
            SddManagementProductRepo.repository_id == repository.id,
        )
        .first()
    )
    if existing:
        raise ProductServiceError("This repository is already bound to the product", status_code=409)

    binding = SddManagementProductRepo(
        product_id=product.id,
        repository_id=repository.id,
        ref_type=normalized_ref_type,
        ref_name=normalized_ref_name,
        created_by=creator_id,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


def unbind_product_repo(db: Session, product: SddManagementProduct, repository_id: str) -> None:
    binding = (
        db.query(SddManagementProductRepo)
        .filter(
            SddManagementProductRepo.product_id == product.id,
            SddManagementProductRepo.repository_id == repository_id,
        )
        .first()
    )
    if not binding:
        raise ProductServiceError("Binding not found", status_code=404)
    db.delete(binding)
    db.commit()


__all__ = [
    "ProductServiceError",
    "serialize_product",
    "serialize_product_detail",
    "list_products",
    "get_product",
    "create_product",
    "update_product",
    "delete_product",
    "bind_product_repo",
    "unbind_product_repo",
]
