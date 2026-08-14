"""
Product management service: products, versions and per-version repository bindings.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.domains.management.models.management import (
    ProductStatus,
    ProductVersionStatus,
    SddManagementProduct,
    SddManagementProductVersion,
    SddManagementProductVersionRepo,
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


def serialize_version(version: SddManagementProductVersion) -> Dict[str, object]:
    bindings = []
    for binding in sorted(version.repo_bindings, key=lambda item: item.created_at):
        repo = binding.repository
        bindings.append(
            {
                "id": binding.id,
                "repository_id": binding.repository_id,
                "repository_name": repo.name if repo else binding.repository_id,
                "git_url": repo.git_url if repo else None,
                "repo_type": repo.repo_type.value if repo and hasattr(repo.repo_type, "value") else None,
                "branch_name": binding.branch_name,
                "created_at": binding.created_at,
            }
        )
    return {
        "id": version.id,
        "product_id": version.product_id,
        "version_no": version.version_no,
        "status": version.status.value if hasattr(version.status, "value") else str(version.status),
        "release_date": version.release_date,
        "description": version.description,
        "repo_bindings": bindings,
        "created_at": version.created_at,
        "updated_at": version.updated_at,
    }


def serialize_product(product: SddManagementProduct) -> Dict[str, object]:
    return {
        "id": product.id,
        "name": product.name,
        "code": product.code,
        "product_line": product.product_line,
        "description": product.description,
        "status": product.status.value if hasattr(product.status, "value") else str(product.status),
        "created_at": product.created_at,
        "updated_at": product.updated_at,
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
        .options(joinedload(SddManagementProduct.versions).joinedload(SddManagementProductVersion.repo_bindings))
        .filter(SddManagementProduct.id == product_id)
        .first()
    )


def serialize_product_detail(product: SddManagementProduct) -> Dict[str, object]:
    payload = serialize_product(product)
    payload["versions"] = [serialize_version(version) for version in product.versions]
    return payload


def create_product(
    db: Session,
    *,
    name: str,
    code: str,
    product_line: Optional[str] = None,
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


def get_version(db: Session, product_id: str, version_id: str) -> Optional[SddManagementProductVersion]:
    return (
        db.query(SddManagementProductVersion)
        .options(joinedload(SddManagementProductVersion.repo_bindings).joinedload(SddManagementProductVersionRepo.repository))
        .filter(
            SddManagementProductVersion.id == version_id,
            SddManagementProductVersion.product_id == product_id,
        )
        .first()
    )


def create_version(
    db: Session,
    product: SddManagementProduct,
    *,
    version_no: str,
    status: str = "PLANNED",
    release_date: Optional[datetime] = None,
    description: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProductVersion:
    normalized_no = str(version_no or "").strip()
    if not normalized_no:
        raise ProductServiceError("version_no is required", status_code=400)
    existing = (
        db.query(SddManagementProductVersion)
        .filter(
            SddManagementProductVersion.product_id == product.id,
            SddManagementProductVersion.version_no == normalized_no,
        )
        .first()
    )
    if existing:
        raise ProductServiceError("This version already exists for the product", status_code=409)
    version = SddManagementProductVersion(
        product_id=product.id,
        version_no=normalized_no,
        status=_normalize_status(ProductVersionStatus, status or "PLANNED"),
        release_date=release_date,
        description=description,
        created_by=creator_id,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def update_version(
    db: Session,
    version: SddManagementProductVersion,
    *,
    version_no: Optional[str] = None,
    status: Optional[str] = None,
    release_date: Optional[datetime] = None,
    description: Optional[str] = None,
) -> SddManagementProductVersion:
    if version_no is not None:
        normalized_no = str(version_no).strip()
        existing = (
            db.query(SddManagementProductVersion)
            .filter(
                SddManagementProductVersion.product_id == version.product_id,
                SddManagementProductVersion.version_no == normalized_no,
                SddManagementProductVersion.id != version.id,
            )
            .first()
        )
        if existing:
            raise ProductServiceError("This version already exists for the product", status_code=409)
        version.version_no = normalized_no
    if status is not None:
        version.status = _normalize_status(ProductVersionStatus, status)
    if release_date is not None:
        version.release_date = release_date
    if description is not None:
        version.description = description
    db.commit()
    db.refresh(version)
    return version


def delete_version(db: Session, version: SddManagementProductVersion) -> None:
    db.delete(version)
    db.commit()


def bind_version_repo(
    db: Session,
    version: SddManagementProductVersion,
    *,
    repository_id: str,
    branch_name: str,
    creator_id: Optional[str] = None,
) -> SddManagementProductVersionRepo:
    repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
    if not repository:
        raise ProductServiceError("Repository not found", status_code=404)

    normalized_branch = str(branch_name or "").strip()
    if not normalized_branch:
        raise ProductServiceError("branch_name is required", status_code=400)

    # Binding validation: the repository must be accessible and the branch must exist.
    git_ref_service.validate_branch_exists(repository.git_url, normalized_branch)

    existing = (
        db.query(SddManagementProductVersionRepo)
        .filter(
            SddManagementProductVersionRepo.product_version_id == version.id,
            SddManagementProductVersionRepo.repository_id == repository.id,
        )
        .first()
    )
    if existing:
        raise ProductServiceError("This repository is already bound to the version", status_code=409)

    binding = SddManagementProductVersionRepo(
        product_version_id=version.id,
        repository_id=repository.id,
        branch_name=normalized_branch,
        created_by=creator_id,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


def unbind_version_repo(
    db: Session,
    version: SddManagementProductVersion,
    repository_id: str,
) -> None:
    binding = (
        db.query(SddManagementProductVersionRepo)
        .filter(
            SddManagementProductVersionRepo.product_version_id == version.id,
            SddManagementProductVersionRepo.repository_id == repository_id,
        )
        .first()
    )
    if not binding:
        raise ProductServiceError("Binding not found", status_code=404)
    db.delete(binding)
    db.commit()


def version_repo_bindings(
    db: Session,
    version: SddManagementProductVersion,
) -> List[Dict[str, object]]:
    return serialize_version(version)["repo_bindings"]  # type: ignore[return-value]


__all__ = [
    "ProductServiceError",
    "serialize_product",
    "serialize_product_detail",
    "list_products",
    "get_product",
    "create_product",
    "update_product",
    "delete_product",
    "get_version",
    "create_version",
    "update_version",
    "delete_version",
    "bind_version_repo",
    "unbind_version_repo",
]
