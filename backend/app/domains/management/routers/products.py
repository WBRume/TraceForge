"""
Product management API routes (product doubles as its version).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db, require_admin
from app.domains.auth.models.user import User
from app.domains.management.schemas.management import (
    ProductCreate,
    ProductRepoBindCreate,
    ProductUpdate,
)
from app.domains.management.services import product_service
from app.domains.management.services.git_ref_service import GitRefAccessError

router = APIRouter(prefix="/management/products", tags=["Management Products"])


@router.get("")
def list_products(
    keyword: str = Query(default="", max_length=100),
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = product_service.list_products(
        db,
        keyword=keyword,
        status=status,
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
            version_no=data.version_no,
            release_date=data.release_date,
            description=data.description,
            status=data.status,
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
            version_no=data.version_no,
            release_date=data.release_date,
            description=data.description,
            status=data.status,
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
    product_service.delete_product(db, product)
    audit_log(
        action="delete_product",
        outcome="success",
        resource_type="product",
        resource_id=product_id,
        user_id=current_user.id,
    )
    return {"msg": "Product deleted"}


@router.post("/{product_id}/repos", status_code=201)
def bind_product_repository(
    product_id: str,
    data: ProductRepoBindCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        binding = product_service.bind_product_repo(
            db,
            product,
            repository_id=data.repository_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
            creator_id=current_user.id,
        )
        audit_log(
            action="bind_product_repo",
            outcome="success",
            resource_type="product_repo",
            resource_id=binding.id,
            user_id=current_user.id,
            product_id=product.id,
            repository_id=data.repository_id,
            ref_type=data.ref_type,
            ref_name=data.ref_name,
        )
        return {
            "id": binding.id,
            "product_id": binding.product_id,
            "repository_id": binding.repository_id,
            "ref_type": binding.ref_type.value if hasattr(binding.ref_type, "value") else str(binding.ref_type),
            "ref_name": binding.ref_name,
        }
    except (product_service.ProductServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.delete("/{product_id}/repos/{repository_id}")
def unbind_product_repository(
    product_id: str,
    repository_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    product = product_service.get_product(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        product_service.unbind_product_repo(db, product, repository_id)
        return {"msg": "Repository unbound from product"}
    except product_service.ProductServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
