"""Finalization services reject unresolved collaboration even without their HTTP routes."""

import pytest
from workspace_collaboration import test_service as shared

from app.domains.workflow.services.change_proposal_service import ChangeProposalError, create_change_proposal
from app.domains.workspace_asset.models.workspace_asset import SddTaskBaseline, SddTaskFinalSummary
from app.domains.workspace_asset.schemas.task_final_workflow import WorkflowFinalSummaryUpsertRequest
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.task_final_workflow import baseline_service, summary_service
from app.domains.workspace_collaboration.models import CollaborationState

environment = shared.environment


def test_unresolved_collaboration_cannot_be_finalized_through_direct_services(environment):
    db, task, _root = environment
    shared.enabled(environment)
    state = db.get(CollaborationState, task.id)
    for phase in ["RUNNING", "DELIVERY_PENDING", "CONFLICT_PENDING", "RECOVERY_REQUIRED"]:
        state.sync_phase = phase
        db.flush()
        with pytest.raises(ChangeProposalError) as proposal_error:
            create_change_proposal(db, task=task, workspace=None, creator_id="u")
        assert proposal_error.value.status_code == 409
        with pytest.raises(WorkspaceAssetError, match="本地代码交付") as summary_error:
            summary_service.upsert_final_summary(
                db, "w", task.id, "u", WorkflowFinalSummaryUpsertRequest(final_status="VERIFIED", summary="final")
            )
        assert summary_error.value.status_code == 409
        with pytest.raises(WorkspaceAssetError, match="本地代码交付") as baseline_error:
            baseline_service.baseline_task(db, task, "u")
        assert baseline_error.value.status_code == 409
    assert db.query(SddTaskBaseline).count() == 0
    assert db.query(SddTaskFinalSummary).count() == 0

    # Drafting observations remains available while code conflicts are unresolved.
    draft = summary_service.upsert_final_summary(
        db, "w", task.id, "u", WorkflowFinalSummaryUpsertRequest(final_status="PARTIAL", summary="investigating")
    )
    assert db.get(SddTaskFinalSummary, draft).summary == "investigating"
    state.sync_phase = "READY"
    db.flush()
    baseline_service.ensure_collaboration_ready(db, task.id)
    with pytest.raises(WorkspaceAssetError, match="Coverage"):
        summary_service.upsert_final_summary(
            db,
            "w",
            task.id,
            "u",
            WorkflowFinalSummaryUpsertRequest(final_status="VERIFIED", summary="still unverified"),
        )
