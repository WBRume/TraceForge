from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.asset.models.asset import AssetType, SddAsset, SddAssetVersion
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.auth.routers.auth import router as auth_router
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import SddRequirement
from app.domains.workspace_asset.routers.workspace_asset import router as workspace_asset_router
from app.domains.workspace_canvas.models import WorkspaceCanvas
from app.domains.workspace_canvas.router import router


def _canvas_client(db):
    for user_id in ("owner", "member", "outsider"):
        db.add(User(id=user_id, display_name=user_id, email=f"{user_id}@example.test", hashed_password="unused"))
    db.add_all(
        [
            Workspace(id="workspace", name="Canvas", owner_id="owner"),
            Workspace(id="other", name="Other", owner_id="outsider"),
        ]
    )
    db.flush()
    db.add_all(
        [
            WorkspaceMember(workspace_id="workspace", user_id="owner", role=WorkspaceRole.OWNER),
            WorkspaceMember(
                workspace_id="workspace",
                user_id="member",
                role=WorkspaceRole.VIEWER,
                permissions_json='["VIEW_DASHBOARD"]',
            ),
            SddTask(id="task", workspace_id="workspace", creator_id="owner", name="Task"),
            SddTask(id="other-task", workspace_id="other", creator_id="outsider", name="Other task"),
        ]
    )
    db.commit()

    def current_user(x_actor: str = Header()):
        return db.get(User, x_actor)

    app = FastAPI()
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(workspace_asset_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, base_url="http://testserver/workspaces/workspace/canvas/")


def _operation(client, actor, operation_id, edit, anchors=None):
    payload = {"id": operation_id, "edit": edit, "anchors": anchors or []}
    return client.post("operations", headers={"x-actor": actor}, json=payload)


def _node(node_id, kind, x=0, y=0, width=200, height=150, reference=None):
    return {
        "id": node_id,
        "kind": kind,
        "position": {"x": x, "y": y},
        "size": {"width": width, "height": height},
        "reference": reference,
    }


def test_canvas_merges_field_edits_and_retries_and_moves_grouped_items(db):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    note = {"type": "add_node", "node": _node("note", "note", 40, 50)}
    frame = {"type": "add_node", "node": _node("frame", "frame", width=400, height=320)}
    assert _operation(client, "member", "note-op", note).json() == {"revision": 1}
    assert _operation(client, "owner", "frame-op", frame).json() == {"revision": 2}
    move = {"type": "update_node", "id": "frame", "patch": {"position": {"x": -120, "y": 75}}}
    assert _operation(client, "owner", "move-op", move).json() == {"revision": 3}
    write = {"type": "update_node", "id": "note", "patch": {"text": "Shared notes", "expected_text": ""}}
    assert _operation(client, "member", "text-op", write).json() == {"revision": 4}
    assert _operation(client, "owner", "move-op", move).json() == {"revision": 4}
    stale = {**write, "patch": {"text": "A stale edit", "expected_text": ""}}
    conflict = _operation(client, "owner", "stale-op", stale)
    assert conflict.status_code == 409 and conflict.json()["detail"] == "CANVAS_TEXT_CHANGED"

    edge = {"type": "add_edge", "edge": {"id": "arrow", "source": "frame", "target": "note"}}
    assert _operation(client, "member", "arrow-op", edge).status_code == 200
    state = client.get(".", headers=owner).json()
    nodes = {node["id"]: node for node in state["nodes"]}
    assert nodes["note"]["position"] == {"x": -80, "y": 125}
    assert nodes["note"]["text"] == "Shared notes"
    assert [item["id"] for item in state["edges"]] == ["arrow"]
    assert _operation(client, "owner", "delete-op", {"type": "remove_node", "id": "note"}).status_code == 200
    assert client.get(".", headers=owner).json()["edges"] == []


def test_canvas_enforces_source_permissions_and_projects_live_state(db):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    member = {"x-actor": "member"}
    assert client.get(".", headers={"x-actor": "outsider"}).status_code == 403
    assert client.get("plan-files", headers=member).status_code == 403
    assert client.get(".", headers=member).json()["assets"] == []
    for source_id, expected in [("other-task", 404), ("task", 200)]:
        card = _node("card", "card", reference={"kind": "task", "id": source_id})
        assert (
            _operation(client, "owner", f"source-{source_id}", {"type": "add_node", "node": card}).status_code
            == expected
        )

    assert (
        _operation(client, "member", "note-op", {"type": "add_node", "node": _node("note", "note")}).status_code == 200
    )
    edge = {"type": "add_edge", "edge": {"id": "arrow", "source": "note", "target": "card"}}
    assert _operation(client, "owner", "arrow-op", edge).status_code == 200
    state = client.get(".", headers=member).json()
    assert [node["id"] for node in state["nodes"]] == ["note"]
    assert state["edges"] == []
    assert _operation(client, "member", "delete-card", {"type": "remove_node", "id": "card"}).status_code == 409

    task = db.get(SddTask, "task")
    task.status = TaskStatus.COMPLETED
    db.commit()
    new_state = client.get(".", headers=owner).json()
    assert new_state["revision"] == state["revision"]
    assert new_state["nodes"][0]["details"]["status"] == "COMPLETED"
    assert new_state["assets"][0]["details"]["status"] == "COMPLETED"


