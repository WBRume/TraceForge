"""Agent adapters 包。"""

from app.agents.registration import AgentSetting
from app.agents.registry import register_backend
from app.domains.system_config.services.config_fields import ConfigField


def register_all() -> None:
    """注册所有内置 adapter。"""
    from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter
    from app.agents.adapters.mock.mock_adapter import MockAdapter
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.engine.claude_bridge import create_cli_bridge

    register_backend(
        "claude-code",
        ClaudeCodeAdapter,
        label="Claude Code CLI",
        runtime_factory=create_cli_bridge,
        probe_scope="binary",
    )
    register_backend(
        "opencode",
        OpenCodeAdapter,
        label="OpenCode (Server)",
        runtime_kwargs={"runtime_credentials": True},
        model_format="provider/model",
        settings=(
            AgentSetting(
                "server_url",
                ConfigField(
                    "opencode_url",
                    "OpenCode 服务地址",
                    "OPENCODE_SERVER_URL",
                    "url",
                    maximum=500,
                    hint="作用：连接 OpenCode Server。前提：服务已启动且后端可访问，地址需包含协议与端口。",
                ),
            ),
            AgentSetting(
                "username", ConfigField("opencode_username", "OpenCode 用户名", "OPENCODE_SERVER_USERNAME", maximum=200)
            ),
            AgentSetting(
                "password", ConfigField("opencode_password", "OpenCode 密码", "OPENCODE_SERVER_PASSWORD", "secret")
            ),
        ),
    )
    register_backend(
        "dsh",
        DshServerAdapter,
        label="DSH (Web Host)",
        runtime_kwargs={"runtime_credentials": True},
        model_format="provider/model",
        settings=(
            AgentSetting(
                "server_url",
                ConfigField(
                    "dsh_url",
                    "DSH Web Host 地址",
                    "DSH_SERVER_URL",
                    "url",
                    maximum=500,
                    hint="作用：连接 DSH Web Host。前提：服务已启动且后端可访问，地址需包含协议与端口。",
                ),
            ),
            AgentSetting(
                "browser_token", ConfigField("dsh_browser_token", "DSH 启动令牌", "DSH_BROWSER_TOKEN", "secret")
            ),
            AgentSetting(
                "browser_cookie", ConfigField("dsh_browser_cookie", "DSH 会话 Cookie", "DSH_BROWSER_COOKIE", "secret")
            ),
        ),
    )
    register_backend(
        "mock", MockAdapter, label="Mock", selectable=False, runtime_factory=create_cli_bridge, probe_scope="simulation"
    )
