from datetime import datetime
from threading import BoundedSemaphore

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.asset.models.asset import AssetType, SddAsset, SddAssetVersion
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.auth.routers.auth import router as auth_router
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookSpec
from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.workspace_asset.models.workspace_asset import (
    SddRequirement,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_asset.routers.requirement_documents import router as requirement_documents_router
from app.domains.workspace_asset.routers.workspace_asset import router as workspace_asset_router
from app.domains.workspace_canvas import map_queries, quarters, read_budget, root_tree
from app.domains.workspace_canvas.models import WorkspaceCanvas
from app.domains.workspace_canvas.router import router
from app.domains.workspace_canvas.schemas import ObjectReference
from app.domains.workspace_canvas.sources import catalog_node_id


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
    app.include_router(requirement_documents_router)
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


def test_canvas_keeps_scoped_placements_and_annotations_independent(db):
    client = _canvas_client(db)
    first, second = "asset-" + "a" * 32, "asset-" + "b" * 32
    reference = ObjectReference(kind="task", id="task")
    frames = {
        scope: {**_node(f"frame-{label}", "frame", width=400, height=320), "scope_id": scope}
        for scope, label in ((first, "first"), (second, "second"))
    }
    for scope, frame in frames.items():
        assert _operation(client, "owner", frame["id"], {"type": "add_node", "node": frame}).status_code == 200
        note = {**_node(f"note-{frame['id']}", "note", 40, 40), "scope_id": scope}
        assert _operation(client, "owner", note["id"], {"type": "add_node", "node": note}).status_code == 200

    card_id = catalog_node_id(reference, first)
    anchor = {**_node(card_id, "card", 80, 50, reference=reference.model_dump()), "scope_id": first}
    move = {"type": "update_node", "id": "frame-first", "patch": {"position": {"x": 50, "y": 0}}}
    assert _operation(client, "owner", "move", move, [anchor]).status_code == 200
    nodes = {row["id"]: row for row in client.get(".", headers={"x-actor": "owner"}).json()["nodes"]}
    assert nodes[card_id]["position"]["x"] == 130
    assert nodes["note-frame-first"]["position"]["x"] == 90
    assert nodes["note-frame-second"]["position"]["x"] == 40
    arrow = {"type": "add_edge", "edge": {"id": "across", "source": card_id, "target": "note-frame-second"}}
    assert _operation(client, "owner", "cross-scope", arrow).status_code == 200
    assert client.get(".", headers={"x-actor": "owner"}).json()["edges"] == [arrow["edge"]]


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
    standalone = client.get(
        "branches", params={"quarter": new_state["quarter"]["id"], "kind": "standalone"}, headers=owner
    )
    assert standalone.json()["assets"][0]["details"]["status"] == "COMPLETED"


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
    assert "endpoint" not in state["access"]["source_kinds"]
    assert [asset["reference"]["id"] for asset in state["assets"]] == ["task"]
    assert state["branches"] == []
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
    link = state["relations"][0]
    assert link["source"] == {"kind": "task", "id": "task"}
    assert link["target"] == {"kind": "requirement", "id": "requirement"}
    assert link["relation_type"] == "COVERS"

    task_card = state["assets"][1]
    anchor = _node(task_card["node_id"], "card", reference=task_card["reference"])
    edit = {"type": "update_node", "id": anchor["id"], "patch": {"position": {"x": 220, "y": 170}}}
    assert _operation(client, "owner", "move-task", edit, [anchor]).status_code == 200
    updated = client.get(".", headers=owner).json()
    assert updated["nodes"][0]["position"] == {"x": 220, "y": 170}
    assert updated["assets"][1]["node_id"] == anchor["id"]

    assert client.delete(f"{relationship}/task", headers=owner).status_code == 200
    assert client.get(".", headers=owner).json()["relations"] == []


def test_large_canvas_bounds_roots_and_reads_real_neighbors_by_cursor(db, monkeypatch):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    monkeypatch.setattr(quarters, "OVERVIEW_DETAIL_LIMIT", 5)
    monkeypatch.setattr(map_queries, "WINDOW_LIMIT", 2)
    task_ids = [f"task-{index}" for index in range(8)]
    db.add(SddRequirement(id="delivery", workspace_id="workspace", title="Delivery"))
    db.add_all(
        SddTask(id=identifier, workspace_id="workspace", creator_id="owner", name=f"Rollout {identifier}")
        for identifier in task_ids
    )
    db.flush()
    db.add_all(
        SddTaskRequirement(
            workspace_id="workspace",
            requirement_id="delivery",
            task_id=identifier,
            relation_type=TaskRequirementRelationType.COVERS,
        )
        for identifier in task_ids[:5]
    )
    db.commit()

    summary = client.get(".", headers=owner).json()
    assert summary["root_tree"] and summary["branches"] == []
    assert [asset["reference"]["id"] for asset in summary["assets"]] == ["delivery", "task-7", "task-6"]
    assert summary["assets"][0]["has_related"]

    result = client.get("search", params={"q": "Rollout task-7", "kind": "task"}, headers=owner).json()
    assert [item["reference"]["id"] for item in result] == ["task-7"]
    assert client.get("search", params={"q": "Other"}, headers=owner).json() == []
    assert client.get("search", params={"q": "Rollout"}, headers={"x-actor": "member"}).json() == []

    params = {"kind": "requirement", "id": "delivery"}
    visited = []
    for _ in range(3):
        page = client.get("window", params=params, headers=owner).json()
        assert page["assets"][0]["reference"]["id"] == "delivery"
        assert len(page["assets"]) <= 3
        visited.extend(row["source"]["id"] for row in page["relations"])
        params["cursor"] = page["next_cursor"]
    assert sorted(visited) == task_ids[:5]
    assert params["cursor"] is None
    focus = client.get("window", params={**params, "reveal": "task:task-4"}, headers=owner).json()
    assert [asset["reference"]["id"] for asset in focus["assets"]] == ["delivery", "task-4", "task-0", "task-1"]
    rejected = client.get("window", params={**params, "reveal": "task:task-7"}, headers=owner).json()
    assert "task-7" not in {asset["reference"]["id"] for asset in rejected["assets"]}
    assert client.get("window", params={"kind": "task", "id": "other-task"}, headers=owner).status_code == 404


def test_canvas_keeps_asset_lookup_available_when_graph_is_busy(db, monkeypatch):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(read_budget, "_read_slots", slot)
    with slot:
        response = client.get(".", headers=owner)
        assert response.status_code == 503 and response.headers["retry-after"] == "3"
        assert response.json()["detail"] == "CANVAS_QUERY_BUSY"
        assert (
            client.get("branches", params={"quarter": "2026-Q4", "kind": "standalone"}, headers=owner).status_code
            == 503
        )
        lookup = client.get("search", headers=owner, params={"q": "Task"})
        assert [item["reference"]["id"] for item in lookup.json()] == ["task"]
    assert client.get(".", headers=owner).status_code == 200


def test_quarter_history_keeps_only_the_summary_and_real_cross_period_edges(db):
    client = _canvas_client(db)
    actor = {"x-actor": "owner"}
    db.get(SddTask, "task").created_at = datetime(2024, 1, 1)
    older = SddRequirement(id="older", workspace_id="workspace", title="Older demand", created_at=datetime(2022, 8, 3))
    current = SddRequirement(id="newer", workspace_id="workspace", title="New demand", created_at=datetime(2026, 11, 3))
    activities = [
        SddTask(id=identifier, workspace_id="workspace", creator_id="owner", name=identifier, created_at=when)
        for identifier, when in (
            ("old-task", datetime(2022, 8, 9)),
            ("issue-a", datetime(2026, 10, 1)),
            ("issue-b", datetime(2026, 12, 1)),
        )
    ]
    db.add_all([older, current, *activities])
    db.flush()
    db.add_all(
        SddTaskRequirement(
            workspace_id="workspace",
            requirement_id="older",
            task_id=task.id,
            relation_type=TaskRequirementRelationType.RELATES_TO,
        )
        for task in activities
    )
    db.commit()
    state = client.get(".", params={"quarter": "2026-Q4"}, headers=actor).json()
    assets = {asset["reference"]["id"]: asset for asset in state["assets"]}
    assert set(assets) == {"older", "newer", "issue-a", "issue-b"}
    assert assets["older"]["quarter"]["id"] == "2022-Q3"
    assert {link["source"]["id"] for link in state["relations"]} == {"issue-a", "issue-b"}
    params = {"kind": "requirement", "id": "older", "quarter": "2026-Q4"}
    assert len(client.get("window", params=params, headers=actor).json()["assets"]) == 1
    directed = client.get(
        "window", headers=actor, params={"quarter": "2026-Q4", "kind": "task", "id": "issue-a", "children": True}
    ).json()
    assert [asset["reference"]["id"] for asset in directed["assets"]] == ["issue-a", "older"]
    assert not any(asset["has_unseen_children"] for asset in directed["assets"])
    history = client.get(".", params={"quarter": "2022-Q3"}, headers=actor).json()
    assert "old-task" in {asset["reference"]["id"] for asset in history["assets"]}


def test_dense_root_pages_follow_real_links_and_keep_unlinked_roots_reachable(db, monkeypatch):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    monkeypatch.setattr(quarters, "OVERVIEW_DETAIL_LIMIT", 4)
    monkeypatch.setattr(root_tree, "SCAN_LIMIT", 4)
    monkeypatch.setattr(root_tree, "TYPE_PAGE", 2)
    when = datetime(2026, 11, 3)
    db.add_all(
        SddRequirement(id=key, workspace_id="workspace", title=key, created_at=when)
        for key in ("one", "two", "three", "four", "root")
    )
    db.flush()
    db.add(
        SddRequirement(id="sub", workspace_id="workspace", title="Sub", parent_requirement_id="root", created_at=when)
    )
    db.get(SddRequirement, "root").predecessor_id = "three"
    db.add(SddRequirement(id="elsewhere", workspace_id="other", title="Elsewhere", created_at=when))
    db.commit()

    initial = client.get(".", params={"quarter": "2026-Q4"}, headers=owner).json()
    assert initial["root_tree"] and initial["branches"] == []
    assert [asset["reference"]["id"] for asset in initial["assets"] if asset["reference"]["kind"] == "requirement"] == [
        "three",
        "root",
    ]
    assert [(edge["source"]["id"], edge["target"]["id"], edge["relation_type"]) for edge in initial["relations"]] == [
        ("root", "three", "PREREQUISITE"),
    ]
    assert (
        client.get("window", params={"quarter": "2026-Q4", "kind": "requirement", "id": "root"}, headers=owner).json()[
            "assets"
        ][1]["reference"]["id"]
        == "sub"
    )
    params = {"quarter": "2026-Q4", "kind": "requirement", "slice": "M2"}
    seen = []
    for _ in range(4):
        page = client.get("roots", params=params, headers=owner).json()
        seen.extend(asset["reference"]["id"] for asset in page["assets"])
        if not page["next_cursor"]:
            break
        params["cursor"] = page["next_cursor"]
    assert seen == ["three", "root", "two", "one", "four"]
    assert client.get("roots", params={**params, "cursor": '{"requirement":1}'}, headers=owner).status_code == 422


def test_quarter_saved_calendar_and_annotated_scope(db):
    client = _canvas_client(db)
    owner, viewer = {"x-actor": "owner"}, {"x-actor": "member"}
    payload = {"format": "months", "start_month": 11, "year_label": "end", "timezone": "Asia/Hong_Kong"}
    assert client.put("calendar", headers=viewer, json=payload).status_code == 403
    assert client.put("calendar", headers=owner, json=payload).status_code == 200
    calendar = client.get("calendar", params={"year": 2025}, headers=viewer).json()
    assert calendar["can_edit"] is False
    assert calendar["quarters"][0]["start"] == "2025-11-01"
    assert calendar["quarters"][0]["end"] == "2026-01-31"
    assert calendar["quarters"][0]["label_year"] == 2026
    note = {**_node("quarter-note", "note"), "scope_id": "quarter-2025-Q1"}
    assert _operation(client, "owner", "note-in-quarter", {"type": "add_node", "node": note}).status_code == 200
    assert client.get(".", headers=owner, params={"quarter": "2025-Q1"}).json()["nodes"][0]["id"] == "quarter-note"
    assert client.get(".", headers=owner, params={"quarter": "2025-Q2"}).json()["nodes"] == []


def test_quarter_task_branch_filters_and_cursors_resume_after_an_empty_window(db, monkeypatch):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    monkeypatch.setattr(quarters, "SCAN_LIMIT", 3)
    timestamp = datetime(2026, 11, 4)
    db.add(SddRequirement(id="delivery", workspace_id="workspace", title="Delivery", created_at=timestamp))
    linked = ["a-task", "b-task", "c-task"]
    db.add_all(
        SddTask(id=identifier, workspace_id="workspace", creator_id="owner", name=identifier, created_at=timestamp)
        for identifier in linked
    )
    db.add(
        SddTask(
            id="follow",
            workspace_id="workspace",
            creator_id="owner",
            name="Consultation",
            created_at=timestamp,
            status=TaskStatus.COMPLETED,
        )
    )
    db.flush()
    db.add_all(
        SddTaskRequirement(
            workspace_id="workspace",
            requirement_id="delivery",
            task_id=identifier,
            relation_type=TaskRequirementRelationType.COVERS,
        )
        for identifier in linked
    )
    db.commit()
    params = {"quarter": "2026-Q4", "kind": "standalone", "status": "COMPLETED", "slice": "M2", "q": "Consult"}
    first = client.get("branches", headers=owner, params=params).json()
    assert first["assets"] == [] and first["next_cursor"].endswith(":c-task")
    following = client.get("branches", headers=owner, params={**params, "cursor": first["next_cursor"]}).json()
    assert [asset["reference"]["id"] for asset in following["assets"]] == ["follow"]
    assert client.get("branches", headers=owner, params={**params, "slice": "M9"}).status_code == 422


def test_canvas_projects_real_document_and_diagnosis_provenance(db):
    client = _canvas_client(db)
    owner = {"x-actor": "owner"}
    member = {"x-actor": "member"}
    db.add_all(
        [
            SddRequirement(id="parent", workspace_id="workspace", title="Parent"),
            SddTask(
                id="diagnosis",
                workspace_id="workspace",
                creator_id="owner",
                name="Investigate",
                task_type=TaskType.DIAGNOSIS.value,
            ),
            PlaybookSpec(
                id="procedure",
                workspace_id="workspace",
                spec_key="procedure",
                version="1.0.0",
                spec_digest="spec",
                bundle_digest="bundle",
                spec_json={"spec": {"metadata": {"title": "Procedure"}}},
            ),
            SddAsset(
                id="design",
                workspace_id="workspace",
                task_id="task",
                creator_id="owner",
                name="Design.md",
                asset_type=AssetType.PLAN,
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            SddRequirement(
                id="leaf",
                workspace_id="workspace",
                parent_requirement_id="parent",
                predecessor_id="parent",
                title="Leaf",
            ),
            SddCase(
                id="case-one",
                workspace_id="workspace",
                creator_id="owner",
                source_task_id="diagnosis",
                title="Case one",
            ),
            SddCase(id="case-two", workspace_id="workspace", creator_id="owner", title="Case two"),
        ]
    )
    db.flush()
    for case_id in ("case-one", "case-two"):
        db.add(CasePlaybookLink(case_id=case_id, spec_id="procedure", revision_json={"kind": "CASE_PROMOTION"}))
    db.commit()
    asset_url = "http://testserver/workspaces/workspace/workspace-assets"
    documents_url = f"{asset_url}/requirements/leaf/documents"
    document = client.post(documents_url, headers=owner, files={"file": ("Need.md", b"# Four eyes", "text/markdown")})
    assert document.status_code == 201
    doc_id = document.json()["id"]
    shared = client.put(f"{documents_url}/task-assets/design", headers=owner)
    assert shared.status_code == 200
    assert shared.json() == client.put(f"{documents_url}/task-assets/design", headers=owner).json()
    disabled = client.post(documents_url, headers=member, files={"file": ("Need.md", b"test", "text/plain")})
    assert disabled.status_code == 403
    assert client.get(f"{asset_url}/requirement-documents/{doc_id}/download", headers=owner).content == b"# Four eyes"

    state = client.get(".", headers=owner).json()
    assert not state["root_tree"]
    assert not any(asset["has_unseen_children"] for asset in state["assets"])
    terminal = client.get(
        "window",
        headers=owner,
        params={"quarter": state["quarter"]["id"], "kind": "document", "id": "design", "children": True},
    ).json()
    assert [asset["reference"]["id"] for asset in terminal["assets"]] == ["design"]
    assert terminal["relations"] == []
    visible = [f"{asset['reference']['kind']}:{asset['reference']['id']}" for asset in state["assets"]]
    expansions = []
    for kind, identifier in (
        ("requirement", "parent"),
        ("requirement", "leaf"),
        ("task", "diagnosis"),
        ("case", "case-one"),
    ):
        page = client.get("window", params={"kind": kind, "id": identifier, "visible": visible}, headers=owner).json()
        expansions.extend(page["relations"])
        visible.extend(f"{asset['reference']['kind']}:{asset['reference']['id']}" for asset in page["assets"])
    links = {
        (link["source"]["id"], link["target"]["id"], link["relation_type"]) for link in state["relations"] + expansions
    }
    assert links == {
        (doc_id, "leaf", "DOCUMENT_REQUIREMENT"),
        ("design", "leaf", "DOCUMENT_REQUIREMENT"),
        ("design", "task", "DOCUMENT_TASK"),
        ("case-one", "diagnosis", "CASE_TASK"),
        ("case-one", "procedure", "CASE_PROMOTION"),
        ("case-two", "procedure", "CASE_PROMOTION"),
        ("leaf", "parent", "SUB_REQUIREMENT"),
        ("leaf", "parent", "PREREQUISITE"),
    }
    restricted = client.get(
        "branches", params={"quarter": state["quarter"]["id"], "kind": "knowledge"}, headers=member
    ).json()
    assert {link["relation_type"] for link in restricted["relations"]} == {"CASE_PROMOTION"}
    assert client.delete(f"{documents_url}/{shared.json()['link_id']}", headers=owner).status_code == 204
    attached_ids = {item["id"] for item in client.get(documents_url, headers=owner).json()["items"]}
    assert attached_ids == {doc_id}


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
