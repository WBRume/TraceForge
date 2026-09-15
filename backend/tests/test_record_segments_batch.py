"""record_segments_batch：单事务批量落库、批内去重、snapshot 同事务更新。"""

import os
import sys


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.models.context_token import (  # noqa: E402
    ContextTokenCategory,
    SddContextTokenSegment,
    SddContextTokenSnapshot,
)
from app.domains.task.services import context_token_service  # noqa: E402


def _tool_input_kwargs(tool_use_id: str) -> dict:
    return {
        "workspace_id": "ws-batch",
        "task_id": "task-batch",
        "ai_job_id": "job-batch",
        "session_id": "session-batch",
        "tool_name": "read_file",
        "tool_input": {"path": "README.md"},
        "tool_use_id": tool_use_id,
    }


def _tool_result_kwargs(tool_use_id: str) -> dict:
    return {
        "workspace_id": "ws-batch",
        "task_id": "task-batch",
        "ai_job_id": "job-batch",
        "session_id": "session-batch",
        "tool_use_id": tool_use_id,
        "output": "hello",
        "is_error": False,
    }


def _count(db, category) -> int:
    return (
        db.query(SddContextTokenSegment)
        .filter(
            SddContextTokenSegment.task_id == "task-batch",
            SddContextTokenSegment.category == category,
        )
        .count()
    )


def test_batch_writes_single_transaction_with_dedupe(db):
    entries = [
        ("tool_input", _tool_input_kwargs("call-1")),
        ("tool_input", _tool_input_kwargs("call-1")),  # 批内去重
        ("tool_input", _tool_input_kwargs("call-2")),
        ("tool_result", _tool_result_kwargs("call-1")),
        ("thinking", {
            "workspace_id": "ws-batch",
            "task_id": "task-batch",
            "ai_job_id": "job-batch",
            "session_id": "session-batch",
            "content": "thinking merged",
        }),
        ("hitl", {
            "workspace_id": "ws-batch",
            "task_id": "task-batch",
            "ai_job_id": "job-batch",
            "session_id": "session-batch",
            "prompt": "请确认",
            "source_kind": "hitl_prompt",
        }),
    ]
    snapshot_update = {
        "workspace_id": "ws-batch",
        "task_id": "task-batch",
        "ai_job_id": "job-batch",
        "session_id": "session-batch",
        "usage": {"input_tokens": 42},
    }

    processed = context_token_service.record_segments_batch(
        db, entries, snapshot_update=snapshot_update
    )

    assert processed == 5
    assert _count(db, ContextTokenCategory.TOOL_INPUT) == 2
    assert _count(db, ContextTokenCategory.TOOL_RESULT) == 1
    assert _count(db, ContextTokenCategory.THINKING) == 1
    assert _count(db, ContextTokenCategory.HITL) == 1

    snapshots = (
        db.query(SddContextTokenSnapshot)
        .filter(SddContextTokenSnapshot.task_id == "task-batch")
        .all()
    )
    assert len(snapshots) == 1
    assert snapshots[0].input_tokens == 42
    # 批内含无响应 HITL → snapshot 标记 WAITING_HITL
    assert snapshots[0].status == "WAITING_HITL"


def test_repeated_batches_dedupe_tool_input(db):
    context_token_service.record_segments_batch(
        db, [("tool_input", _tool_input_kwargs("call-1"))]
    )
    context_token_service.record_segments_batch(
        db, [("tool_input", _tool_input_kwargs("call-1"))]
    )
    assert _count(db, ContextTokenCategory.TOOL_INPUT) == 1


def test_unknown_recorder_rejected(db):
    import pytest

    with pytest.raises(ValueError):
        context_token_service.record_segments_batch(db, [("bogus", {})])
    db.rollback()
