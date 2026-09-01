"""
Management domain service tests (restructured): products as versions with
tag/branch repo bindings, repo groups, projects with per-product delivery
progress and releases.
"""

import os
import sys
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User  # noqa: E402
from app.domains.management.services import (  # noqa: E402
    product_service,
    project_service,
    repo_group_service,
    repository_service,
)
from app.domains.management.models.management import (  # noqa: E402
    ProjectLifecycleStatus,
    SddManagementRepository,
)

# Register every mapped model for create_all completeness.
import app.models.user  # noqa: E402,F401
import app.models.task  # noqa: E402,F401
import app.models.asset  # noqa: E402,F401
import app.models.chat  # noqa: E402,F401
import app.models.log  # noqa: E402,F401
import app.models.test_result  # noqa: E402,F401
import app.models.metric  # noqa: E402,F401
import app.models.skill  # noqa: E402,F401
import app.models.api_mock  # noqa: E402,F401
import app.models.ai_job  # noqa: E402,F401
import app.models.workspace_asset  # noqa: E402,F401
import app.models.task_change  # noqa: E402,F401
import app.models.task_cli_bootstrap  # noqa: E402,F401
import app.models.provision_job  # noqa: E402,F401
import app.models.management  # noqa: E402,F401
import app.models.workspace_repository  # noqa: E402,F401
import app.models.task_repository  # noqa: E402,F401


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    db = session()
    try:
        yield db
    finally:
        db.close()


def _seed_user(db) -> User:
    user = User(id="user-1", email="admin@example.com", hashed_password="x", display_name="Admin", is_admin=True)
    db.add(user)
    db.commit()
    return user


def _seed_repository(db, name="billing-core", git_url="https://git.example.com/billing-core.git", repo_type="OOTB"):
    group = repo_group_service.create_group(db, name=f"Seed 组 {name}")
    return repository_service.create_repository(
        db,
        name=name,
        git_url=git_url,
        repo_type=repo_type,
        default_branch="main",
        group_id=group.id,
        creator_id="user-1",
    )


def _seed_product_version(db, product, version_no="V1", **kwargs):
    return product_service.create_version(
        db,
        product,
        version_no=version_no,
        creator_id="user-1",
        **kwargs,
    )


