"""Claims use the execution capabilities behind the Agent registration."""

import pytest

from app.domains.ai.services.jobs.store import resolve_execution_kind_for_backend


@pytest.mark.parametrize(
    ("backend", "expected"),
    [
        ("claude-code", "LOCAL_PROCESS"),
        ("mock", "LOCAL_PROCESS"),
        ("opencode", "REMOTE_SESSION"),
        ("dsh", "REMOTE_SESSION"),
    ],
)
def test_registered_backend_execution_kind(backend, expected):
    assert resolve_execution_kind_for_backend(backend) == expected
