from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domains.local_resource.client import ResourceError
from app.domains.local_resource.schemas import TaskExecutionInput
from app.domains.local_resource import service


@pytest.mark.parametrize("actor,expert,operation,allowed", [("creator",False,"execute",True),("member",True,"execute",True),("member",False,"execute",False),("member",True,"generate_patch",False),("creator",False,"generate_patch",True)])
def test_permission_matrix(monkeypatch, actor, expert, operation, allowed):
    monkeypatch.setattr(service, "require_member", lambda *args: SimpleNamespace(is_expert=expert))
    monkeypatch.setattr(service, "binding", lambda *args: None)
    monkeypatch.setattr(service, "runtime_profile", lambda *args: {})
    monkeypatch.setattr(service, "require_online", lambda *args: None)
    task = SimpleNamespace(id="task", execution_location="LOCAL", creator_id="creator", workspace_id="ws")
    if allowed:
        service.require_operation(None, task, actor, operation)
    else:
        with pytest.raises(ResourceError) as error:
            service.require_operation(None, task, actor, operation)
        assert error.value.status_code == 403


def test_execution_contract():
    with pytest.raises(ValidationError):
        TaskExecutionInput(location="LOCAL")
    with pytest.raises(ValidationError):
        TaskExecutionInput(location="SERVER", resource_id="stale")
    assert TaskExecutionInput(location="LOCAL", resource_id="r", profile_revision=1).location == "LOCAL"


def test_runtime_binding_keeps_endpoints_and_allows_same_host_credential_rotation(monkeypatch):
    monkeypatch.setattr(service, "require_member", lambda *args: None)
    config = dict(workspace_id="ws", owner_user_id="owner", host_id="host", service_url="http://10.0.0.1:1",
                  resource_service_url="http://10.0.0.1:2", encrypted_credentials="old", workspace_root="G:/original", backend="opencode")
    binding = SimpleNamespace(profile_json=config, resource_id="resource")
    current = SimpleNamespace(**{**config, "encrypted_credentials": "rotated", "workspace_root": "G:/new"})
    db = SimpleNamespace(get=lambda *args: current)
    resolved = service.runtime_profile(db, binding)
    assert resolved["encrypted_credentials"] == "rotated"
    assert resolved["workspace_root"] == "G:/original"
    assert config["encrypted_credentials"] == "old"
    current.service_url = "http://10.0.0.9:1"
    assert service.runtime_profile(db, binding)["encrypted_credentials"] == "old"


def test_member_suggestion_is_draft_only_and_creator_receives_it(monkeypatch):
    from unittest.mock import AsyncMock
    from tests.task.test_task_session_sharing import _build_app, _seed, _build_db
    from app.dependencies import get_current_user
    from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
    from app.domains.task.models.session_share import TaskShareSuggestion
    from app.domains.task.models.task_event_outbox import TaskEventOutbox
    from app.domains.task.models.chat import ChatMessage
    from app.domains.task.models.chat_submission import TaskChatSubmission
    from app.domains.task.services import chat_submission_service
    engine, factory = _build_db()
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(chat_submission_service, "wake_event_publisher", AsyncMock())
    with factory() as db:
        owner, _, task = _seed(db)
        task.execution_location = "LOCAL"
        member = User(id="member", email="member@test.local", hashed_password="x", display_name="Member")
        db.add(member)
        db.add(WorkspaceMember(workspace_id="ws-1", user_id="member", role=WorkspaceRole.OWNER, is_expert=False))
        db.commit()
        app = _build_app(db)
        app.dependency_overrides[get_current_user] = lambda: db.get(User, "member")
        client = TestClient(app)
        url = "/api/workspaces/ws-1/tasks/task-1/member-suggestions"
        body = {"content": "Please check the fork", "client_submission_id": "first"}
        response = client.post(url, json=body)
        assert response.status_code == 200, response.text
        assert client.post(url, json=body).json()["submission_id"] == response.json()["submission_id"]
        assert db.query(TaskShareSuggestion).count() == 1
        assert db.query(TaskEventOutbox).count() == 1
        assert db.query(ChatMessage).count() == 3
        assert db.query(TaskChatSubmission).count() == 0
        row = db.query(TaskShareSuggestion).one()
        assert row.recipient_user_id == "owner-1"
        assert row.source_kind == "MEMBER"
        assert row.sender_user_id == "member"
        app.dependency_overrides[get_current_user] = lambda: db.get(User, "owner-1")
        inbox = client.get("/api/workspaces/ws-1/tasks/task-1/share-suggestions")
        assert inbox.status_code == 200
        assert inbox.json()["items"][0]["original_content"] == body["content"]
    engine.dispose()