class TestProductService:
    def test_product_evolves_through_versions(self, db_session):
        db = db_session
        product = product_service.create_product(
            db, name="Billing", code="BILLING", product_line="Billing", creator_id="user-1"
        )
        # New products start without versions.
        assert len(product_service.get_product(db, product.id).versions) == 0

        version = _seed_product_version(db, product, version_no="V8R21")
        assert version.version_no == "V8R21"
        payload = product_service.serialize_product(product_service.get_product(db, product.id))
        assert payload["version_no"] == "V8R21"
        # A second version starts the next evolution cycle.
        version = product_service.create_version(db, product, version_no="V9R0", creator_id="user-1")
        assert version.version_no == "V9R0"
        payload = product_service.serialize_product(product_service.get_product(db, product.id))
        assert payload["version_no"] == "V9R0"

    def test_serialize_product_detail_with_versions_includes_effective_bindings(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = _seed_product_version(db, product, version_no="V1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, version, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )
        detail = product_service.serialize_product_detail(product_service.get_product(db, product.id))
        assert len(detail["versions"]) == 1
        assert len(detail["versions"][0]["effective_repo_bindings"]) == 1

    def test_product_base_repos_are_changeable(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        repo_a = _seed_repository(db, name="repo-a", git_url="https://git.example.com/repo-a.git")
        repo_b = _seed_repository(db, name="repo-b", git_url="https://git.example.com/repo-b.git")

        product_service.add_base_repo(db, product, repository_id=repo_a.id, creator_id="user-1")
        product_service.add_base_repo(db, product, repository_id=repo_b.id, creator_id="user-1")
        detail = product_service.serialize_product_detail(product_service.get_product(db, product.id))
        assert {item["repository_name"] for item in detail["base_repos"]} == {"repo-a", "repo-b"}

        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.add_base_repo(db, product, repository_id=repo_a.id, creator_id="user-1")
        assert exc_info.value.status_code == 409

        product_service.remove_base_repo(db, product, repo_a.id)
        detail = product_service.serialize_product_detail(product_service.get_product(db, product.id))
        assert [item["repository_name"] for item in detail["base_repos"]] == ["repo-b"]

    def test_create_version_inherits_product_base_repos(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        repo_a = _seed_repository(db, name="repo-a", git_url="https://git.example.com/repo-a.git")
        repo_b = _seed_repository(db, name="repo-b", git_url="https://git.example.com/repo-b.git")
        product_service.add_base_repo(db, product, repository_id=repo_a.id, creator_id="user-1")
        product_service.add_base_repo(db, product, repository_id=repo_b.id, creator_id="user-1")

        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            version = product_service.create_version(
                db,
                product,
                version_no="V1.0",
                inherit_product_repos=True,
                inherit_ref_type="BRANCH",
                inherit_ref_name="branch_v0.0.1",
                creator_id="user-1",
            )
        assert {item.repository_id for item in version.repo_bindings} == {repo_a.id, repo_b.id}
        assert all(item.ref_name == "branch_v0.0.1" for item in version.repo_bindings)
        assert validate_ref.call_count == 2

    def test_repo_type_restrictions_by_product_type(self, db_session):
        db = db_session
        ootb = product_service.create_product(
            db, name="OOTB Base", code="OOTB", creator_id="user-1", product_type="OOTB"
        )
        ootb_version = _seed_product_version(db, ootb, version_no="V1")
        custom = product_service.create_product(
            db, name="Customer Custom", code="CUSTOM", creator_id="user-1",
            product_type="CUSTOM", baseline_product_id=ootb.id,
        )
        custom_version = product_service.create_version(
            db, custom, version_no="C1", baseline_product_version_id=ootb_version.id, creator_id="user-1"
        )
        ootb_repo = _seed_repository(db, name="ootb-repo", git_url="https://git.example.com/ootb.git", repo_type="OOTB")
        custom_repo = _seed_repository(db, name="custom-repo", git_url="https://git.example.com/custom.git", repo_type="CUSTOM")

        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.add_base_repo(db, ootb, repository_id=custom_repo.id, creator_id="user-1")
        assert exc_info.value.status_code == 400

        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.add_base_repo(db, custom, repository_id=ootb_repo.id, creator_id="user-1")
        assert exc_info.value.status_code == 400

        with pytest.raises(product_service.ProductServiceError):
            product_service.bind_version_repo(
                db, ootb_version, repository_id=custom_repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )
        with pytest.raises(product_service.ProductServiceError):
            product_service.bind_version_repo(
                db, custom_version, repository_id=ootb_repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )

    def test_custom_product_version_binds_baseline_version_dynamic(self, db_session):
        db = db_session
        baseline = product_service.create_product(
            db, name="OOTB Base", code="OOTB", creator_id="user-1", product_type="OOTB"
        )
        baseline_version = _seed_product_version(db, baseline, version_no="V1")
        repo_a = _seed_repository(db, name="repo-a", git_url="https://git.example.com/repo-a.git")
        repo_b = _seed_repository(db, name="repo-b", git_url="https://git.example.com/repo-b.git")
        custom_repo = _seed_repository(
            db, name="custom-repo", git_url="https://git.example.com/custom.git", repo_type="CUSTOM"
        )
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, baseline_version, repository_id=repo_a.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )
            product_service.bind_version_repo(
                db, baseline_version, repository_id=repo_b.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )

        custom = product_service.create_product(
            db, name="Customer Custom", code="CUSTOM", creator_id="user-1",
            product_type="CUSTOM", baseline_product_id=baseline.id,
        )
        custom_version = product_service.create_version(
            db,
            custom,
            version_no="C1",
            baseline_product_version_id=baseline_version.id,
            creator_id="user-1",
        )
        effective = product_service.resolve_effective_version_bindings(custom_version)
        assert {item["repository_id"] for item in effective} == {repo_a.id, repo_b.id}
        assert all(item["source"] == "baseline" for item in effective)

        # Custom product can override a baseline OOTB repository ref.
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, custom_version, repository_id=repo_a.id, ref_type="TAG", ref_name="v1.0", creator_id="user-1"
            )
        effective = product_service.resolve_effective_version_bindings(custom_version)
        repo_a_item = next(item for item in effective if item["repository_id"] == repo_a.id)
        assert repo_a_item["source"] == "custom_override"
        assert repo_a_item["ref_name"] == "v1.0"

        # Custom product can add its own CUSTOM repository alongside baseline repos.
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, custom_version, repository_id=custom_repo.id, ref_type="BRANCH", ref_name="dev", creator_id="user-1"
            )
        effective = product_service.resolve_effective_version_bindings(custom_version)
        custom_item = next(item for item in effective if item["repository_id"] == custom_repo.id)
        assert custom_item["source"] == "custom"

        # Excluding repo_b removes it from the dynamic effective set.
        product_service.add_baseline_exclusion(db, custom_version, repository_id=repo_b.id, creator_id="user-1")
        effective = product_service.resolve_effective_version_bindings(custom_version)
        assert {item["repository_id"] for item in effective} == {repo_a.id, custom_repo.id}


    def test_serialize_custom_product_and_version_reverse_links(self, db_session):
        db = db_session
        baseline = product_service.create_product(
            db, name="OOTB Base", code="OOTB-BASE", creator_id="user-1", product_type="OOTB"
        )
        baseline_version = _seed_product_version(db, baseline, version_no="V1")
        custom = product_service.create_product(
            db, name="Customer Custom", code="CUSTOM-1", creator_id="user-1",
            product_type="CUSTOM", baseline_product_id=baseline.id,
        )
        custom_version = product_service.create_version(
            db, custom, version_no="C1", baseline_product_version_id=baseline_version.id, creator_id="user-1"
        )

        baseline_detail = product_service.serialize_product_detail(
            product_service.get_product(db, baseline.id)
        )
        assert [cp["id"] for cp in baseline_detail["custom_products"]] == [custom.id]
        baseline_version_payload = next(
            v for v in baseline_detail["versions"] if v["id"] == baseline_version.id
        )
        assert baseline_version_payload["custom_versions"][0]["id"] == custom_version.id
        assert baseline_version_payload["custom_versions"][0]["product_name"] == custom.name

        custom_payload = product_service.serialize_version(
            product_service.get_version(db, custom.id, custom_version.id)
        )
        assert custom_payload["baseline_product_id"] == baseline.id
        assert custom_payload["baseline_product_version_id"] == baseline_version.id
        assert custom_payload["baseline_product_name"] == baseline.name
        assert custom_payload["baseline_version_no"] == baseline_version.version_no

    def test_batch_update_scope_baseline(self, db_session):
        db = db_session
        ootb = product_service.create_product(
            db, name="OOTB Base", code="OOTB", creator_id="user-1", product_type="OOTB"
        )
        ootb_version = _seed_product_version(db, ootb, version_no="V1")
        repo = _seed_repository(db, name="ootb-repo", git_url="https://git.example.com/ootb.git")
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, ootb_version, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )
        custom = product_service.create_product(
            db, name="Customer Custom", code="CUSTOM", creator_id="user-1",
            product_type="CUSTOM", baseline_product_id=ootb.id,
        )
        custom_version = product_service.create_version(
            db, custom, version_no="C1", baseline_product_version_id=ootb_version.id, creator_id="user-1"
        )
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.update_version_repo_refs_batch(
                db,
                custom_version,
                ref_type="TAG",
                ref_name="v2.0",
                scope="baseline",
            )
        refreshed = product_service.get_version(db, ootb.id, ootb_version.id)
        assert refreshed.repo_bindings[0].ref_type.value == "TAG"
        assert refreshed.repo_bindings[0].ref_name == "v2.0"

    def test_delete_baseline_product_referenced_by_custom_conflicts(self, db_session):
        db = db_session
        baseline = product_service.create_product(
            db, name="OOTB Base", code="OOTB", creator_id="user-1", product_type="OOTB"
        )
        product_service.create_product(
            db, name="Customer Custom", code="CUSTOM", creator_id="user-1",
            product_type="CUSTOM", baseline_product_id=baseline.id,
        )
        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.delete_product(db, baseline)
        assert exc_info.value.status_code == 409
        assert "custom product 'Customer Custom'" in str(exc_info.value)

    def test_new_version_inherits_source_bindings(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version_a = _seed_product_version(db, product, version_no="A")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(db, version_a, repository_id=repo.id, ref_type="TAG", ref_name="v1.0", creator_id="user-1")
        # A1 evolves from A and inherits its repository bindings.
        version_a1 = product_service.create_version(
            db, product, version_no="A1", from_version_id=version_a.id, creator_id="user-1",
        )
        assert len(version_a1.repo_bindings) == 1
        assert version_a1.repo_bindings[0].repository_id == repo.id
        assert version_a1.repo_bindings[0].ref_name == "v1.0"

    def test_create_version_without_source_is_base_and_allows_multi_evolution(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        initial = _seed_product_version(db, product, version_no="V1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, initial, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )

        # 不选择演进来源时，作为基础版本，不继承任何仓库绑定。
        base = product_service.create_version(db, product, version_no="A", creator_id="user-1")
        assert len(base.repo_bindings) == 0

        # 支持从同一个版本多路演进。
        child1 = product_service.create_version(
            db, product, version_no="A1", from_version_id=initial.id, creator_id="user-1"
        )
        child2 = product_service.create_version(
            db, product, version_no="A2", from_version_id=initial.id, creator_id="user-1"
        )
        assert len(child1.repo_bindings) == 1
        assert len(child2.repo_bindings) == 1

    def test_version_from_other_product_rejected(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        other = product_service.create_product(db, name="Q", code="Q", creator_id="user-1")
        other_version = _seed_product_version(db, other, version_no="B")
        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.create_version(
                db, product, version_no="A1", from_version_id=other_version.id, creator_id="user-1",
            )
        assert exc_info.value.status_code == 404

    def _first_version(self, db, product):
        loaded = product_service.get_product(db, product.id)
        if not loaded.versions:
            return _seed_product_version(db, loaded)
        return loaded.versions[0]

    def test_bind_version_repo_validates_branch(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = self._first_version(db, product)
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            binding = product_service.bind_version_repo(
                db, version, repository_id=repo.id, ref_type="BRANCH",
                ref_name="release/v8r21", creator_id="user-1",
            )
            validate_ref.assert_called_once_with(repo.git_url, "BRANCH", "release/v8r21")
        assert binding.ref_name == "release/v8r21"
        assert binding.ref_type.value == "BRANCH"

    def test_bind_version_repo_validates_tag(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = self._first_version(db, product)
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            binding = product_service.bind_version_repo(
                db, version, repository_id=repo.id, ref_type="TAG",
                ref_name="v8r21.0", creator_id="user-1",
            )
            validate_ref.assert_called_once_with(repo.git_url, "TAG", "v8r21.0")
        assert binding.ref_type.value == "TAG"

    def test_update_version_repo_ref(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = _seed_product_version(db, product, version_no="v1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            product_service.bind_version_repo(
                db, version, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )
            updated = product_service.update_version_repo_ref(
                db,
                version,
                repository_id=repo.id,
                ref_type="TAG",
                ref_name="v8r21.0",
            )
            validate_ref.assert_any_call(repo.git_url, "TAG", "v8r21.0")
        assert updated.ref_type.value == "TAG"
        assert updated.ref_name == "v8r21.0"

    def test_update_version_repo_refs_batch(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = _seed_product_version(db, product, version_no="v1")
        repo_a = _seed_repository(db, name="repo-a", git_url="https://git.example.com/repo-a.git")
        repo_b = _seed_repository(db, name="repo-b", git_url="https://git.example.com/repo-b.git")
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, version, repository_id=repo_a.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )
            product_service.bind_version_repo(
                db, version, repository_id=repo_b.id, ref_type="BRANCH", ref_name="dev", creator_id="user-1"
            )
            updated = product_service.update_version_repo_refs_batch(
                db,
                version,
                ref_type="TAG",
                ref_name="v2.0",
            )
        assert len(updated) == 2
        assert all(item.ref_type.value == "TAG" for item in updated)
        assert all(item.ref_name == "v2.0" for item in updated)

    def test_invalid_ref_type_rejected(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = self._first_version(db, product)
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ), pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.bind_version_repo(
                db, version, repository_id=repo.id, ref_type="COMMIT", ref_name="x", creator_id="user-1"
            )
        assert exc_info.value.status_code == 400

    def test_duplicate_binding_conflicts(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = self._first_version(db, product)
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(db, version, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1")
            with pytest.raises(product_service.ProductServiceError) as exc_info:
                product_service.bind_version_repo(db, version, repository_id=repo.id, ref_type="BRANCH", ref_name="dev", creator_id="user-1")
        assert exc_info.value.status_code == 409

    def test_unbind_version_repo(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = self._first_version(db, product)
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(db, version, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1")
        product_service.unbind_version_repo(db, version, repo.id)
        assert len(product_service.get_product(db, product.id).versions[0].repo_bindings) == 0

    def test_delete_product_referenced_by_project_conflicts(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        _seed_product_version(db, product, version_no="v1")
        project = project_service.create_project(
            db, name="Customer A", code="CUST-A", customer="Site A", creator_id="user-1"
        )
        project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")

        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.delete_product(db, product)
        assert exc_info.value.status_code == 409
        assert "project 'Customer A'" in str(exc_info.value)

    def test_delete_product_referenced_by_release_conflicts(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        project = project_service.create_project(
            db, name="Customer A", code="CUST-A", customer="Site A", creator_id="user-1"
        )
        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_ref_exists"
        ):
            project_service.create_release(
                db,
                project,
                release_no="R1",
                name="First Release",
                product_id=product.id,
                creator_id="user-1",
            )

        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.delete_product(db, product)
        assert exc_info.value.status_code == 409
        assert "project 'Customer A' release 'R1'" in str(exc_info.value)

    def test_delete_product_version_referenced_by_project_conflicts(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = self._first_version(db, product)
        project = project_service.create_project(
            db, name="Customer A", code="CUST-A", customer="Site A", creator_id="user-1"
        )
        project_service.add_project_product(db, project, product_id=product.id, product_version_id=version.id, creator_id="user-1")

        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.delete_version(db, version)
        assert exc_info.value.status_code == 409
        assert "project 'Customer A'" in str(exc_info.value)


class TestRepoGroupService:
    def test_tree_build_and_repo_placement(self, db_session):
        db = db_session
        group = repo_group_service.create_group(db, name="Billing 基线组")
        child = repo_group_service.create_group(db, name="Web 组", parent_id=group.id)
        repo = _seed_repository(db)
        repository_service.move_repository_to_group(db, repo, child.id)

        tree = repo_group_service.build_repo_group_tree(db)
        assert tree[0]["name"] == "Billing 基线组"
        assert tree[0]["children"][0]["name"] == "Web 组"
        assert tree[0]["children"][0]["repositories"][0]["name"] == "billing-core"

    def test_delete_group_with_repos_conflicts(self, db_session):
        db = db_session
        group = repo_group_service.create_group(db, name="G")
        repo = _seed_repository(db)
        repository_service.move_repository_to_group(db, repo, group.id)
        with pytest.raises(repo_group_service.RepoGroupServiceError) as exc_info:
            repo_group_service.delete_group(db, group)
        assert exc_info.value.status_code == 409

    def test_delete_group_with_children_conflicts(self, db_session):
        db = db_session
        group = repo_group_service.create_group(db, name="G")
        repo_group_service.create_group(db, name="child", parent_id=group.id)
        with pytest.raises(repo_group_service.RepoGroupServiceError):
            repo_group_service.delete_group(db, group)

    def test_cannot_move_group_under_own_descendant(self, db_session):
        db = db_session
        parent = repo_group_service.create_group(db, name="P")
        child = repo_group_service.create_group(db, name="C", parent_id=parent.id)
        with pytest.raises(repo_group_service.RepoGroupServiceError):
            repo_group_service.update_group(db, parent, parent_id=child.id)

    def test_unassigned_repositories_not_exposed(self, db_session):
        db = db_session
        # Simulate legacy ungrouped data (no longer creatable through the service).
        repo = SddManagementRepository(
            name="legacy-ungrouped",
            git_url="https://git.example.com/legacy-ungrouped.git",
            repo_type="OOTB",
            default_branch="main",
        )
        db.add(repo)
        db.commit()
        tree = repo_group_service.build_repo_group_tree(db)
        assert all(node.get("id") is not None for node in tree)
        assert not any(node["name"] == "Unassigned" for node in tree)

    def test_create_repository_requires_group(self, db_session):
        db = db_session
        with pytest.raises(repository_service.RepositoryServiceError) as exc_info:
            repository_service.create_repository(
                db,
                name="no-group-repo",
                git_url="https://git.example.com/no-group.git",
                repo_type="OOTB",
                creator_id="user-1",
            )
        assert exc_info.value.status_code == 400

        with pytest.raises(repository_service.RepositoryServiceError) as exc_info:
            repository_service.create_repository(
                db,
                name="missing-group-repo",
                git_url="https://git.example.com/missing-group.git",
                repo_type="OOTB",
                group_id="missing-group-id",
                creator_id="user-1",
            )
        assert exc_info.value.status_code == 400


class TestProjectService:
    def _seed_project(self, db):
        return project_service.create_project(
            db, name="Customer A", code="CUST-A", customer="Site A", organization="Dept X", creator_id="user-1"
        )

    def test_project_lifecycle_allows_adjacent_backward_transition(self, db_session):
        db = db_session
        project = self._seed_project(db)
        assert project.lifecycle_status == ProjectLifecycleStatus.INITIATED
        project = project_service.transition_lifecycle(db, project, "DEVELOPING", "user-1")
        # Skipping a state is rejected.
        with pytest.raises(project_service.ProjectServiceError):
            project_service.transition_lifecycle(db, project, "MAINTAINING", "user-1")
        # A misclicked advancement can be reverted to the previous state.
        project = project_service.transition_lifecycle(db, project, "INITIATED", "user-1")
        assert project.lifecycle_status == ProjectLifecycleStatus.INITIATED

    def test_project_contains_products_with_delivery_progress(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        _seed_product_version(db, product, version_no="V8R21")

        link = project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")
        assert link.delivery_status == ProjectLifecycleStatus.INITIATED

        link = project_service.transition_project_product_delivery(db, link, "DEVELOPING", "user-1")
        assert link.delivery_status == ProjectLifecycleStatus.DEVELOPING

        # Skipping a delivery state is rejected.
        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.transition_project_product_delivery(db, link, "RETIRED", "user-1")
        assert exc_info.value.status_code == 409

        detail = project_service.serialize_project_detail(project_service.get_project(db, project.id))
        assert detail["products"][0]["delivery_status"] == "DEVELOPING"
        assert detail["products"][0]["product_version_no"] == "V8R21"

    def test_project_product_can_switch_version(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        _seed_product_version(db, product, version_no="A1")
        link = project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")
        assert link.product_version_id is not None

        version_a2 = product_service.create_version(db, product, version_no="A2", creator_id="user-1")
        link = project_service.update_project_product_version(db, link, product_version_id=version_a2.id, actor_user_id="user-1")
        assert link.product_version_id == version_a2.id
        detail = project_service.serialize_project_detail(project_service.get_project(db, project.id))
        assert detail["products"][0]["product_version_no"] == "A2"

        # Switching to a version of another product is rejected.
        other = product_service.create_product(db, name="Other", code="OTHER", creator_id="user-1")
        other_version = _seed_product_version(db, other, version_no="B1")
        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.update_project_product_version(db, link, product_version_id=other_version.id, actor_user_id="user-1")
        assert exc_info.value.status_code == 404

    def test_duplicate_project_product_conflicts(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        _seed_product_version(db, product, version_no="V1")
        project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")
        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")
        assert exc_info.value.status_code == 409

    def test_project_cannot_bind_custom_product_with_its_baseline(self, db_session):
        db = db_session
        project = self._seed_project(db)
        baseline = product_service.create_product(db, name="OOTB Billing", code="BILLING", creator_id="user-1")
        baseline_version = _seed_product_version(db, baseline, version_no="V1")
        custom = product_service.create_product(
            db,
            name="Custom Billing",
            code="CUSTOM-BILLING",
            product_type="CUSTOM",
            baseline_product_id=baseline.id,
            creator_id="user-1",
        )
        _seed_product_version(db, custom, version_no="C1", baseline_product_version_id=baseline_version.id)

        project_service.add_project_product(db, project, product_id=baseline.id, creator_id="user-1")
        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.add_project_product(db, project, product_id=custom.id, creator_id="user-1")
        assert exc_info.value.status_code == 409
        assert "baseline" in str(exc_info.value)

    def test_project_cannot_bind_baseline_product_after_custom(self, db_session):
        db = db_session
        project = self._seed_project(db)
        baseline = product_service.create_product(db, name="OOTB Billing", code="BILLING", creator_id="user-1")
        baseline_version = _seed_product_version(db, baseline, version_no="V1")
        custom = product_service.create_product(
            db,
            name="Custom Billing",
            code="CUSTOM-BILLING",
            product_type="CUSTOM",
            baseline_product_id=baseline.id,
            creator_id="user-1",
        )
        _seed_product_version(db, custom, version_no="C1", baseline_product_version_id=baseline_version.id)

        project_service.add_project_product(db, project, product_id=custom.id, creator_id="user-1")
        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.add_project_product(db, project, product_id=baseline.id, creator_id="user-1")
        assert exc_info.value.status_code == 409
        assert "baseline" in str(exc_info.value)

    def test_project_can_bind_multiple_custom_products(self, db_session):
        db = db_session
        project = self._seed_project(db)
        baseline = product_service.create_product(db, name="OOTB Billing", code="BILLING", creator_id="user-1")
        baseline_version = _seed_product_version(db, baseline, version_no="V1")
        custom_a = product_service.create_product(
            db,
            name="Custom Billing A",
            code="CUSTOM-A",
            product_type="CUSTOM",
            baseline_product_id=baseline.id,
            creator_id="user-1",
        )
        custom_b = product_service.create_product(
            db,
            name="Custom Billing B",
            code="CUSTOM-B",
            product_type="CUSTOM",
            baseline_product_id=baseline.id,
            creator_id="user-1",
        )
        _seed_product_version(db, custom_a, version_no="C1", baseline_product_version_id=baseline_version.id)
        _seed_product_version(db, custom_b, version_no="C2", baseline_product_version_id=baseline_version.id)

        project_service.add_project_product(db, project, product_id=custom_a.id, creator_id="user-1")
        project_service.add_project_product(db, project, product_id=custom_b.id, creator_id="user-1")
        detail = project_service.serialize_project_detail(project_service.get_project(db, project.id))
        assert len(detail["products"]) == 2

    def test_delete_project_with_products_conflicts(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        _seed_product_version(db, product, version_no="V1")
        project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")

        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.delete_project(db, project)
        assert exc_info.value.status_code == 409
        assert "1 product(s)" in str(exc_info.value)

    def test_delete_project_with_releases_conflicts(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_ref_exists"
        ):
            project_service.create_release(
                db,
                project,
                release_no="R1",
                name="First Release",
                product_id=product.id,
                creator_id="user-1",
            )

        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.delete_project(db, project)
        assert exc_info.value.status_code == 409
        assert "1 release(s)" in str(exc_info.value)

    def test_create_release_snapshots_product_bindings_and_custom_repos(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        version = _seed_product_version(db, product, version_no="V8R21")
        ootb_repo = _seed_repository(db, name="billing-core")
        custom_repo = _seed_repository(db, name="customer-extension", repo_type="CUSTOM",
                                       git_url="https://git.example.com/customer-extension.git")
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(db, version, repository_id=ootb_repo.id, ref_type="TAG", ref_name="v8r21.0", creator_id="user-1")

        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            release = project_service.create_release(
                db,
                project,
                release_no="R1",
                name="First Release",
                product_id=product.id,
                custom_repos=[{"repository_id": custom_repo.id, "ref_type": "BRANCH", "ref_name": "feature/a"}],
                creator_id="user-1",
            )
            validate_ref.assert_called_once_with(custom_repo.git_url, "BRANCH", "feature/a")

        payload = project_service.serialize_release(release)
        kinds = {item["repo_kind"]: item for item in payload["repos"]}
        assert kinds["OOTB"]["ref_type"] == "TAG"
        assert kinds["OOTB"]["ref_name"] == "v8r21.0"
        assert kinds["CUSTOM"]["ref_name"] == "feature/a"

    def test_resolve_project_repo_set_filters_by_products(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product_a = product_service.create_product(db, name="A", code="A", creator_id="user-1")
        product_b = product_service.create_product(db, name="B", code="B", creator_id="user-1")
        version_a = _seed_product_version(db, product_a, version_no="V1")
        version_b = _seed_product_version(db, product_b, version_no="V1")
        repo_a = _seed_repository(db, name="repo-a", git_url="https://git.example.com/repo-a.git")
        repo_b = _seed_repository(db, name="repo-b", git_url="https://git.example.com/repo-b.git")

        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(db, version_a, repository_id=repo_a.id, ref_type="BRANCH", ref_name="main", creator_id="user-1")
            product_service.bind_version_repo(db, version_b, repository_id=repo_b.id, ref_type="TAG", ref_name="v2.0", creator_id="user-1")
        project_service.add_project_product(db, project, product_id=product_a.id, creator_id="user-1")
        project_service.add_project_product(db, project, product_id=product_b.id, creator_id="user-1")

        project = project_service.get_project(db, project.id)
        # Only product A selected: only repo-a.
        repo_set = project_service.resolve_project_repo_set(db, project, product_ids=[product_a.id])
        assert len(repo_set) == 1
        assert repo_set[0]["repository_name"] == "repo-a"
        assert repo_set[0]["repo_kind"] == "OOTB"
        assert repo_set[0]["ref_name"] == "main"

        # No selection: every product binding appears.
        repo_set_all = project_service.resolve_project_repo_set(db, project, product_ids=[])
        assert len(repo_set_all) == 2

    def test_resolve_project_repo_set_reports_ootb_and_custom_kinds(self, db_session):
        db = db_session
        project = self._seed_project(db)
        ootb = product_service.create_product(
            db, name="OOTB Base", code="OOTB-BASE", creator_id="user-1", product_type="OOTB"
        )
        ootb_version = _seed_product_version(db, ootb, version_no="V1")
        ootb_repo = _seed_repository(db, name="base-repo", git_url="https://git.example.com/base.git")
        custom = product_service.create_product(
            db, name="Customer Custom", code="CUSTOM-1", creator_id="user-1",
            product_type="CUSTOM", baseline_product_id=ootb.id,
        )
        custom_version = product_service.create_version(
            db, custom, version_no="C1", baseline_product_version_id=ootb_version.id, creator_id="user-1"
        )
        custom_repo = _seed_repository(
            db, name="custom-repo", git_url="https://git.example.com/custom.git", repo_type="CUSTOM"
        )
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, ootb_version, repository_id=ootb_repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1"
            )
            product_service.bind_version_repo(
                db, custom_version, repository_id=custom_repo.id, ref_type="BRANCH", ref_name="dev", creator_id="user-1"
            )
        project_service.add_project_product(
            db, project, product_id=custom.id, product_version_id=custom_version.id, creator_id="user-1"
        )

        repo_set = project_service.resolve_project_repo_set(db, project, product_ids=[custom.id])
        kinds = {item["repo_kind"] for item in repo_set}
        assert kinds == {"OOTB", "CUSTOM"}
        assert any(item["repository_name"] == "base-repo" for item in repo_set)
        assert any(item["repository_name"] == "custom-repo" for item in repo_set)



class TestRepositoryService:
    def test_repository_crud_and_group_move(self, db_session):
        db = db_session
        repo = _seed_repository(db)
        assert repo.repo_type.value == "OOTB"

        with pytest.raises(repository_service.RepositoryServiceError):
            _seed_repository(db, name="dup", git_url="https://git.example.com/billing-core.git")

        group = repo_group_service.create_group(db, name="G1")
        moved = repository_service.move_repository_to_group(db, repo, group.id)
        assert moved.group_id == group.id
        assert moved.group.name == "G1"

        repository_service.delete_repository(db, moved)
        assert repository_service.get_repository(db, moved.id) is None

    def test_list_repositories_searches_group_subtree(self, db_session):
        db = db_session
        root = repo_group_service.create_group(db, name="Root")
        child = repo_group_service.create_group(db, name="Child", parent_id=root.id)
        grand = repo_group_service.create_group(db, name="Grand", parent_id=child.id)
        outside = repo_group_service.create_group(db, name="Outside")
        repo_root = _seed_repository(db, name="root-repo", git_url="https://git.example.com/root.git")
        repo_child = _seed_repository(db, name="child-repo", git_url="https://git.example.com/child.git")
        repo_grand = _seed_repository(db, name="grand-repo", git_url="https://git.example.com/grand.git")
        repo_out = _seed_repository(db, name="out-repo", git_url="https://git.example.com/out.git")
        repository_service.move_repository_to_group(db, repo_root, root.id)
        repository_service.move_repository_to_group(db, repo_child, child.id)
        repository_service.move_repository_to_group(db, repo_grand, grand.id)
        repository_service.move_repository_to_group(db, repo_out, outside.id)

        items, total = repository_service.list_repositories(db, group_id=root.id, page_size=100)
        assert total == 3
        assert {item["name"] for item in items} == {"root-repo", "child-repo", "grand-repo"}

        items, total = repository_service.list_repositories(db, group_id=child.id, page_size=100)
        assert total == 2
        assert {item["name"] for item in items} == {"child-repo", "grand-repo"}

        items, total = repository_service.list_repositories(
            db, group_id=root.id, keyword="grand", page_size=100
        )
        assert total == 1
        assert items[0]["name"] == "grand-repo"

    def test_delete_repository_referenced_by_product_version_conflicts(self, db_session):
        db = db_session
        repo = _seed_repository(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        version = _seed_product_version(db, product, version_no="V8R21")
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_version_repo(
                db, version, repository_id=repo.id, ref_type="TAG", ref_name="v8r21.0", creator_id="user-1"
            )

        with pytest.raises(repository_service.RepositoryServiceError) as exc_info:
            repository_service.delete_repository(db, repo)
        assert exc_info.value.status_code == 409
        assert "product 'Billing' version 'V8R21'" in str(exc_info.value)

    def test_delete_repository_referenced_by_product_base_conflicts(self, db_session):
        db = db_session
        repo = _seed_repository(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        product_service.add_base_repo(db, product, repository_id=repo.id, creator_id="user-1")

        with pytest.raises(repository_service.RepositoryServiceError) as exc_info:
            repository_service.delete_repository(db, repo)
        assert exc_info.value.status_code == 409
        assert "product 'Billing' base repositories" in str(exc_info.value)

    def test_delete_repository_referenced_by_project_release_conflicts(self, db_session):
        db = db_session
        repo = _seed_repository(db, name="customer-extension", repo_type="CUSTOM",
                                git_url="https://git.example.com/customer-extension.git")
        project = project_service.create_project(
            db, name="Customer A", code="CUST-A", customer="Site A", creator_id="user-1"
        )
        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_ref_exists"
        ):
            project_service.create_release(
                db,
                project,
                release_no="R1",
                name="First Release",
                product_id=None,
                custom_repos=[{"repository_id": repo.id, "ref_type": "BRANCH", "ref_name": "feature/a"}],
                creator_id="user-1",
            )

        with pytest.raises(repository_service.RepositoryServiceError) as exc_info:
            repository_service.delete_repository(db, repo)
        assert exc_info.value.status_code == 409
        assert "project 'Customer A' release 'R1'" in str(exc_info.value)
