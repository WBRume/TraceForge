"""
Product management service.

A product starts without versions and owns a changeable pool of base
repositories. Versions are created later through the development/release
process: each version may inherit the product base pool (optionally with a
uniform branch/tag), copy another version, or start empty and bind
version-specific repositories. Repository bindings are validated against the
remote.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domains.management.models.management import (
    ProductStatus,
    ProductType,
    ProductVersionStatus,
    RepoRefType,
    RepositoryType,
    SddManagementProduct,
    SddManagementProductRepo,
    SddManagementProductVersion,
    SddManagementProductVersionBaselineExclusion,
    SddManagementProductVersionRepo,
    SddManagementProject,
    SddManagementProjectProduct,
    SddManagementProjectRelease,
    SddManagementRepository,
)
from app.domains.management.services import git_ref_service


class ProductServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _normalize_product_type(value: str) -> ProductType:
    normalized = str(value or "OOTB").strip().upper()
    try:
        return ProductType(normalized)
    except ValueError as exc:
        raise ProductServiceError("Invalid product_type. Expected OOTB or CUSTOM", status_code=400) from exc


def _ensure_repo_type_matches_product(
    product: SddManagementProduct,
    repository: SddManagementRepository,
) -> None:
    if product.product_type == ProductType.OOTB and repository.repo_type != RepositoryType.OOTB:
        raise ProductServiceError(
            "OOTB product can only bind OOTB repositories",
            status_code=400,
        )
    if product.product_type == ProductType.CUSTOM and repository.repo_type != RepositoryType.CUSTOM:
        raise ProductServiceError(
            "Custom product can only bind custom repositories",
            status_code=400,
        )


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


def _serialize_binding(binding: SddManagementProductVersionRepo) -> Dict[str, object]:
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


def _binding_to_effective_dict(
    binding,
    source: str,
) -> Dict[str, object]:
    repo = binding.repository
    return {
        "id": binding.id,
        "repository_id": binding.repository_id,
        "repository_name": repo.name if repo else binding.repository_id,
        "git_url": repo.git_url if repo else None,
        "repo_type": repo.repo_type.value if repo and hasattr(repo.repo_type, "value") else None,
        "default_branch": repo.default_branch if repo else None,
        "ref_type": binding.ref_type.value if hasattr(binding.ref_type, "value") else str(binding.ref_type),
        "ref_name": binding.ref_name,
        "source": source,
        "created_at": binding.created_at,
    }


def _serialize_effective_binding(item: Dict[str, object]) -> Dict[str, object]:
    return item


def resolve_effective_version_bindings(
    version: SddManagementProductVersion,
) -> List[Dict[str, object]]:
    """Resolve the live repository set of a product version.

    For custom versions, the effective set is the baseline version's current
    bindings (minus excluded repositories) overlaid with this version's own
    custom bindings. For normal versions, the version's own bindings are the
    effective set.
    """
    custom_bindings = list(version.repo_bindings or [])
    baseline = version.baseline_version
    if baseline is None:
        return [_binding_to_effective_dict(binding, "custom") for binding in custom_bindings]

    excluded_ids = {
        item.repository_id for item in (version.baseline_exclusions or [])
    }
    result: Dict[str, Dict[str, object]] = {}
    for binding in baseline.repo_bindings or []:
        if binding.repository_id in excluded_ids:
            continue
        result[binding.repository_id] = _binding_to_effective_dict(binding, "baseline")
    for binding in custom_bindings:
        source = "custom_override" if binding.repository_id in result else "custom"
        result[binding.repository_id] = _binding_to_effective_dict(binding, source)
    return list(result.values())


def _serialize_base_repo(binding: SddManagementProductRepo) -> Dict[str, object]:
    repo = binding.repository
    return {
        "id": binding.id,
        "product_id": binding.product_id,
        "repository_id": binding.repository_id,
        "repository_name": repo.name if repo else binding.repository_id,
        "git_url": repo.git_url if repo else None,
        "repo_type": repo.repo_type.value if repo and hasattr(repo.repo_type, "value") else None,
        "default_branch": repo.default_branch if repo else None,
        "created_at": binding.created_at,
    }


def _serialize_custom_version_ref(version: SddManagementProductVersion) -> Dict[str, object]:
    product = version.product
    return {
        "id": version.id,
        "product_id": version.product_id,
        "product_name": product.name if product else version.product_id,
        "product_code": product.code if product else None,
        "version_no": version.version_no,
        "status": version.status.value if hasattr(version.status, "value") else str(version.status),
    }


def _serialize_custom_product_ref(product: SddManagementProduct) -> Dict[str, object]:
    latest = _latest_version(product)
    return {
        "id": product.id,
        "name": product.name,
        "code": product.code,
        "version_no": latest.version_no if latest else (product.version_no or ""),
        "status": product.status.value if hasattr(product.status, "value") else str(product.status),
    }


def serialize_version(
    version: SddManagementProductVersion,
    *,
    include_bindings: bool = False,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "id": version.id,
        "product_id": version.product_id,
        "version_no": version.version_no,
        "status": version.status.value if hasattr(version.status, "value") else str(version.status),
        "release_date": version.release_date,
        "description": version.description,
        "baseline_product_version_id": version.baseline_product_version_id,
        "baseline_version_no": version.baseline_version.version_no if version.baseline_version else None,
        "baseline_product_id": version.baseline_version.product_id if version.baseline_version else None,
        "baseline_product_code": version.baseline_version.product.code if version.baseline_version and version.baseline_version.product else None,
        "baseline_product_name": version.baseline_version.product.name if version.baseline_version and version.baseline_version.product else None,
        "custom_versions": [
            _serialize_custom_version_ref(cv) for cv in (version.custom_versions or [])
        ],
        "created_at": version.created_at,
        "updated_at": version.updated_at,
    }
    if include_bindings:
        payload["repo_bindings"] = [
            _serialize_binding(binding) for binding in version.repo_bindings
        ]
        payload["effective_repo_bindings"] = [
            _serialize_effective_binding(item) for item in resolve_effective_version_bindings(version)
        ]
    return payload


def _latest_version(product: SddManagementProduct) -> Optional[SddManagementProductVersion]:
    """Latest version of a product (by creation order)."""
    if not product.versions:
        return None
    return product.versions[-1]


def serialize_product(product: SddManagementProduct, *, include_bindings: bool = False) -> Dict[str, object]:
    latest = _latest_version(product)
    payload: Dict[str, object] = {
        "id": product.id,
        "name": product.name,
        "code": product.code,
        "product_line": product.product_line,
        "version_no": latest.version_no if latest else (product.version_no or ""),
        "release_date": latest.release_date if latest else product.release_date,
        "description": product.description,
        "status": product.status.value if hasattr(product.status, "value") else str(product.status),
        "product_type": product.product_type.value if hasattr(product.product_type, "value") else str(product.product_type),
        "baseline_product_id": product.baseline_product_id,
        "baseline_product_name": product.baseline_product.name if product.baseline_product else None,
        "created_at": product.created_at,
        "updated_at": product.updated_at,
    }
    if include_bindings:
        payload["base_repos"] = [
            _serialize_base_repo(binding) for binding in product.base_repos
        ]
        payload["versions"] = [
            serialize_version(version, include_bindings=True) for version in product.versions
        ]
        payload["custom_products"] = [
            _serialize_custom_product_ref(cp) for cp in (product.custom_products or [])
        ]
    return payload


def list_products(
    db: Session,
    *,
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    include_versions: bool = False,
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
    options = [
        joinedload(SddManagementProduct.versions),
        joinedload(SddManagementProduct.base_repos).joinedload(SddManagementProductRepo.repository),
    ]
    if include_versions:
        options.extend([
            selectinload(SddManagementProduct.custom_products)
            .selectinload(SddManagementProduct.versions),
            joinedload(SddManagementProduct.versions)
            .selectinload(SddManagementProductVersion.custom_versions)
            .joinedload(SddManagementProductVersion.product),
        ])
    products = (
        query.options(*options)
        .order_by(SddManagementProduct.created_at.desc())
        .offset((max(1, page) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [
        serialize_product(product, include_bindings=include_versions)
        for product in products
    ], total


def get_product(db: Session, product_id: str) -> Optional[SddManagementProduct]:
    return (
        db.query(SddManagementProduct)
        .options(
            joinedload(SddManagementProduct.baseline_product),
            selectinload(SddManagementProduct.custom_products)
            .selectinload(SddManagementProduct.versions),
            joinedload(SddManagementProduct.versions)
            .selectinload(SddManagementProductVersion.custom_versions)
            .joinedload(SddManagementProductVersion.product),
            joinedload(SddManagementProduct.base_repos).joinedload(SddManagementProductRepo.repository),
            joinedload(SddManagementProduct.versions)
            .joinedload(SddManagementProductVersion.repo_bindings)
            .joinedload(SddManagementProductVersionRepo.repository),
            joinedload(SddManagementProduct.versions)
            .joinedload(SddManagementProductVersion.baseline_version)
            .joinedload(SddManagementProductVersion.product),
        )
        .filter(SddManagementProduct.id == product_id)
        .first()
    )


def serialize_product_detail(product: SddManagementProduct) -> Dict[str, object]:
    return serialize_product(product, include_bindings=True)


def get_version(
    db: Session,
    product_id: str,
    version_id: str,
) -> Optional[SddManagementProductVersion]:
    return (
        db.query(SddManagementProductVersion)
        .options(
            joinedload(SddManagementProductVersion.repo_bindings)
            .joinedload(SddManagementProductVersionRepo.repository),
            joinedload(SddManagementProductVersion.baseline_version)
            .joinedload(SddManagementProductVersion.product),
            selectinload(SddManagementProductVersion.custom_versions)
            .joinedload(SddManagementProductVersion.product),
        )
        .filter(
            SddManagementProductVersion.id == version_id,
            SddManagementProductVersion.product_id == product_id,
        )
        .first()
    )


def create_product(
    db: Session,
    *,
    name: str,
    code: str,
    product_line: Optional[str] = None,
    description: Optional[str] = None,
    status: str = "ACTIVE",
    product_type: str = "OOTB",
    baseline_product_id: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProduct:
    normalized_name = str(name or "").strip()
    normalized_code = str(code or "").strip()
    if not normalized_name or not normalized_code:
        raise ProductServiceError("Product name and code are required", status_code=400)
    existing = db.query(SddManagementProduct).filter(SddManagementProduct.code == normalized_code).first()
    if existing:
        raise ProductServiceError("A product with this code already exists", status_code=409)

    normalized_type = _normalize_product_type(product_type)
    baseline = None
    if normalized_type == ProductType.CUSTOM:
        if not baseline_product_id:
            raise ProductServiceError(
                "Custom product requires a baseline product",
                status_code=400,
            )
        baseline = db.query(SddManagementProduct).filter(
            SddManagementProduct.id == baseline_product_id,
            SddManagementProduct.product_type == ProductType.OOTB,
        ).first()
        if not baseline:
            raise ProductServiceError(
                "Baseline product not found or it is not an OOTB product",
                status_code=404,
            )

    # A product starts without versions; versions are created through the
    # development/release process afterwards.
    product = SddManagementProduct(
        name=normalized_name,
        code=normalized_code,
        product_line=(str(product_line or "").strip() or None),
        version_no="",
        release_date=None,
        description=description,
        status=_normalize_status(ProductStatus, status or "ACTIVE"),
        product_type=normalized_type,
        baseline_product_id=baseline.id if baseline else None,
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
    product_type: Optional[str] = None,
    baseline_product_id: Optional[str] = None,
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
    if product_type is not None or baseline_product_id is not None:
        new_type = _normalize_product_type(product_type or product.product_type.value)
        new_baseline_id = baseline_product_id if baseline_product_id is not None else product.baseline_product_id
        if new_type == ProductType.CUSTOM:
            if not new_baseline_id:
                raise ProductServiceError(
                    "Custom product requires a baseline product",
                    status_code=400,
                )
            baseline = db.query(SddManagementProduct).filter(
                SddManagementProduct.id == new_baseline_id,
                SddManagementProduct.product_type == ProductType.OOTB,
            ).first()
            if not baseline:
                raise ProductServiceError(
                    "Baseline product not found or it is not an OOTB product",
                    status_code=404,
                )
        elif new_baseline_id:
            raise ProductServiceError(
                "OOTB product cannot have a baseline product",
                status_code=400,
            )
        product.product_type = new_type
        product.baseline_product_id = new_baseline_id if new_type == ProductType.CUSTOM else None
    db.commit()
    db.refresh(product)
    return product


def add_base_repo(
    db: Session,
    product: SddManagementProduct,
    *,
    repository_id: str,
    creator_id: Optional[str] = None,
) -> SddManagementProductRepo:
    repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
    if not repository:
        raise ProductServiceError("Repository not found", status_code=404)
    _ensure_repo_type_matches_product(product, repository)
    existing = (
        db.query(SddManagementProductRepo)
        .filter(
            SddManagementProductRepo.product_id == product.id,
            SddManagementProductRepo.repository_id == repository.id,
        )
        .first()
    )
    if existing:
        raise ProductServiceError("This repository is already in the product base", status_code=409)
    binding = SddManagementProductRepo(
        product_id=product.id,
        repository_id=repository.id,
        created_by=creator_id,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


def remove_base_repo(
    db: Session,
    product: SddManagementProduct,
    repository_id: str,
) -> None:
    binding = (
        db.query(SddManagementProductRepo)
        .filter(
            SddManagementProductRepo.product_id == product.id,
            SddManagementProductRepo.repository_id == repository_id,
        )
        .first()
    )
    if not binding:
        raise ProductServiceError("Product base repository not found", status_code=404)
    db.delete(binding)
    db.commit()


def _product_reference_lines(
    db: Session,
    product: SddManagementProduct,
) -> List[str]:
    """Return human-readable references to a product from projects/releases."""
    lines: List[str] = []

    custom_products = (
        db.query(SddManagementProduct)
        .filter(SddManagementProduct.baseline_product_id == product.id)
        .all()
    )
    for custom_product in custom_products:
        lines.append(f"custom product '{custom_product.name}'")

    project_links = (
        db.query(SddManagementProjectProduct, SddManagementProject)
        .join(SddManagementProject, SddManagementProject.id == SddManagementProjectProduct.project_id)
        .filter(SddManagementProjectProduct.product_id == product.id)
        .all()
    )
    for _, project in project_links:
        lines.append(f"project '{project.name}'")

    release_refs = (
        db.query(SddManagementProjectRelease, SddManagementProject)
        .join(SddManagementProject, SddManagementProject.id == SddManagementProjectRelease.project_id)
        .filter(SddManagementProjectRelease.product_id == product.id)
        .all()
    )
    for release, project in release_refs:
        lines.append(f"project '{project.name}' release '{release.release_no}'")

    return lines


def delete_product(db: Session, product: SddManagementProduct) -> None:
    references = _product_reference_lines(db, product)
    if references:
        raise ProductServiceError(
            "Cannot delete product '{name}' because it is still referenced by: {refs}".format(
                name=product.name,
                refs="; ".join(references),
            ),
            status_code=409,
        )
    db.delete(product)
    db.commit()


# ── Product versions ───────────────────────────────────────────────────────

def create_version(
    db: Session,
    product: SddManagementProduct,
    *,
    version_no: str,
    status: str = "ACTIVE",
    release_date: Optional[datetime] = None,
    description: Optional[str] = None,
    from_version_id: Optional[str] = None,
    baseline_product_version_id: Optional[str] = None,
    inherit_product_repos: bool = False,
    inherit_ref_type: Optional[str] = None,
    inherit_ref_name: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProductVersion:
    normalized_no = str(version_no or "").strip()
    if not normalized_no:
        raise ProductServiceError("version_no is required", status_code=400)
    if from_version_id and inherit_product_repos:
        raise ProductServiceError(
            "Choose either 'from_version_id' or 'inherit_product_repos', not both",
            status_code=400,
        )
    is_custom = product.product_type == ProductType.CUSTOM
    if is_custom and not baseline_product_version_id:
        raise ProductServiceError(
            "Custom product version requires a baseline product version",
            status_code=400,
        )
    if not is_custom and baseline_product_version_id:
        raise ProductServiceError(
            "Only custom product versions can bind a baseline product version",
            status_code=400,
        )
    baseline_version = None
    if baseline_product_version_id:
        baseline_version = (
            db.query(SddManagementProductVersion)
            .filter(
                SddManagementProductVersion.id == baseline_product_version_id,
                SddManagementProductVersion.product_id == product.baseline_product_id,
            )
            .first()
        )
        if not baseline_version:
            raise ProductServiceError(
                "Baseline product version not found for the selected baseline product",
                status_code=404,
            )
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

    source = None
    if from_version_id:
        source = (
            db.query(SddManagementProductVersion)
            .filter(
                SddManagementProductVersion.id == from_version_id,
                SddManagementProductVersion.product_id == product.id,
            )
            .first()
        )
        if not source:
            raise ProductServiceError("Source version not found", status_code=404)

    version = SddManagementProductVersion(
        product_id=product.id,
        version_no=normalized_no,
        status=_normalize_status(ProductVersionStatus, status or "ACTIVE"),
        release_date=release_date,
        description=description,
        baseline_product_version_id=baseline_version.id if baseline_version else None,
        created_by=creator_id,
    )
    db.add(version)
    db.flush()

    if source is not None:
        # Copy the source version's repository bindings (multi-way evolution).
        for binding in source.repo_bindings:
            db.add(
                SddManagementProductVersionRepo(
                    product_version_id=version.id,
                    repository_id=binding.repository_id,
                    ref_type=binding.ref_type,
                    ref_name=binding.ref_name,
                    created_by=creator_id,
                )
            )
    elif inherit_product_repos:
        # Seed the version from the product's current base repository pool.
        # An optional uniform ref can be applied to every inherited repo
        # (e.g. a release maintenance branch); otherwise the repository
        # default branch is used.
        base_ref_type = _normalize_ref_type(inherit_ref_type or "BRANCH")
        uniform_ref_name = str(inherit_ref_name or "").strip()
        base_repos = (
            db.query(SddManagementProductRepo)
            .options(joinedload(SddManagementProductRepo.repository))
            .filter(SddManagementProductRepo.product_id == product.id)
            .order_by(SddManagementProductRepo.created_at.asc())
            .all()
        )
        for base_repo in base_repos:
            repository = base_repo.repository
            if not repository:
                continue
            ref_name = uniform_ref_name or repository.default_branch or "main"
            git_ref_service.validate_ref_exists(repository.git_url, base_ref_type.value, ref_name)
            db.add(
                SddManagementProductVersionRepo(
                    product_version_id=version.id,
                    repository_id=repository.id,
                    ref_type=base_ref_type,
                    ref_name=ref_name,
                    created_by=creator_id,
                )
            )

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
        if not normalized_no:
            raise ProductServiceError("version_no cannot be empty", status_code=400)
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
    if version.custom_versions:
        refs = "; ".join(
            f"custom version '{cv.version_no}'" for cv in version.custom_versions
        )
        raise ProductServiceError(
            "Cannot delete baseline version '{version_no}' because it is still referenced by: {refs}".format(
                version_no=version.version_no,
                refs=refs,
            ),
            status_code=409,
        )
    project_links = (
        db.query(SddManagementProjectProduct, SddManagementProject)
        .join(SddManagementProject, SddManagementProject.id == SddManagementProjectProduct.project_id)
        .filter(SddManagementProjectProduct.product_version_id == version.id)
        .all()
    )
    if project_links:
        refs = "; ".join(f"project '{project.name}'" for _, project in project_links)
        raise ProductServiceError(
            "Cannot delete version '{version_no}' of product '{product_name}' because it is still "
            "referenced by: {refs}".format(
                version_no=version.version_no,
                product_name=version.product.name if version.product else version.product_id,
                refs=refs,
            ),
            status_code=409,
        )
    db.delete(version)
    db.commit()


def bind_version_repo(
    db: Session,
    version: SddManagementProductVersion,
    *,
    repository_id: str,
    ref_type: str,
    ref_name: str,
    creator_id: Optional[str] = None,
) -> SddManagementProductVersionRepo:
    repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
    if not repository:
        raise ProductServiceError("Repository not found", status_code=404)
    if version.product:
        product = version.product
        if product.product_type == ProductType.OOTB and repository.repo_type != RepositoryType.OOTB:
            raise ProductServiceError(
                "OOTB product can only bind OOTB repositories",
                status_code=400,
            )
        if product.product_type == ProductType.CUSTOM:
            if repository.repo_type == RepositoryType.OOTB:
                # Allow overriding an OOTB repository only when it is part of
                # the referenced baseline version; arbitrary OOTB repos are not
                # allowed in custom products.
                baseline_binding = None
                if version.baseline_product_version_id:
                    baseline_binding = (
                        db.query(SddManagementProductVersionRepo)
                        .filter(
                            SddManagementProductVersionRepo.product_version_id == version.baseline_product_version_id,
                            SddManagementProductVersionRepo.repository_id == repository.id,
                        )
                        .first()
                    )
                if not baseline_binding:
                    raise ProductServiceError(
                        "Custom product can only override OOTB repositories from its baseline version",
                        status_code=400,
                    )
            elif repository.repo_type != RepositoryType.CUSTOM:
                raise ProductServiceError(
                    "Custom product can only bind custom repositories",
                    status_code=400,
                )

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
        ref_type=normalized_ref_type,
        ref_name=normalized_ref_name,
        created_by=creator_id,
    )
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


def update_version_repo_ref(
    db: Session,
    version: SddManagementProductVersion,
    *,
    repository_id: str,
    ref_type: str,
    ref_name: str,
) -> SddManagementProductVersionRepo:
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

    normalized_ref_name = str(ref_name or "").strip()
    normalized_ref_type = _normalize_ref_type(ref_type)
    if not normalized_ref_name:
        raise ProductServiceError("ref_name is required", status_code=400)

    repository = binding.repository or db.query(SddManagementRepository).filter(
        SddManagementRepository.id == repository_id
    ).first()
    if not repository:
        raise ProductServiceError("Repository not found", status_code=404)

    # Revalidate the new branch/tag against the remote before saving.
    git_ref_service.validate_ref_exists(
        repository.git_url,
        normalized_ref_type.value,
        normalized_ref_name,
    )
    binding.ref_type = normalized_ref_type
    binding.ref_name = normalized_ref_name
    db.commit()
    db.refresh(binding)
    return binding


def update_version_repo_refs_batch(
    db: Session,
    version: SddManagementProductVersion,
    *,
    ref_type: str,
    ref_name: str,
    scope: str = "custom",
) -> List[SddManagementProductVersionRepo]:
    normalized_scope = str(scope or "custom").strip().lower()
    if normalized_scope not in {"custom", "baseline"}:
        raise ProductServiceError("scope must be 'custom' or 'baseline'", status_code=400)

    normalized_ref_type = _normalize_ref_type(ref_type)
    normalized_ref_name = str(ref_name or "").strip()
    if not normalized_ref_name:
        raise ProductServiceError("ref_name is required", status_code=400)

    if normalized_scope == "baseline":
        baseline = version.baseline_version
        if not baseline:
            raise ProductServiceError(
                "This version does not reference a baseline version",
                status_code=400,
            )
        bindings = list(baseline.repo_bindings or [])
    else:
        bindings = (
            db.query(SddManagementProductVersionRepo)
            .options(joinedload(SddManagementProductVersionRepo.repository))
            .filter(SddManagementProductVersionRepo.product_version_id == version.id)
            .all()
        )

    if not bindings:
        raise ProductServiceError(
            "No repository bindings found in the selected scope",
            status_code=400,
        )

    touched: List[SddManagementProductVersionRepo] = []
    for binding in bindings:
        repository = binding.repository
        if not repository:
            continue
        git_ref_service.validate_ref_exists(
            repository.git_url,
            normalized_ref_type.value,
            normalized_ref_name,
        )
        binding.ref_type = normalized_ref_type
        binding.ref_name = normalized_ref_name
        touched.append(binding)

    db.commit()
    for binding in touched:
        db.refresh(binding)
    return touched


def add_baseline_exclusion(
    db: Session,
    version: SddManagementProductVersion,
    *,
    repository_id: str,
    creator_id: Optional[str] = None,
) -> SddManagementProductVersionBaselineExclusion:
    if not version.baseline_product_version_id:
        raise ProductServiceError(
            "Only custom versions with a baseline version can exclude repositories",
            status_code=400,
        )
    repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
    if not repository:
        raise ProductServiceError("Repository not found", status_code=404)
    baseline_binding = (
        db.query(SddManagementProductVersionRepo)
        .filter(
            SddManagementProductVersionRepo.product_version_id == version.baseline_product_version_id,
            SddManagementProductVersionRepo.repository_id == repository.id,
        )
        .first()
    )
    if not baseline_binding:
        raise ProductServiceError(
            "Repository is not in the baseline version bindings",
            status_code=400,
        )
    existing = (
        db.query(SddManagementProductVersionBaselineExclusion)
        .filter(
            SddManagementProductVersionBaselineExclusion.product_version_id == version.id,
            SddManagementProductVersionBaselineExclusion.repository_id == repository.id,
        )
        .first()
    )
    if existing:
        raise ProductServiceError("Repository is already excluded", status_code=409)
    exclusion = SddManagementProductVersionBaselineExclusion(
        product_version_id=version.id,
        repository_id=repository.id,
        created_by=creator_id,
    )
    db.add(exclusion)
    db.commit()
    db.refresh(exclusion)
    return exclusion


def remove_baseline_exclusion(
    db: Session,
    version: SddManagementProductVersion,
    repository_id: str,
) -> None:
    exclusion = (
        db.query(SddManagementProductVersionBaselineExclusion)
        .filter(
            SddManagementProductVersionBaselineExclusion.product_version_id == version.id,
            SddManagementProductVersionBaselineExclusion.repository_id == repository_id,
        )
        .first()
    )
    if not exclusion:
        raise ProductServiceError("Baseline exclusion not found", status_code=404)
    db.delete(exclusion)
    db.commit()


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


__all__ = [
    "ProductServiceError",
    "serialize_product",
    "serialize_product_detail",
    "serialize_version",
    "list_products",
    "get_product",
    "get_version",
    "create_product",
    "update_product",
    "add_base_repo",
    "remove_base_repo",
    "delete_product",
    "create_version",
    "update_version",
    "delete_version",
    "bind_version_repo",
    "update_version_repo_ref",
    "update_version_repo_refs_batch",
    "add_baseline_exclusion",
    "remove_baseline_exclusion",
    "resolve_effective_version_bindings",
    "unbind_version_repo",
]
