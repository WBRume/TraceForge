"""
Product management API routes (products evolve through versions).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db, require_admin
from app.domains.auth.models.user import User
from app.domains.management.schemas.management import (
    ProductBaseRepoBindCreate,
    ProductCreate,
    ProductRepoBindCreate,
    ProductUpdate,
    ProductVersionCreate,
    ProductVersionRepoBindCreate,
    ProductVersionRepoBindUpdate,
    ProductVersionRepoRefBatchUpdate,
    ProductVersionUpdate,
)
from app.domains.management.services import product_service
from app.domains.management.services.git_ref_service import GitRefAccessError

router = APIRouter(prefix="/management/products", tags=["Management Products"])


@router.get("")
def list_products(
    keyword: str = Query(default="", max_length=100),
    status: Optional[str] = None,
    include_versions: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = product_service.list_products(
        db,
        keyword=keyword,
        status=status,
        include_versions=include_versions,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_product(
    data: ProductCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        product = product_service.create_product(
            db,
            name=data.name,
            code=data.code,
            product_line=data.product_line,
            description=data.description,
            status=data.status,
            product_type=data.product_type,
            baseline_product_id=data.baseline_product_id,
            creator_id=current_user.id,
        )
        audit_log(
            action="create_product",
            outcome="success",
            resource_type="product",
            resource_id=product.id,
            user_id=current_user.id,
        )
        return product_service.serialize_product(product)
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/{product_id}")
def get_product(
    product_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_service.serialize_product_detail(product)


@router.put("/{product_id}")
def update_product(
    product_id: str,
    data: ProductUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        updated = product_service.update_product(
            db,
            product,
            name=data.name,
            code=data.code,
            product_line=data.product_line,
            description=data.description,
            status=data.status,
            product_type=data.product_type,
            baseline_product_id=data.baseline_product_id,
        )
        return product_service.serialize_product(updated)
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        product_service.delete_product(db, product)
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    audit_log(
        action="delete_product",
        outcome="success",
        resource_type="product",
        resource_id=product_id,
        user_id=current_user.id,
    )
    return {"msg": "Product deleted"}


# ── Product base repository pool ───────────────────────────────────────────

@router.post("/{product_id}/base-repos", status_code=201)
def add_product_base_repo(
    product_id: str,
    data: ProductBaseRepoBindCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        binding = product_service.add_base_repo(
            db,
            product,
            repository_id=data.repository_id,
            creator_id=current_user.id,
        )
        return {
            "id": binding.id,
            "product_id": product_id,
            "repository_id": binding.repository_id,
            "repository_name": binding.repository.name if binding.repository else None,
        }
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{product_id}/base-repos/{repository_id}")
def remove_product_base_repo(
    product_id: str,
    repository_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        product_service.remove_base_repo(db, product, repository_id)
        return {"msg": "Repository removed from product base"}
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


# ── Product versions ───────────────────────────────────────────────────────

@router.post("/{product_id}/versions", status_code=201)
def create_product_version(
    product_id: str,
    data: ProductVersionCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        version = product_service.create_version(
            db,
            product,
            version_no=data.version_no,
            status=data.status,
            release_date=data.release_date,
            description=data.description,
            from_version_id=data.from_version_id,
            baseline_product_version_id=data.baseline_product_version_id,
            inherit_product_repos=data.inherit_product_repos,
            inherit_ref_type=data.inherit_ref_type,
            inherit_ref_name=data.inherit_ref_name,
            creator_id=current_user.id,
        )
        audit_log(
            action="create_product_version",
            outcome="success",
            resource_type="product_version",
            resource_id=version.id,
            user_id=current_user.id,
            product_id=product.id,
            version_no=version.version_no,
        )
        return product_service.serialize_version(version)
    except (product_service.ProductServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.put("/{product_id}/versions/{version_id}")
def update_product_version(
    product_id: str,
    version_id: str,
    data: ProductVersionUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        updated = product_service.update_version(
            db,
            version,
            version_no=data.version_no,
            status=data.status,
            release_date=data.release_date,
            description=data.description,
        )
        return product_service.serialize_version(updated)
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{product_id}/versions/{version_id}")
def delete_product_version(
    product_id: str,
    version_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        product_service.delete_version(db, version)
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    audit_log(
        action="delete_product_version",
        outcome="success",
        resource_type="product_version",
        resource_id=version_id,
        user_id=current_user.id,
        product_id=product_id,
    )
    return {"msg": "Product version deleted"}


@router.post("/{product_id}/versions/{version_id}/baseline-exclusions", status_code=201)
def add_baseline_exclusion(
    product_id: str,
    version_id: str,
    data: ProductBaseRepoBindCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        exclusion = product_service.add_baseline_exclusion(
            db,
            version,
            repository_id=data.repository_id,
            creator_id=current_user.id,
        )
        return {
            "id": exclusion.id,
            "product_version_id": version_id,
            "repository_id": exclusion.repository_id,
        }
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{product_id}/versions/{version_id}/baseline-exclusions/{repository_id}")
def remove_baseline_exclusion(
    product_id: str,
    version_id: str,
    repository_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        product_service.remove_baseline_exclusion(db, version, repository_id)
        return {"msg": "Baseline repository exclusion removed"}
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{product_id}/versions/{version_id}/repos/batch-ref")
def update_version_repository_refs_batch(
    product_id: str,
    version_id: str,
    data: ProductVersionRepoRefBatchUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        bindings = product_service.update_version_repo_refs_batch(
            db,
            version,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
            scope=data.scope,
        )
        audit_log(
            action="update_version_repo_refs_batch",
            outcome="success",
            resource_type="product_version",
            resource_id=version_id,
            user_id=current_user.id,
            product_id=product_id,
            product_version_id=version_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
            updated_count=len(bindings),
        )
        return {
            "updated_count": len(bindings),
            "items": [
                {
                    "id": binding.id,
                    "product_version_id": version_id,
                    "repository_id": binding.repository_id,
                    "ref_type": binding.ref_type.value if hasattr(binding.ref_type, "value") else str(binding.ref_type),
                    "ref_name": binding.ref_name,
                }
                for binding in bindings
            ],
        }
    except (product_service.ProductServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.post("/{product_id}/versions/{version_id}/repos", status_code=201)
def bind_version_repository(
    product_id: str,
    version_id: str,
    data: ProductVersionRepoBindCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        binding = product_service.bind_version_repo(
            db,
            version,
            repository_id=data.repository_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
            creator_id=current_user.id,
        )
        audit_log(
            action="bind_version_repo",
            outcome="success",
            resource_type="product_version_repo",
            resource_id=binding.id,
            user_id=current_user.id,
            product_id=product_id,
            product_version_id=version_id,
            repository_id=data.repository_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
        )
        return {
            "id": binding.id,
            "product_id": product_id,
            "product_version_id": version_id,
            "repository_id": binding.repository_id,
            "ref_type": binding.ref_type.value if hasattr(binding.ref_type, "value") else str(binding.ref_type),
            "ref_name": binding.ref_name,
        }
    except (product_service.ProductServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.put("/{product_id}/versions/{version_id}/repos/{repository_id}")
def update_version_repository_ref(
    product_id: str,
    version_id: str,
    repository_id: str,
    data: ProductVersionRepoBindUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        binding = product_service.update_version_repo_ref(
            db,
            version,
            repository_id=repository_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
        )
        audit_log(
            action="update_version_repo_ref",
            outcome="success",
            resource_type="product_version_repo",
            resource_id=binding.id,
            user_id=current_user.id,
            product_id=product_id,
            product_version_id=version_id,
            repository_id=repository_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
        )
        return {
            "id": binding.id,
            "product_id": product_id,
            "product_version_id": version_id,
            "repository_id": binding.repository_id,
            "ref_type": binding.ref_type.value if hasattr(binding.ref_type, "value") else str(binding.ref_type),
            "ref_name": binding.ref_name,
        }
    except (product_service.ProductServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.delete("/{product_id}/versions/{version_id}/repos/{repository_id}")
def unbind_version_repository(
    product_id: str,
    version_id: str,
    repository_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = product_service.get_version(db, product_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")
    try:
        product_service.unbind_version_repo(db, version, repository_id)
        return {"msg": "Repository unbound from product version"}
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


# ── Legacy product-level binding (compat: binds to the latest version) ─────

@router.post("/{product_id}/repos", status_code=201)
def bind_product_repository_legacy(
    product_id: str,
    data: ProductRepoBindCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.versions:
        raise HTTPException(status_code=409, detail="Product has no versions yet")
    version = product.versions[-1]
    try:
        binding = product_service.bind_version_repo(
            db,
            version,
            repository_id=data.repository_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
            creator_id=current_user.id,
        )
        return {
            "id": binding.id,
            "product_id": product.id,
            "product_version_id": version.id,
            "repository_id": binding.repository_id,
            "ref_type": binding.ref_type.value if hasattr(binding.ref_type, "value") else str(binding.ref_type),
            "ref_name": binding.ref_name,
        }
    except (product_service.ProductServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.delete("/{product_id}/repos/{repository_id}")
def unbind_product_repository_legacy(
    product_id: str,
    repository_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.versions:
        raise HTTPException(status_code=409, detail="Product has no versions yet")
    try:
        product_service.unbind_version_repo(db, product.versions[-1], repository_id)
        return {"msg": "Repository unbound from product"}
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
