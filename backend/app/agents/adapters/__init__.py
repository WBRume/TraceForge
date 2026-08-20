"""Agent adapters 包。"""

from app.agents.registry import register_backend


def register_all() -> None:
    """注册所有内置 adapter。"""
    from app.agents.adapters.mock.mock_adapter import MockAdapter
    from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.adapters.dsh.dsh_adapter import DSHAdapter

    register_backend("mock", MockAdapter)
    register_backend("claude-code", ClaudeCodeAdapter)
    register_backend("opencode", OpenCodeAdapter)
    register_backend("dsh", DSHAdapter)