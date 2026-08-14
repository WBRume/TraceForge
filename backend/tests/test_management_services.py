"""
Management domain service tests: products/versions/bindings, project lifecycle,
releases, org tree and repository registration.
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
    org_service,
    product_service,
    project_service,
    repository_service,
)
from app.domains.management.models.management import (  # noqa: E402
    ProjectLifecycleStatus,
)

# Register every mapped model for create_all completeness.
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


def _seed_user(db: "Session") -> User:
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
    def test_create_product_and_versions(self, db_session):
        db = db_session
        product = product_service.create_product(
            db, name="Billing", code="BILLING", product_line="Billing", creator_id="user-1"
        )
        assert product.code == "BILLING"

        version = product_service.create_version(
            db, product, version_no="V8R21", status="ACTIVE", creator_id="user-1"
        )
        assert version.version_no == "V8R21"

        detail = product_service.serialize_product_detail(product_service.get_product(db, product.id))
        assert len(detail["versions"]) == 1
        assert detail["versions"][0]["repo_bindings"] == []

    def test_duplicate_product_code_conflicts(self, db_session):
        db = db_session
        product_service.create_product(db, name="A", code="DUP", creator_id="user-1")
        with pytest.raises(product_service.ProductServiceError) as exc_info:
            product_service.create_product(db, name="B", code="DUP", creator_id="user-1")
        assert exc_info.value.status_code == 409

    def test_bind_version_repo_validates_branch(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = product_service.create_version(db, product, version_no="v1", creator_id="user-1")
        repo = _seed_repository(db)

        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_branch_exists"
        ) as validate_branch:
            binding = product_service.bind_version_repo(
                db, version, repository_id=repo.id, branch_name="release/v8r21", creator_id="user-1"
            )
            validate_branch.assert_called_once_with(repo.git_url, "release/v8r21")
        assert binding.branch_name == "release/v8r21"

        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_branch_exists",
            side_effect=__import__(
                "app.domains.management.services.git_ref_service", fromlist=["GitRefAccessError"]
            ).GitRefAccessError("Branch 'nope' does not exist", status_code=409),
        ):
            with pytest.raises(Exception):
                product_service.bind_version_repo(
                    db, version, repository_id=repo.id, branch_name="nope", creator_id="user-1"
                )

    def test_unbind_version_repo(self, db_session):
        db = db_session
        product = product_service.create_product(db, name="P", code="P", creator_id="user-1")
        version = product_service.create_version(db, product, version_no="v1", creator_id="user-1")
        repo = _seed_repository(db)
        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_branch_exists"
        ):
            product_service.bind_version_repo(
                db, version, repository_id=repo.id, branch_name="main", creator_id="user-1"
            )
        product_service.unbind_version_repo(db, version, repo.id)
        refreshed = product_service.get_version(db, product.id, version.id)
        assert len(refreshed.repo_bindings) == 0


class TestProjectService:
    def _seed_project(self, db):
        return project_service.create_project(
            db, name="Customer A", code="CUST-A", customer="Site A", organization="Dept X", creator_id="user-1"
        )

    def test_lifecycle_forward_transitions_only(self, db_session):
        db = db_session
        project = self._seed_project(db)
        assert project.lifecycle_status == ProjectLifecycleStatus.INITIATED

        project = project_service.transition_lifecycle(db, project, "DEVELOPING", "user-1")
        assert project.lifecycle_status == ProjectLifecycleStatus.DEVELOPING

        # Skipping a state is rejected.
        with pytest.raises(project_service.ProjectServiceError) as exc_info:
            project_service.transition_lifecycle(db, project, "MAINTAINING", "user-1")
        assert exc_info.value.status_code == 409

        project = project_service.transition_lifecycle(db, project, "DELIVERING", "user-1")
        project = project_service.transition_lifecycle(db, project, "MAINTAINING", "user-1")
        project = project_service.transition_lifecycle(db, project, "RETIRED", "user-1")
        assert project.lifecycle_status == ProjectLifecycleStatus.RETIRED

        with pytest.raises(project_service.ProjectServiceError):
            project_service.transition_lifecycle(db, project, "DEVELOPING", "user-1")

    def test_create_release_with_ootb_and_custom_repos(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        version = product_service.create_version(db, product, version_no="V8R21", creator_id="user-1")
        ootb_repo = _seed_repository(db, name="billing-core")
        custom_repo = _seed_repository(db, name="customer-extension", repo_type="CUSTOM",
                                       git_url="https://git.example.com/customer-extension.git")

        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_branch_exists"
        ):
            product_service.bind_version_repo(
                db, version, repository_id=ootb_repo.id, branch_name="release/v8r21", creator_id="user-1"
            )

        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_branch_exists"
        ) as validate_branch:
            release = project_service.create_release(
                db,
                project,
                release_no="R1",
                name="First Release",
                product_id=product.id,
                product_version_id=version.id,
                custom_repos=[{"repository_id": custom_repo.id, "branch_name": "feature/a"}],
                creator_id="user-1",
            )
            validate_branch.assert_called_once_with(custom_repo.git_url, "feature/a")

        payload = project_service.serialize_release(release)
        kinds = {item["repo_kind"]: item for item in payload["repos"]}
        assert kinds["OOTB"]["branch_name"] == "release/v8r21"
        assert kinds["CUSTOM"]["branch_name"] == "feature/a"

    def test_resolve_project_repo_set(self, db_session):
        db = db_session
        project = self._seed_project(db)
        product = product_service.create_product(db, name="Billing", code="BILLING", creator_id="user-1")
        version = product_service.create_version(db, product, version_no="V8R21", creator_id="user-1")
        ootb_repo = _seed_repository(db, name="billing-core")
        custom_repo = _seed_repository(db, name="customer-extension", repo_type="CUSTOM",
                                       git_url="https://git.example.com/customer-extension.git")

        with mock.patch(
            "app.domains.management.services.product_service.git_ref_service.validate_branch_exists"
        ):
            product_service.bind_version_repo(
                db, version, repository_id=ootb_repo.id, branch_name="release/v8r21", creator_id="user-1"
            )
        project_service.add_product_dep(db, project, product_id=product.id, product_version_id=version.id, creator_id="user-1")
        with mock.patch(
            "app.domains.management.services.project_service.git_ref_service.validate_branch_exists"
        ):
            project_service.associate_repository(
                db, project, repository_id=custom_repo.id, branch_name="main", creator_id="user-1"
            )

        repo_set = project_service.resolve_project_repo_set(db, project)
        by_kind = {item["repo_kind"]: item for item in repo_set}
        assert by_kind["OOTB"]["branch_name"] == "release/v8r21"
        assert by_kind["CUSTOM"]["repository_name"] == "customer-extension"

        repo_set = project_service.resolve_project_repo_set(
            db, project, branch_overrides={ootb_repo.id: "hotfix/x"}
        )
        assert {item["repo_kind"]: item["branch_name"] for item in repo_set}["OOTB"] == "hotfix/x"


class TestOrgService:
    def test_org_tree_build_and_repo_placement(self, db_session):
        db = db_session
        product_line = org_service.create_node(db, parent_id=None, name="Billing 产品线", node_type="PRODUCT_LINE")
        group = org_service.create_node(db, parent_id=product_line.id, name="Billing 项目组", node_type="PROJECT_GROUP")
        repo = _seed_repository(db)
        repository_service.update_repository(db, repo, org_node_id=group.id)

        tree = org_service.build_org_tree(db)
        assert tree[0]["name"] == "Billing 产品线"
        assert tree[0]["children"][0]["name"] == "Billing 项目组"
        assert tree[0]["children"][0]["repositories"][0]["name"] == "billing-core"

    def test_delete_node_with_repositories_conflicts(self, db_session):
        db = db_session
        group = org_service.create_node(db, parent_id=None, name="G", node_type="PROJECT_GROUP")
        repo = _seed_repository(db)
        repository_service.update_repository(db, repo, org_node_id=group.id)
        with pytest.raises(org_service.OrgServiceError) as exc_info:
            org_service.delete_node(db, group)
        assert exc_info.value.status_code == 409

    def test_project_group_cannot_nest(self, db_session):
        db = db_session
        group = org_service.create_node(db, parent_id=None, name="G", node_type="PROJECT_GROUP")
        with pytest.raises(org_service.OrgServiceError):
            org_service.create_node(db, parent_id=group.id, name="child", node_type="PROJECT_GROUP")


class TestRepositoryService:
    def test_repository_crud_and_unique_url(self, db_session):
        db = db_session
        repo = _seed_repository(db)
        assert repo.repo_type.value == "OOTB"

        with pytest.raises(repository_service.RepositoryServiceError):
            _seed_repository(db, name="dup", git_url="https://git.example.com/billing-core.git")

        updated = repository_service.update_repository(db, repo, name="billing-core-renamed")
        assert updated.name == "billing-core-renamed"

        repository_service.delete_repository(db, updated)
        assert repository_service.get_repository(db, updated.id) is None
