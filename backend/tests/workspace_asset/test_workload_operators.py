from datetime import datetime, timedelta
from itertools import permutations
from types import SimpleNamespace

import pytest

from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.workspace_asset.services.workload import verify_graph
from app.domains.workspace_asset.services.workload_operators import (
    GRAPH_VERSION,
    OPERATOR_SPECS,
    Interaction,
    InteractionPolicy,
    execution_state,
    interaction_accumulator,
)

NOW = datetime(2026, 11, 18, 12)


def test_registered_operators_form_a_versioned_graph():
    verify_graph()
    assert GRAPH_VERSION >= 1
    assert set(OPERATOR_SPECS) == {
        "ExecutionProject",
        "EventNormalize",
        "HumanItemProject",
        "InteractionAccumulator",
        "SlotProjection",
        "FollowupCheckProject",
        "MemberAggregate",
    }
    assert all(spec.version >= 1 and spec.missing for spec in OPERATOR_SPECS.values())


@pytest.mark.parametrize(
    ("offsets", "seconds_later", "strength", "following"),
    [
        pytest.param([], 0, 0, False, id="cold-start"),
        pytest.param([0], 0, 1, False, id="one-followup"),
        pytest.param([-240, 0], 0, 1.0625, False, id="spaced-followups"),
        pytest.param([-60, 0], 0, 1.5, True, id="two-followups"),
        pytest.param([0] * 20, 0, 2, True, id="burst-capped"),
        pytest.param([0, 0], 60, 1, True, id="retained-between-thresholds"),
        pytest.param([0, 0], 119, 2 * 2 ** (-119 / 60), True, id="just-before-exit"),
        pytest.param([0, 0], 120, 0.5, False, id="at-exit"),
        pytest.param([0, 0, 120], 120, 1.5, True, id="new-followup-at-exit"),
        pytest.param([0, 0], 900, 2 * 2 ** (-15), False, id="fifteen-minutes-silent"),
        pytest.param([0, 60, 61], 0, 1, False, id="future-events-ignored"),
    ],
)
def test_bounded_decay_and_hysteresis(offsets, seconds_later, strength, following):
    events = [(str(index), NOW + timedelta(seconds=offset)) for index, offset in enumerate(offsets)]
    as_of = NOW + timedelta(seconds=seconds_later)
    result = interaction_accumulator(events, as_of)
    assert result.strength == pytest.approx(strength)
    assert result.following is following
    if following:
        assert result.next_evaluate_at > as_of
        boundary = interaction_accumulator(events, result.next_evaluate_at)
        assert boundary.strength == pytest.approx(0.5)
        assert boundary.following is False
    else:
        assert result.next_evaluate_at is None


def test_replay_orders_by_occurrence_and_deduplicates_business_events():
    first = ("same-submit", NOW - timedelta(seconds=60))
    second = ("independent-submit", NOW)
    replay = ("same-submit", NOW)
    expected = interaction_accumulator([first, second], NOW)
    assert expected.strength == 1.5
    assert all(interaction_accumulator(order, NOW) == expected for order in permutations([first, second, replay]))
    assert interaction_accumulator([first, second, replay], NOW, since=NOW) == Interaction(1, False, None)


@pytest.mark.parametrize(
    "changes",
    [{"half_life_seconds": 0}, {"leave": 0}, {"enter": 0.5}, {"ceiling": 1}],
)
def test_invalid_interaction_policies_are_rejected(changes):
    with pytest.raises(ValueError, match="Invalid workload interaction policy"):
        InteractionPolicy(**changes)


@pytest.mark.parametrize(
    ("status", "started_seconds", "lease_seconds", "revision", "expected"),
    [
        pytest.param(AiJobStatus.PENDING, None, None, 1, None, id="queued"),
        pytest.param(AiJobStatus.RUNNING, -5, 1, 1, "active", id="live"),
        pytest.param(AiJobStatus.RUNNING, None, 1, 1, "uncertain", id="no-start"),
        pytest.param(AiJobStatus.RUNNING, 5, 10, 1, "uncertain", id="future-start"),
        pytest.param(AiJobStatus.RUNNING, -5, 0, 1, "uncertain", id="lease-expired"),
        pytest.param(AiJobStatus.RUNNING, -5, 1, 0, "uncertain", id="revision-fenced"),
        pytest.param(AiJobStatus.RUNNING, -5, None, None, "active", id="legacy-live"),
        pytest.param(AiJobStatus.ORPHANED, -5, -1, 1, "uncertain", id="lost-worker"),
        pytest.param(AiJobStatus.TERMINATING, -5, 1, 1, "uncertain", id="unconfirmed-stop"),
        pytest.param(AiJobStatus.WAITING_HITL, -5, None, 1, None, id="paused-for-input"),
        pytest.param(AiJobStatus.INTERRUPTED, -5, None, 1, None, id="confirmed-pause"),
        pytest.param(AiJobStatus.CANCELLED, -5, None, 1, None, id="confirmed-stop"),
        pytest.param(AiJobStatus.SUCCESS, -5, None, 1, None, id="completed"),
        pytest.param(AiJobStatus.FAILED, -5, None, 1, None, id="failed"),
    ],
)
def test_running_count_uses_durable_execution_evidence(status, started_seconds, lease_seconds, revision, expected):
    job = SimpleNamespace(
        status=status,
        started_at=NOW + timedelta(seconds=started_seconds) if started_seconds is not None else None,
        lease_expires_at=NOW + timedelta(seconds=lease_seconds) if lease_seconds is not None else None,
        session_revision=revision,
    )
    assert execution_state(job, NOW, 1) == expected
