"""Read-only room members may observe but cannot mutate prompts or run the Agent."""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.domains.auth.models.user import WorkspaceMember, WorkspaceRole
from app.domains.task.models.pre_input import SddTaskPreInput
from tests.task.test_pre_input_ws_flow import _complete_initial_sync, _receive_business
from tests.task.test_pre_input_ws_flow import ws_env as websocket_environment

ws_env = websocket_environment


@pytest.mark.parametrize(
    "action,payload",
    [
        ("pre_input_create", {"main_text": "unauthorized"}),
        ("pre_input_edit_document", {"text": "unauthorized"}),
        ("pre_input_replace_span", {"start": 0, "end": 0, "replacement": "unauthorized"}),
        ("pre_input_mark_done", {}),
        ("pre_input_submit", {}),
        ("pre_input_cancel", {}),
        ("chat_message", {"content": "unauthorized", "client_message_id": "viewer-input"}),
    ],
)
def test_viewer_cannot_write_through_task_socket(ws_env, action, payload):
    member = ws_env.query(WorkspaceMember).filter_by(user_id="u-member").one()
    member.role = WorkspaceRole.VIEWER
    ws_env.commit()
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/task/task-1?token=u-owner") as owner:
            _complete_initial_sync(owner)
            owner.send_json(
                {"type": "pre_input_create", "payload": {"main_text": "original", "edit_permission": "ALL"}}
            )
            assert _receive_business(owner)["type"] == "pre_input_update"
        with client.websocket_connect("/ws/task/task-1?token=u-member") as viewer:
            _complete_initial_sync(viewer)
            viewer.send_json({"type": action, "payload": payload})
            denied = _receive_business(viewer)
            assert denied["type"] == ("chat_message_ack" if action == "chat_message" else "pre_input_error")
            assert "No permission" in denied["payload"]["message"]
    ws_env.expire_all()
    assert ws_env.query(SddTaskPreInput).one().main_text == "original"
