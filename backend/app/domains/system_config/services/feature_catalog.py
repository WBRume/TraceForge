"""Allowlisted feature fields shared by validation, environment fallback and UI."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import SecretStr

from app.config import settings


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    env: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 4096
    hint: str = ""

    def default(self):
        if self.env == "SPEECH_MODE":
            return settings.SPEECH_MODE or ("api" if settings.SPEECH_API_ENABLED else "off")
        if self.env == "OAUTH_GITHUB_ENABLED":
            return bool(settings.OAUTH_GITHUB_CLIENT_ID and settings.OAUTH_GITHUB_CLIENT_SECRET)
        value = getattr(settings, self.env)
        return value.get_secret_value() if isinstance(value, SecretStr) else value

    def validate(self, value):
        if self.kind == "boolean":
            return type(value) is bool
        if self.kind == "number":
            return type(value) is int and self.minimum <= value <= self.maximum
        if not isinstance(value, str) or len(value) > self.maximum:
            return False
        if self.options:
            return value in self.options
        if self.kind == "secret":
            if self.key in {"api_key", "embedding_api_key"} and "********" in value:
                return False
            return not value or not set(value) <= {"*", "•"}
        if self.kind in {"url", "https"} and value:
            try:
                parts = urlsplit(value)
                valid_port = parts.port is None or 1 <= parts.port <= 65535
            except ValueError:
                return False
            schemes = {"https"} if self.kind == "https" else {"https", "http"}
            return bool(
                parts.scheme in schemes
                and parts.hostname
                and valid_port
                and not (parts.username or parts.password or parts.query or parts.fragment)
            )
        return True


CATALOG = {
    "speech": (
        "语音输入",
        (
            ConfigField(
                "mode",
                "识别模式",
                "SPEECH_MODE",
                "select",
                ("api", "offline", "off"),
                hint=(
                    "作用：选择语音输入的识别通道。在线 API 走百炼云服务做流式识别，"
                    "离线模式在客户端本机完成识别，停用后隐藏语音输入入口。\n"
                    "前提：在线模式需配置百炼 API Key 且能访问所选地域；"
                    "离线模式需客户端已内置离线识别模型。"
                ),
            ),
            ConfigField("api_key", "百炼 API Key", "SPEECH_API_KEY", "secret"),
            ConfigField(
                "region",
                "服务地域",
                "SPEECH_API_REGION",
                "select",
                ("beijing", "singapore"),
                hint=(
                    "作用：指定在线识别调用的百炼服务地域，决定请求发往北京或新加坡节点。\n"
                    "前提：仅在识别模式为「在线 API」时生效；"
                    "API Key 所属地域必须与所选地域一致，否则调用会被拒绝。"
                ),
            ),
            ConfigField(
                "token_ttl",
                "临时凭据有效期（秒）",
                "SPEECH_TOKEN_TTL_SECONDS",
                "number",
                minimum=60,
                maximum=300,
                hint=(
                    "作用：控制下发给客户端的临时语音凭据的有效时长，过期后客户端自动重新签发。\n"
                    "前提：仅在线 API 模式需要；取值需在 60–300 秒之间，"
                    "并保证服务端与客户端时钟同步。"
                ),
            ),
            ConfigField(
                "requests_per_minute",
                "每用户每分钟凭据上限",
                "SPEECH_TOKEN_REQUESTS_PER_MINUTE",
                "number",
                minimum=1,
                maximum=60,
                hint=(
                    "作用：限制单个用户每分钟申请临时凭据的次数，用于防止凭据被滥用。\n"
                    "前提：仅在线 API 模式生效；取值需在 1–60 之间，"
                    "且不应高于平台整体限流阈值。"
                ),
            ),
        ),
    ),
    "search": (
        "全局搜索",
        (
            ConfigField("enabled", "启用搜索", "SEARCH_ENABLED", "boolean"),
            ConfigField(
                "backend",
                "搜索引擎",
                "SEARCH_BACKEND",
                "select",
                ("auto", "sqlite", "elasticsearch"),
                hint=(
                    "作用：选择全局搜索使用的检索引擎。自动模式优先使用远程引擎，"
                    "不可用时降级为本地检索，也可强制指定后端。\n"
                    "前提：选择 Elasticsearch 时需先填写可访问的 ES 地址与凭据；"
                    "本地检索依赖内置 SQLite，无需额外服务。"
                ),
            ),
            ConfigField(
                "workers_enabled",
                "内置索引工作进程",
                "SEARCH_WORKERS_ENABLED",
                "boolean",
                hint=(
                    "作用：控制是否由后台工作进程增量构建与更新搜索索引。\n"
                    "前提：需先启用全局搜索；关闭后仅在检索时按需处理，首次查询可能较慢。"
                ),
            ),
            ConfigField(
                "es_url",
                "Elasticsearch 地址",
                "SEARCH_ES_URL",
                "url",
                maximum=500,
                hint=(
                    "作用：指定远程 Elasticsearch 服务的访问地址。\n"
                    "前提：仅在搜索引擎选择 Elasticsearch 时生效；"
                    "需包含协议与端口，且服务可从后端网络访问。"
                ),
            ),
            ConfigField("es_username", "Elasticsearch 用户名", "SEARCH_ES_USERNAME", maximum=200),
            ConfigField("es_password", "Elasticsearch 密码", "SEARCH_ES_PASSWORD", "secret"),
            ConfigField(
                "embedding_endpoint",
                "向量服务端点",
                "SEARCH_EMBEDDING_ENDPOINT",
                "https",
                maximum=500,
                hint=(
                    "作用：提供文本向量化的 HTTPS 端点，用于语义检索与向量索引构建。\n"
                    "前提：需为 HTTPS 且可从后端访问；"
                    "需与向量模型、向量服务 API Key 一同配置后语义检索才会生效。"
                ),
            ),
            ConfigField(
                "embedding_model",
                "向量模型",
                "SEARCH_EMBEDDING_MODEL",
                maximum=200,
                hint=(
                    "作用：指定向量化使用的模型标识，决定向量的维度与语义检索效果。\n"
                    "前提：需与向量服务端点提供的模型名称完全一致；"
                    "更换模型后需重建索引，否则检索结果不可用。"
                ),
            ),
            ConfigField("embedding_api_key", "向量服务 API Key", "SEARCH_EMBEDDING_API_KEY", "secret"),
        ),
    ),
    "diagnosis": (
        "诊断规程防线",
        (
            ConfigField("worker_enabled", "启用诊断工作进程", "DIAGNOSIS_PLAYBOOK_WORKER_ENABLED", "boolean"),
            ConfigField(
                "enforcement",
                "执行防线等级",
                "DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL",
                "select",
                ("ADVISORY_GUARD", "WORKTREE_BROKER", "CONTAINER_SANDBOX"),
                hint=(
                    "作用：设定诊断执行时采用的防线强度，依次为建议、工作树代理与容器沙箱。\n"
                    "前提：强制防线必须有经过验证且绑定当前 Agent 的执行环境；"
                    "每次执行都会重新核验，未通过则回退到建议防线。"
                ),
            ),
        ),
    ),
    "oauth": (
        "三方登录",
        (
            ConfigField("enabled", "启用 GitHub 登录", "OAUTH_GITHUB_ENABLED", "boolean"),
            ConfigField(
                "client_id",
                "GitHub Client ID",
                "OAUTH_GITHUB_CLIENT_ID",
                maximum=200,
                hint=(
                    "作用：GitHub OAuth 应用的应用标识，用于向 GitHub 发起授权。\n"
                    "前提：需先在 GitHub 开发者设置中创建 OAuth App；"
                    "Client ID、Client Secret 与回调地址必须来自同一个应用。"
                ),
            ),
            ConfigField("client_secret", "GitHub Client Secret", "OAUTH_GITHUB_CLIENT_SECRET", "secret"),
            ConfigField(
                "redirect_uri_web",
                "网页回调地址",
                "OAUTH_GITHUB_REDIRECT_URI_WEB",
                "url",
                maximum=500,
                hint=(
                    "作用：网页端完成登录后 GitHub 回跳的地址，用于接收授权码。\n"
                    "前提：必须与 GitHub OAuth App 中登记的 Callback URL 完全一致，"
                    "且该地址可从浏览器访问。"
                ),
            ),
            ConfigField(
                "redirect_uri_desktop",
                "客户端回调模板",
                "OAUTH_GITHUB_REDIRECT_URI_DESKTOP",
                "url",
                maximum=500,
                hint=(
                    "作用：桌面客户端登录使用的回调模板，"
                    "通常以自定义协议或本地端口接收授权码。\n"
                    "前提：需与 GitHub OAuth App 登记的回调地址匹配，"
                    "且客户端已注册对应的协议处理器。"
                ),
            ),
            ConfigField(
                "scope",
                "授权 Scope",
                "OAUTH_GITHUB_SCOPE",
                maximum=500,
                hint=(
                    "作用：向 GitHub 申请的授权范围，决定可读取的用户信息与权限。\n"
                    "前提：需填写 GitHub 支持的有效 scope；"
                    "建议按最小权限原则配置，变更后用户需重新授权。"
                ),
            ),
        ),
    ),
    "agent": (
        "Agent 引擎",
        (
            ConfigField(
                "backend",
                "默认 Agent 后端",
                "AGENT_BACKEND",
                "select",
                ("claude-code", "opencode", "dsh", "mock"),
                hint=(
                    "作用：新建会话默认使用的 Agent 引擎，可在具体会话中单独切换。\n"
                    "前提：所选引擎需已配置且可连通"
                    "（如 OpenCode/DSH 服务地址或 Claude Code 本地环境），否则会话启动会失败。"
                ),
            ),
            ConfigField(
                "opencode_url",
                "OpenCode 服务地址",
                "OPENCODE_SERVER_URL",
                "url",
                maximum=500,
                hint=(
                    "作用：OpenCode Server 的访问地址，供 Agent 引擎调用。\n"
                    "前提：仅在默认后端或会话选择 OpenCode 时生效；"
                    "需包含协议与端口，且服务已启动并可从后端访问。"
                ),
            ),
            ConfigField("opencode_username", "OpenCode 用户名", "OPENCODE_SERVER_USERNAME", maximum=200),
            ConfigField("opencode_password", "OpenCode 密码", "OPENCODE_SERVER_PASSWORD", "secret"),
            ConfigField(
                "dsh_url",
                "DSH Web Host 地址",
                "DSH_SERVER_URL",
                "url",
                maximum=500,
                hint=(
                    "作用：DSH Web Host 的访问地址，供 Agent 引擎调用。\n"
                    "前提：仅在选用 DSH 后端时生效；"
                    "需包含协议与端口，且服务已启动并可从后端访问。"
                ),
            ),
            ConfigField("dsh_browser_token", "DSH 启动令牌", "DSH_BROWSER_TOKEN", "secret"),
            ConfigField("dsh_browser_cookie", "DSH 会话 Cookie", "DSH_BROWSER_COOKIE", "secret"),
        ),
    ),
}
