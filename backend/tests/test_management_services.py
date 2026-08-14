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
    return repository_service.create_repository(
        db,
        name=name,
        git_url=git_url,
        repo_type=repo_type,
        default_branch="main",
        creator_id="user-1",
    )


class TestProductService:
    def test_product_carries_own_version(self, db_session):
        db = db_session
        product = product_service.create_product(
            db, name="Billing", code="BILLING", product_line="Billing",
            version_no="V8R21", creator_id="user-1",
        )
        assert product.version_no == "V8R21"
        payload = product_service.serialize_product(product)
        assert payload["version_no"] == "V8R21"

    def test_bind_product_repo_validates_branch(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", version_no="v1", creator_id="user-1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            binding = product_service.bind_product_repo(
                db, product, repository_id=repo.id, ref_type="BRANCH",
                ref_name="release/v8r21", creator_id="user-1",
            )
            validate_ref.assert_called_once_with(repo.git_url, "BRANCH", "release/v8r21")
        assert binding.ref_name == "release/v8r21"
        assert binding.ref_type.value == "BRANCH"

    def test_bind_product_repo_validates_tag(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", version_no="v1", creator_id="user-1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            binding = product_service.bind_product_repo(
                db, product, repository_id=repo.id, ref_type="TAG",
                ref_name="v8r21.0", creator_id="user-1",
            )
            validate_ref.assert_called_once_with(repo.git_url, "TAG", "v8r21.0")
        assert binding.ref_type.value == "TAG"

    def test_invalid_ref_type_rejected(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", version_no="v1", creator_id="user-1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ), pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.bind_product_repo(
                db, product, repository_id=repo.id, ref_type="COMMIT", ref_name="x", creator_id="user-1"
            )
        assert exc_info.value.status_code == 400

    def test_duplicate_binding_conflicts(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", version_no="v1", creator_id="user-1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_product_repo(db, product, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1")
            with pytest.raises(product_service.ProductServiceError) as exc_info:
                product_service.bind_product_repo(db, product, repository_id=repo.id, ref_type="BRANCH", ref_name="dev", creator_id="user-1")
        assert exc_info.value.status_code == 409

    def test_unbind_product_repo(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", version_no="v1", creator_id="user-1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_product_repo(db, product, repository_id=repo.id, ref_type="BRANCH", ref_name="main", creator_id="user-1")
        product_service.unbind_product_repo(db, product, repo.id)
        assert len(product_service.get_product(db, product.id).repo_bindings) == 0


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

    def test_unassigned_repositories_exposed(self, db_session):
        db = db_session
        _seed_repository(db)
        tree = repo_group_service.build_repo_group_tree(db)
        assert tree[-1]["name"] == "Unassigned"
        assert tree[-1]["repositories"][0]["name"] == "billing-core"


class TestProjectService:
    def _seed_project(self, db):
        return project_service.create_project(
            db, name="Customer A", code="CUST-A", customer="Site A", organization="Dept X", creator_id="user-1"
        )

    def test_project_lifecycle_forward_only(self, db_session):
        db = db_session
        project = self._seed_project(db)
        assert project.lifecycle_status == ProjectLifecycleStatus.INITIATED
        project = project_service.transition_lifecycle(db, project, "DEVELOPING", "user-1")
        with pytest.raises(project_service.ProjectServiceError):
            project_service.transition_lifecycle(db, project, "MAINTAINING", "user-1")

    def test_project_contains_products_with_delivery_progress(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", version_no="V8R21", creator_id="user-1")

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

    def test_duplicate_project_product_conflicts(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")
        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.add_project_product(db, project, product_id=product.id, creator_id="user-1")
        assert exc_info.value.status_code == 409

    def test_create_release_snapshots_product_bindings_and_custom_repos(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", version_no="V8R21", creator_id="user-1")
        ootb_repo = _seed_repository(db, name="billing-core")
        custom_repo = _seed_repository(db, name="customer-extension", repo_type="CUSTOM",
                                       git_url="https://git.example.com/customer-extension.git")
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_product_repo(db, product, repository_id=ootb_repo.id, ref_type="TAG", ref_name="v8r21.0", creator_id="user-1")

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
        repo_a = _seed_repository(db, name="repo-a", git_url="https://git.example.com/repo-a.git")
        repo_b = _seed_repository(db, name="repo-b", git_url="https://git.example.com/repo-b.git")
        custom_repo = _seed_repository(db, name="custom", repo_type="CUSTOM",
                                       git_url="https://git.example.com/custom.git")

        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_ref_exists"
        ):
            product_service.bind_product_repo(db, product_a, repository_id=repo_a.id, ref_type="BRANCH", ref_name="main", creator_id="user-1")
            product_service.bind_product_repo(db, product_b, repository_id=repo_b.id, ref_type="TAG", ref_name="v2.0", creator_id="user-1")
        project_service.add_project_product(db, project, product_id=product_a.id, creator_id="user-1")
        project_service.add_project_product(db, project, product_id=product_b.id, creator_id="user-1")
        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_ref_exists"
        ):
            project_service.associate_repository(db, project, repository_id=custom_repo.id, ref_name="main", creator_id="user-1")

        project = project_service.get_project(db, project.id)
        # Only product A selected: repo-a + custom repo.
        repo_set = project_service.resolve_project_repo_set(db, project, product_ids=[product_a.id])
        by_kind = {item["repo_kind"]: item for item in repo_set}
        assert set(by_kind.keys()) == {"OOTB", "CUSTOM"}
        assert by_kind["OOTB"]["repository_name"] == "repo-a"
        assert by_kind["OOTB"]["ref_name"] == "main"

        # No selection: every product binding appears.
        repo_set_all = project_service.resolve_project_repo_set(db, project, product_ids=[])
        assert len(repo_set_all) == 3

    def test_associate_repository_validates_ref(self, db_session):
        db = db_session
        project = self._seed_project(db)
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_ref_exists"
        ) as validate_ref:
            assoc = project_service.associate_repository(db, project, repository_id=repo.id, ref_type="TAG", ref_name="v1.0", creator_id="user-1")
            validate_ref.assert_called_once_with(repo.git_url, "TAG", "v1.0")
        assert assoc.ref_name == "v1.0"


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