def test_asset_display_preference_is_owned_by_each_account(db):
    client = _canvas_client(db)
    profile = "http://testserver/auth/me"
    member = {"x-actor": "member"}
    owner = {"x-actor": "owner"}
    assert client.get(profile, headers=member).json()["asset_display_mode"] == "table"
    assert client.put(f"{profile}/asset-display", headers=member, json={"mode": "canvas"}).json() == {"mode": "canvas"}
    assert client.get(profile, headers=member).json()["asset_display_mode"] == "canvas"
    assert client.get(profile, headers=owner).json()["asset_display_mode"] == "table"


def test_canvas_omits_legacy_api_mock_cards_and_their_arrows(db):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    reference = {"kind": "endpoint", "id": "mock-project", "method": "GET", "path": "/receipt"}
    db.add(
        WorkspaceCanvas(
            workspace_id="workspace",
            revision=1,
            contents={
                "nodes": {
                    "note": _node("note", "note"),
                    "mock-card": _node("mock-card", "card", reference=reference),
                },
                "edges": {"arrow": {"id": "arrow", "source": "note", "target": "mock-card"}},
            },
        )
    )
    db.commit()

    state = client.get(".", headers=owner).json()
    assert state["access"]["source_kinds"] == ["case", "requirement", "task", "document", "plan_document"]
    assert [item["reference"]["kind"] for item in state["assets"]] == ["task"]
    assert [item["id"] for item in state["nodes"]] == ["note"]
    assert state["edges"] == []
    edit_note = {"type": "update_node", "id": "note", "patch": {"text": "Still shared"}}
    assert _operation(client, "owner", "save-note", edit_note).status_code == 200
    add_mock = {"type": "add_node", "node": _node("new-mock", "card", reference=reference)}
    assert _operation(client, "owner", "add-mock", add_mock).status_code == 403


def test_canvas_projects_catalog_and_canonical_links_without_saved_cards(db):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    db.add(SddRequirement(id="requirement", workspace_id="workspace", title="Requirement"))
    db.commit()
    relationship = "http://testserver/workspaces/workspace/workspace-assets/requirements/requirement/tasks"
    assert (
        client.post(relationship, headers=owner, json={"task_id": "task", "relation_type": "COVERS"}).status_code == 200
    )
    state = client.get(".", headers=owner).json()
    assert state["nodes"] == [] and state["revision"] == 0
    assert [item["reference"]["id"] for item in state["assets"]] == ["requirement", "task"]
    assert state["relations"] == [{"requirement_id": "requirement", "task_id": "task", "relation_type": "COVERS"}]

    task_card = state["assets"][1]
    anchor = _node(task_card["node_id"], "card", reference=task_card["reference"])
    edit = {"type": "update_node", "id": anchor["id"], "patch": {"position": {"x": 220, "y": 170}}}
    assert _operation(client, "owner", "move-task", edit, [anchor]).status_code == 200
    updated = client.get(".", headers=owner).json()
    assert updated["nodes"][0]["position"] == {"x": 220, "y": 170}
    assert updated["assets"][1]["node_id"] == anchor["id"]

    assert client.delete(f"{relationship}/task", headers=owner).status_code == 200
    assert client.get(".", headers=owner).json()["relations"] == []


def test_paragraph_cards_remain_anchored_after_document_publication(db):
    client = _canvas_client(db)
    db.add(
        SddAsset(
            id="doc",
            task_id="task",
            workspace_id="workspace",
            creator_id="owner",
            asset_type=AssetType.PLAN,
            name="Plan",
        )
    )
    db.flush()
    for version, text in [(1, "Original paragraph"), (2, "Updated paragraph")]:
        db.add(
            SddAssetVersion(
                id=f"version-{version}",
                asset_id="doc",
                version_no=version,
                created_by="owner",
                blocks_json=[{"id": "blk-1", "text": text}],
            )
        )
    db.flush()
    asset = db.get(SddAsset, "doc")
    asset.active_version_id = "version-1"
    db.commit()
    owner = {"x-actor": "owner"}
    paragraphs = client.post("paragraphs", headers=owner, json={"kind": "document", "id": "doc"}).json()
    row = paragraphs["items"][0]
    assert row["reference"] == {"kind": "document", "id": "doc", "version_id": "version-1", "block": "blk-1"}
    card = _node("doc-card", "card", reference=row["reference"])
    assert _operation(client, "owner", "pin-doc", {"type": "add_node", "node": card}).status_code == 200
    db.get(SddAsset, "doc").active_version_id = "version-2"
    db.commit()
    pinned = client.get(".", headers=owner).json()["nodes"][0]
    assert pinned["details"]["detail"] == "Original paragraph"
    assert pinned["details"]["historical"] is True
