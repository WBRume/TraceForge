import asyncio

import pytest
from fastapi import HTTPException

from app.domains.workspace_asset.routers import workspace_asset as routes
from app.domains.workspace_asset.schemas.workspace_asset import HumanDeltaCreateRequest
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace


@pytest.mark.parametrize("proposal_id,status", [(None, 400), ("missing-proposal", 404)])
def test_invalid_delta_reference_returns_business_error_instead_of_500(monkeypatch, proposal_id, status):
    engine, factory = _build_db()
    try:
        with factory() as db:
            user, workspace, task = _seed_workspace(db)
            ws_id, task_id = workspace.id, task.id

            async def transaction(body):
                with factory() as session:
                    return body(session)

            monkeypatch.setattr(routes, "run_db_txn", transaction)
            with pytest.raises(HTTPException) as caught:
                asyncio.run(
                    routes.create_workspace_asset_task_human_delta(
                        ws_id=ws_id,
                        task_id=task_id,
                        payload=HumanDeltaCreateRequest(proposal_id=proposal_id, final_evidence_id="missing-evidence"),
                        current_user=user,
                    )
                )
            assert caught.value.status_code == status
            assert "ChangeProposal" in caught.value.detail
    finally:
        engine.dispose()
