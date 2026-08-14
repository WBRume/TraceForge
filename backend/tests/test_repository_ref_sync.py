"""
Repository git ref sync / validation tests (git_ref_service + repository service).
"""

import os
import sys
import unittest
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402
from app.domains.management.services.git_ref_service import (  # noqa: E402
    GitRefAccessError,
    fetch_remote_refs,
    parse_ls_remote_output,
    sync_repository_refs,
    validate_branch_exists,
    validate_repository_accessible,
)
from app.domains.management.services import repository_service  # noqa: E402

import app.models.user  # noqa: E402,F401
import app.models.management  # noqa: E402,F401
import app.models.workspace_repository  # noqa: E402,F401
import app.models.task_repository  # noqa: E402,F401
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


LS_REMOTE_OUTPUT = (
    "abc123\tHEAD\n"
    "abc123\trefs/heads/main\n"
    "def456\trefs/heads/release/v8r21\n"
    "111222\trefs/tags/v8r21.0\n"
    "333444\trefs/tags/v8r21.1\n"
)


class ParseRemoteRefsTest(unittest.TestCase):
    def test_parse_output(self):
        entries = parse_ls_remote_output(LS_REMOTE_OUTPUT)
        self.assertEqual(entries, [
            ("BRANCH", "main", "abc123"),
            ("BRANCH", "release/v8r21", "def456"),
            ("TAG", "v8r21.0", "111222"),
            ("TAG", "v8r21.1", "333444"),
        ])

    def test_fetch_remote_refs_raises_on_failure(self):
        result = mock.Mock()
        result.returncode = 128
        result.stderr = "fatal: repository not found"
        result.stdout = ""
        with mock.patch(
            "app.domains.management.services.git_ref_service._run_ls_remote",
            return_value=result,
        ):
            with self.assertRaises(GitRefAccessError) as ctx:
                fetch_remote_refs("https://git.example.com/missing.git")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_branch_exists(self):
        result = mock.Mock()
        result.returncode = 0
        result.stdout = LS_REMOTE_OUTPUT
        result.stderr = ""
        with mock.patch(
            "app.domains.management.services.git_ref_service._run_ls_remote",
            return_value=result,
        ):
            validate_branch_exists("https://git.example.com/r.git", "release/v8r21")
            with self.assertRaises(GitRefAccessError) as ctx:
                validate_branch_exists("https://git.example.com/r.git", "nope")
        self.assertEqual(ctx.exception.status_code, 409)


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


class SyncRepositoryRefsTest(unittest.TestCase):
    def test_sync_upserts_and_removes_stale_refs(self):
        import tempfile

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)
        db = session()

        repo = repository_service.create_repository(
            db, name="r", git_url="https://git.example.com/r.git", repo_type="OOTB"
        )
        fetch_mock = mock.Mock(return_value=[
            ("BRANCH", "main", "sha1"),
            ("TAG", "v1.0", "sha2"),
        ])
        with mock.patch(
            "app.domains.management.services.git_ref_service.fetch_remote_refs",
            fetch_mock,
        ):
            result = repository_service.sync_repository_refs(db, repo)
        self.assertEqual(result["ref_count"], 2)
        self.assertIsNotNone(repo.last_synced_at)

        # Second sync replaces the ref set (tag removed, branch sha updated).
        with mock.patch(
            "app.domains.management.services.git_ref_service.fetch_remote_refs",
            mock.Mock(return_value=[("BRANCH", "main", "sha3")]),
        ):
            result = repository_service.sync_repository_refs(db, repo)
        refs = repository_service.list_repositories(db, page_size=10)[0]
        self.assertEqual(result["ref_count"], 1)

        from app.domains.management.services.git_ref_service import list_repo_refs

        rows = list_repo_refs(db, repo)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ref_sha, "sha3")
        db.close()
