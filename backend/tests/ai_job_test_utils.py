"""AI 作业（jobs 子包）测试工具。

旧 ``ai_job_service`` 单体测试通过「patch 模块级 SessionLocal / 广播函数 /
调度函数」控制副作用；拆包后这些名字分散在多个模块。这里提供等价的
聚合 patch 帮助函数，保持旧测试语义不变。
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Any, Iterator

# jobs 子包中直接导入 SessionLocal 的模块（随重构演进维护）。
AI_JOB_DB_MODULES = (
    "app.domains.ai.services.jobs.store",
    "app.domains.ai.services.jobs.fencing",
    "app.domains.ai.services.jobs.attempts",
    "app.domains.ai.services.jobs.publishing",
    "app.domains.ai.services.jobs.reaper",
    "app.domains.ai.services.jobs.queue_runner",
    "app.domains.ai.services.jobs.executors",
    "app.domains.ai.services.jobs.executors.task_chat",
)


def _db_modules() -> Iterator[Any]:
    for target in AI_JOB_DB_MODULES:
        module = importlib.import_module(target)
        if hasattr(module, "SessionLocal"):
            yield module


def patch_ai_job_db(monkeypatch, factory) -> None:
    """monkeypatch 风格：把 jobs 子包所有模块的 SessionLocal 换成测试工厂。

    注意：不改动 ``app.database.SessionLocal``——``run_db_txn`` 的惰性导入
    语义与旧单体外洋试图保持一致，需要时由测试显式 patch。
    """
    for module in _db_modules():
        monkeypatch.setattr(module, "SessionLocal", factory)


@contextmanager
def patched_ai_job_db(factory):
    """mock 风格上下文：等价于 :func:`patch_ai_job_db`。"""
    import unittest.mock
    from contextlib import ExitStack

    with ExitStack() as stack:
        for module in _db_modules():
            stack.enter_context(unittest.mock.patch.object(module, "SessionLocal", factory))
        yield