def test_local_preinput_has_no_deadline_or_auto_submit(monkeypatch):
    monkeypatch.setattr(service, "binding", lambda *args: None)
    monkeypatch.setattr(service, "runtime_profile", lambda *args: {})
    monkeypatch.setattr(service, "require_online", lambda *args: None)
    from tests.task.test_pre_input_service import _seed
    from tests.workspace_asset.test_workspace_asset_boundary import _build_db
    from app.domains.task.models.task import SddTask
    from app.domains.task.models.pre_input import SddTaskPreInput
    from app.domains.task.services import pre_input_service as pre
    from datetime import datetime
    engine, factory = _build_db()
    with factory() as db:
        _seed(db)
        db.get(SddTask, "task-1").execution_location = "LOCAL"
        db.commit()
        result = pre._create_pre_input_sync(db, task_id="task-1", creator_id="u-owner", main_text="Check", mentioned_user_ids=[], edit_permission="ALL", wait_seconds=1)
        row = db.get(SddTaskPreInput, result["pre_input_id"])
        assert row.deadline_at is None
        assert not pre._maybe_auto_submit(db, row)
        with pytest.raises(pre.PreInputError):
            pre._claim_submit_sync(db, pre_input_id=row.id, actor_user_id="u-owner", reason="timeout", now=datetime.utcnow())
        with pytest.raises(pre.PreInputError):
            pre._claim_submit_sync(db, pre_input_id=row.id, actor_user_id="u-member", reason="manual", now=datetime.utcnow())
    engine.dispose()


def test_incremental_migration_preserves_server_task():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[2] / "alembic/versions/c924a10b37ef_local_resource_execution.py"
    spec = importlib.util.spec_from_file_location("local_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for name in ("users", "workspaces", "sdd_task_share_suggestions"):
        sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table("sdd_tasks", metadata, sa.Column("id", sa.String(36), primary_key=True), sa.Column("project_path", sa.String(500), nullable=False))
    sa.Table("sdd_task_pre_inputs", metadata, sa.Column("id", sa.String(36), primary_key=True), sa.Column("deadline_at", sa.DateTime(), nullable=False))
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(sa.text("INSERT INTO sdd_tasks VALUES ('existing', '/keep')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(sa.text("SELECT execution_location,project_path FROM sdd_tasks")).one() == ("SERVER", "/keep")
        migration.downgrade()
        assert connection.execute(sa.text("SELECT id,project_path FROM sdd_tasks")).one() == ("existing", "/keep")
    engine.dispose()


def test_task_binding_does_not_wait_for_remote_git_or_provider(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    row = SimpleNamespace(id="resource", backend="opencode", profile_revision=2)
    monkeypatch.setattr(service, "owned", lambda *args: row)
    monkeypatch.setattr("app.agents.selection.resolve_workspace_backend", lambda *args: "opencode")
    monkeypatch.setattr(service, "profile", lambda row: {"host_id": "host", "repositories_json": [{"repository_id": "repo"}]})
    verify = Mock(side_effect=AssertionError("network checks must run in provisioning"))
    monkeypatch.setattr(service, "verify", verify)
    task = SimpleNamespace(id="task", creator_id="user", workspace_id="ws", repo_bindings=[SimpleNamespace(repository_id="repo")])
    db = Mock()
    service.bind_task(db, task, SimpleNamespace(resource_id="resource", profile_revision=2))
    assert task.execution_location == "LOCAL"
    assert db.add.call_args.args[0].profile_json["host_id"] == "host"
    verify.assert_not_called()


def test_provision_checks_connection_before_creating_worktree(monkeypatch):
    from unittest.mock import Mock
    row = SimpleNamespace(profile_json={"repositories_json": []})
    monkeypatch.setattr(service, "binding", lambda *args: row)
    monkeypatch.setattr(service, "runtime_profile", lambda *args: row.profile_json)
    execute = Mock()
    monkeypatch.setattr(service, "execute", execute)
    def unavailable(config):
        raise ResourceError("Agent unavailable")
    monkeypatch.setattr(service, "verify_connection", unavailable)
    with pytest.raises(ResourceError):
        service.provision_task(Mock(), SimpleNamespace(id="task", repo_bindings=[]))
    execute.assert_not_called()


def test_provision_pins_verified_host_before_creating_worktree(monkeypatch):
    from unittest.mock import Mock
    row = SimpleNamespace(profile_json={"workspace_root": "/work", "repositories_json": []}, receipt_json=None)
    monkeypatch.setattr(service, "binding", lambda *args: row)
    monkeypatch.setattr(service, "runtime_profile", lambda *args: row.profile_json)
    monkeypatch.setattr(service, "verify_connection", lambda config: {"host_id": "verified-host"})
    def execute(db, task, kind, payload, operation_id):
        assert row.profile_json["host_id"] == "verified-host"
        return {"task_root": "/work/task", "repositories": []}
    monkeypatch.setattr(service, "execute", execute)
    result = service.provision_task(Mock(), SimpleNamespace(id="task", repo_bindings=[]))
    assert result == row.receipt_json
