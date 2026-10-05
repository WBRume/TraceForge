from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.domains.auth.models.user import User, Workspace
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookSpec
from app.domains.management.models.management import (
    SddManagementProduct,
    SddManagementProject,
    SddManagementProjectProduct,
)
from tests.case_center.test_diagnosis_case_center import _build_app
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session


@pytest.fixture
def case_list_client():
    engine, sessions = _build_db()
    try:
        with _session(sessions) as db:
            user, workspace, _ = _seed_workspace(db)
            for key, title, priority, created in [
                ("a", "Alpha", "P2", datetime(2026, 10, 1)),
                ("b", "Beta", "P0", datetime(2026, 10, 1, 23, 59, 59, 999999)),
                ("c", "Gamma", "P3", datetime(2026, 10, 2)),
                ("d", "Delta", "P1", datetime(2026, 10, 3)),
            ]:
                db.add(
                    SddCase(
                        id=f"case-{key}",
                        workspace_id=workspace.id,
                        creator_id=user.id,
                        title=title,
                        priority=priority,
                        category="PRODUCT",
                        status="APPROVED",
                        product_name="Gateway",
                        product_version="2.1",
                        site_name="East",
                        created_at=created,
                        updated_at=datetime(2026, 10, 5),
                    )
                )
            outsider = User(id="outsider", email="outsider@example.com", hashed_password="x", display_name="Outsider")
            hidden = Workspace(id="hidden", name="Hidden", owner_id=outsider.id)
            db.add_all(
                [
                    outsider,
                    hidden,
                    SddCase(
                        id="case-hidden",
                        workspace_id="hidden",
                        creator_id="outsider",
                        title="Hidden",
                        priority="P0",
                        category="PRODUCT",
                        status="APPROVED",
                    ),
                ]
            )
            spec = PlaybookSpec(
                id="spec",
                workspace_id=workspace.id,
                spec_key="guide",
                version="1",
                spec_digest="sha256:spec",
                bundle_digest="sha256:bundle",
                spec_json={"spec": {"metadata": {"title": "Guide"}, "match": {}, "stages": []}},
            )
            db.add(spec)
            db.add_all(
                [
                    CasePlaybookLink(case_id="case-b", spec_id="spec", revision_json={}),
                    CasePlaybookLink(case_id="case-b", spec_id="spec", revision_json={}),
                    CasePlaybookLink(case_id="case-c", spec_id=None, revision_json={}),
                ]
            )
            db.commit()
        with TestClient(_build_app(sessions, user)) as client:
            yield client, sessions
    finally:
        engine.dispose()


@pytest.mark.parametrize("endpoint", ["/api/workspaces/ws-1/cases", "/api/cases"])
def test_sort_is_global_before_paging_and_is_stable(case_list_client, endpoint):
    client, _ = case_list_client
    params = {"sort_by": "priority", "sort_order": "asc", "page_size": 2}
    first = client.get(endpoint, params=params)
    second = client.get(endpoint, params={**params, "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 4
    assert [item["id"] for item in first.json()["items"]] == ["case-b", "case-d"]
    assert [item["id"] for item in second.json()["items"]] == ["case-a", "case-c"]
    descending = client.get(endpoint, params={**params, "sort_order": "desc"})
    assert [item["id"] for item in descending.json()["items"]] == ["case-c", "case-a"]
    assert client.get("/api/cases", params={"ws_id": "hidden"}).status_code == 403


@pytest.mark.parametrize("endpoint", ["/api/workspaces/ws-1/cases", "/api/cases"])
def test_combined_filters_and_inclusive_dates(case_list_client, endpoint):
    client, _ = case_list_client
    response = client.get(
        endpoint,
        params={
            "keyword": "Beta",
            "category": "PRODUCT",
            "priority": "P0",
            "status": "APPROVED",
            "product_name": "Gate",
            "product_version": "2.",
            "site_name": "ast",
            "creator_name": "Use",
            "created_from": "2026-10-01",
            "created_to": "2026-10-01",
            "has_playbook": "true",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "case-b"
    assert response.json()["items"][0]["has_playbook"] is True
    dates = client.get(endpoint, params={"created_from": "2026-10-01", "created_to": "2026-10-01"})
    assert dates.json()["total"] == 2
    unpromoted = client.get(endpoint, params={"has_playbook": "false"})
    assert {item["id"] for item in unpromoted.json()["items"]} == {"case-a", "case-c", "case-d"}
    assert unpromoted.json()["total"] == 3


def test_product_filters_match_the_displayed_project_fallback(case_list_client):
    client, sessions = case_list_client
    with _session(sessions) as db:
        project = SddManagementProject(id="project", name="Project", code="PROJECT")
        product = SddManagementProduct(id="product", name="Fallback product", code="FALLBACK", version_no="4.2")
        other = SddManagementProduct(id="other", name="Other product", code="OTHER", version_no="9.0")
        db.add_all([project, product, other])
        db.add_all(
            [
                SddManagementProjectProduct(
                    project_id="project", product_id="product", created_at=datetime(2026, 1, 1)
                ),
                SddManagementProjectProduct(project_id="project", product_id="other", created_at=datetime(2026, 1, 2)),
            ]
        )
        db.get(Workspace, "ws-1").project_id = "project"
        inherited = db.get(SddCase, "case-c")
        inherited.product_name = None
        inherited.product_version = " "
        db.commit()
    response = client.get("/api/cases", params={"product_name": "Fallback", "product_version": "4.2"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "case-c"
    assert response.json()["items"][0]["product_version"] == "4.2"
    assert client.get("/api/cases", params={"product_name": "Other"}).json()["total"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"sort_by": "unknown"},
        {"sort_order": "invalid"},
        {"category": "unknown"},
        {"page": 0},
        {"page_size": 101},
        {"created_from": "not-a-date"},
        {"created_from": "2026-10-05", "created_to": "2026-10-01"},
    ],
)
def test_invalid_queries_are_rejected(case_list_client, params):
    client, _ = case_list_client
    for endpoint in ("/api/workspaces/ws-1/cases", "/api/cases"):
        response = client.get(endpoint, params=params)
        assert response.status_code == 422, response.text
