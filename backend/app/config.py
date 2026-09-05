"""
SDD Native Platform - Global Configuration
使用 Pydantic Settings 管理环境变量和配置
"""

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _BACKEND_ROOT / ".env"


def _resolve_backend_path(raw_value: Optional[str], *, fallback: str) -> str:
    raw = str(raw_value or "").strip()
    candidate = raw or str(fallback or "").strip()
    if not candidate:
        candidate = "logs"
    if os.path.isabs(candidate):
        return os.path.abspath(candidate)
    return os.path.abspath(os.path.join(_BACKEND_ROOT, candidate))


class Settings(BaseSettings):
    """应用全局配置"""

    # ── App ──
    APP_NAME: str = "SDD Native Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # ── Database ──
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = Field(..., min_length=1)
    DB_NAME: str = "sdd_platform"
    # SQLAlchemy echo（打印每条 SQL 及参数）：默认关闭，避免 DEBUG 启动时日志刷屏；排查 SQL 时置 true
    SQL_ECHO: bool = False
    # MySQL 连接/读写超时（秒），透传 PyMySQL connect_args；防止 offload 线程被无超时查询永久占用
    DB_CONNECT_TIMEOUT: int = 10
    DB_READ_TIMEOUT: int = 30
    DB_WRITE_TIMEOUT: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 3600
    # 同步 DB offload 线程池（app.core.offload）：db 专用 4 起步，压测后调整；git/文件独立池避免互相拖死
    DB_OFFLOAD_WORKERS: int = 4
    GIT_OFFLOAD_WORKERS: int = 4
    FILE_OFFLOAD_WORKERS: int = 2
    # 本地 git 命令硬超时（秒）：subprocess_runner 统一注入，超时整组回收，防止 offload 线程被挂死 git 永久占用
    GIT_COMMAND_TIMEOUT_SECONDS: int = 180

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    # ── JWT Authentication ──
    JWT_SECRET_KEY: str = Field(..., min_length=16)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 days for debug
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── OAuth 三方登录（设计文档 §4.1）──
    # 命名约定：OAUTH_{PROVIDER_UPPER}_ 前缀；provider 适配类通过 name.upper() 拼 key 读取
    # （providers/base.oauth_setting）→ 新增 provider 只需在 .env 加键，无需改本文件（NFR-M1）。
    # GitHub（首批唯一 provider，拍板 #2）；CLIENT_ID 留空 = 该 provider 不启用（NFR-M2）
    OAUTH_GITHUB_CLIENT_ID: str = ""
    # 🔴 仅服务端使用，绝不下发前端
    OAUTH_GITHUB_CLIENT_SECRET: str = ""
    # Web 端回调地址，如 https://api.traceforge.internal/api/auth/oauth/github/callback
    OAUTH_GITHUB_REDIRECT_URI_WEB: str = ""
    # Electron 端回调模板；运行时由后端按 loopback_port 替换为 http://127.0.0.1:{port}/callback（RFC 8252）
    OAUTH_GITHUB_REDIRECT_URI_DESKTOP: str = "http://127.0.0.1/callback"
    # 最小权限 Scope（NFR-S8）
    OAUTH_GITHUB_SCOPE: str = "read:user,user:email"
    # ── Stub（本地 Demo，非三方接入）──
    # 真实三方登录需登记回调地址，内网/localhost 无法被回调；Stub 在本地模拟 IdP，
    # 走与 GitHub 完全相同的真实后端链路（state→ticket→三路判定→JWT）供演示验证。
    # 🔴 生产必须保持 false：stub 不校验任何真实身份，等于「任意免密登录」。
    OAUTH_STUB_ENABLED: bool = False
    # 仅演示用的占位凭据（无真实权限；是否启用只看 OAUTH_STUB_ENABLED）
    OAUTH_STUB_CLIENT_ID: str = "stub-demo-client"
    OAUTH_STUB_CLIENT_SECRET: str = "stub-demo-secret"
    # Web 端回调（Demo）：后端不在 127.0.0.1:8000 时请在 .env 覆盖为实际地址
    OAUTH_STUB_REDIRECT_URI_WEB: str = "http://127.0.0.1:8000/api/auth/oauth/stub/callback"
    # Electron 端回调模板（Demo 占位，本演示不使用桌面端）
    OAUTH_STUB_REDIRECT_URI_DESKTOP: str = "http://127.0.0.1/callback"
    # state 有效期 10 min（NFR-S4）
    OAUTH_STATE_TTL_SECONDS: int = 600
    # ticket 有效期 10 min（E-17）
    OAUTH_TICKET_TTL_SECONDS: int = 600
    # 路径 B 最大密码尝试次数（E-18）
    OAUTH_BIND_MAX_ATTEMPTS: int = 5
    # 连续失败后的冷却时长 15 min（E-18 / NFR-S6）
    OAUTH_BIND_COOLDOWN_SECONDS: int = 900
    # 三方 HTTP 超时（K-3 / NFR-P2：connect 5s / read 10s）
    OAUTH_HTTP_CONNECT_TIMEOUT: float = 5.0
    OAUTH_HTTP_READ_TIMEOUT: float = 10.0
    # 仅网络类错误的重试次数（K-3 / NFR-P3）
    OAUTH_HTTP_MAX_RETRIES: int = 1
    # 注册域名白名单：逗号分隔域名后缀（如 corp.com,example.com）；留空 = 不限制（拍板 #4）
    REGISTER_EMAIL_DOMAIN_WHITELIST: str = ""
    # 后端 302 跳转用的前端基址（如 http://localhost:5173）
    FRONTEND_BASE_URL: str = ""

    # ── Agent Backend ──
    AGENT_BACKEND: str = "claude-code"  # claude-code | opencode | dsh | mock
    OPENCODE_SERVER_URL: str = "http://127.0.0.1:4097"
    # DSH 会话持久化根（空 = 跟随 dsh 默认 ~/.dsh/sessions）；
    # Web Host fork 读取与写入都指向该目录树
    DSH_SESSION_ROOT: str = ""
    # DSH Web Host 服务地址（`dsh web --no-open --port N` 启动）。
    # dsh 仅支持 Web Host server 模式，不再存在 headless CLI 回退。
    DSH_SERVER_URL: str = "http://127.0.0.1:3080"
    # dsh web authenticates every API request with its launch-token exchange.
    # These values are used only by the adapter's private HTTP client and are
    # never copied into task/session metadata.
    DSH_BROWSER_TOKEN: str = ""
    DSH_BROWSER_COOKIE: str = ""

    # ── Claude CLI Bridge ──
    SDD_CLI_MODE: str = "real"  # "mock" or "real"
    CLAUDE_CLI_PATH: str = "claude"
    CLAUDE_CLI_TIMEOUT: int = 300  # legacy compatibility only
    AGENT_STARTUP_TIMEOUT_SECONDS: int = 60
    AGENT_IDLE_TIMEOUT_SECONDS: int = 600
    AGENT_MAX_RUNTIME_SECONDS: int = 7200
    PLATFORM_API_BASE_URL: str = "http://localhost:8000"

    # ── Workflow ──
    MAX_RETRY_COUNT: int = 3
    SKILLS_STORAGE_ROOT: str = "storage/skills"
    SKILL_MAX_TEXT_FILE_SIZE_BYTES: int = 10 * 1024 * 1024

    # ── Task document scanning ──
    # 计划/规格 Markdown 扫描根目录（相对 task.project_path，逗号分隔；"." 表示项目根）
    TASK_PLAN_DOC_ROOTS: str = "docs/superpowers,superpowers/docs/superpowers,."
    # 任务执行时注入上下文的项目规则/文档路径，逗号分隔；目录会递归扫描 .md/.markdown
    TASK_RULE_DOC_SCAN_PATHS: str = "CLAUDE.md,.claude/CLAUDE.md,docs/superpowers,superpowers/docs/superpowers"

    @property
    def SKILLS_STORAGE_ROOT_ABS(self) -> str:
        """Resolve SKILLS_STORAGE_ROOT against the backend root so the skill
        package path does not change when the process CWD changes."""
        return _resolve_backend_path(self.SKILLS_STORAGE_ROOT, fallback="storage/skills")
    API_MOCK_TEMP_ROOT: str = "tmp/api_mock_workspace"
    CLI_STATE_ROOT: str = "tmp/cli_state"
    WORKSPACE_ARCHIVE_ROOT: str = "tmp/workspace_archive"
    # Undo checkpoints live outside task worktrees and are removed after a
    # successful operation.  Keeping this configurable also makes live tests
    # able to assert that no secret-bearing temporary file remains.
    TASK_SESSION_SNAPSHOT_ROOT: str = "tmp/task_session_snapshots"
    TASK_SESSION_REVERT_WAIT_SECONDS: float = 30.0
    CLI_BOOTSTRAP_TIMEOUT: int = 1800  # seconds
    CLI_CLEANUP_RETRY_COUNT: int = 5
    CLI_CLEANUP_RETRY_INTERVAL_MS: int = 600
    SKILL_GITHUB_IMPORT_GIT_TIMEOUT_SECONDS: int = 240
    SKILL_GITHUB_IMPORT_STALE_GRACE_SECONDS: int = 60
    TASK_CHANGE_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    TASK_CHANGE_DIFF_EXCERPT_CHARS: int = 12000
    TASK_CHANGE_PROPOSAL_QUEUE_WAIT_TIMEOUT_SECONDS: float = 120.0
    TASK_CHANGE_PROPOSAL_QUEUE_POLL_INTERVAL_SECONDS: float = 0.1

    # ── WorkflowEngine 事件落库批处理 ──
    # context segment 批量写入：按条数或时间窗触发（结束/异常/HITL 前强制 flush）
    SEGMENT_FLUSH_INTERVAL_SECONDS: float = 0.2
    SEGMENT_FLUSH_MAX_ITEMS: int = 50
    # thinking WS 帧节流：delta 帧按此窗口合并发送，快照帧立即发
    THINKING_WS_INTERVAL_SECONDS: float = 0.2
    # skill runtime trace writer 队列上限：满则丢弃并限频告警，避免无界堆积
    SKILL_TRACE_QUEUE_MAX_SIZE: int = 1000
    # 事件门禁 TTL：缓存 job/task revision 状态，过期后经 DB 重校验一次（周期兜底）
    REVISION_GATE_TTL_SECONDS: float = 1.0

    # ── WebSocket 出站背压 ──
    # 每连接出站队列条数上限 + 未确认字节上限，双重限长；超限断开该慢客户端，只影响其自身
    WS_OUTBOUND_QUEUE_SIZE: int = 256
    WS_OUTBOUND_MAX_BYTES: int = 1024 * 1024

    # ── CORS ──
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
        "http://127.0.0.1:5177",
        "http://127.0.0.1:5178",
        "null",
        "http://localhost:3000"
    ]
    CORS_ORIGIN_REGEX: Optional[str] = r"^https?://(localhost|127\.0\.0\.1):\d+$"

    # ── Logging ──
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    AI_SESSION_LOG_DIR: str = ""
    LOG_JSON_FILES: bool = True
    LOG_ROTATION: str = "50 MB"
    LOG_RETENTION: str = "10 days"
    LOG_ENQUEUE: bool = True

    # ── Redis / Distributed Lock ──
    REDIS_ENABLED: bool = False
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 3.0
    REDIS_CONNECT_TIMEOUT_SECONDS: float = 3.0

    DISTRIBUTED_LOCK_BACKEND: str = "local"  # local | redis
    DISTRIBUTED_LOCK_KEY_PREFIX: str = "sdd-native"
    DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS: int = 60
    DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS: float = 5.0
    DISTRIBUTED_LOCK_SLEEP_SECONDS: float = 0.1
    DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK: bool = False

    TASK_LOCK_TTL_SECONDS: int = 120
    SKILL_LOCK_TTL_SECONDS: int = 120
    WORKSPACE_LOCK_TTL_SECONDS: int = 180
    AI_JOB_LOCK_TTL_SECONDS: int = 60
    BOOTSTRAP_LOCK_TTL_SECONDS: int = 300
    CHAT_MESSAGE_IDEMPOTENCY_TTL_SECONDS: int = 86400
    TASK_CREATE_QUEUE_WAIT_TIMEOUT_SECONDS: float = 120.0
    TASK_CREATE_QUEUE_POLL_INTERVAL_SECONDS: float = 0.1
    BACKGROUND_QUEUE_WAIT_TIMEOUT_SECONDS: float = 900.0
    BACKGROUND_QUEUE_POLL_INTERVAL_SECONDS: float = 0.1
    BACKGROUND_QUEUE_DEFAULT_MAX_CONCURRENT: int = 2
    PROVISION_QUEUE_MAX_CONCURRENT: int = 2
    API_MOCK_QUEUE_MAX_CONCURRENT: int = 2
    BOOTSTRAP_QUEUE_MAX_CONCURRENT: int = 2

    # ── RAG 适配层 ──
    # 当前只实现适配层：httpx / mock；具体平台（WeKnora / LLMWiki 等）后续按选型结果追加
    RAG_ENABLED: bool = False
    RAG_PROVIDER: str = "mock"
    RAG_API_BASE_URL: str = ""
    RAG_API_KEY: str = ""
    RAG_API_TIMEOUT_SECONDS: int = 10
    RAG_INGEST_BATCH_SIZE: int = 20
    RAG_INGEST_INTERVAL_SECONDS: float = 5.0
    RAG_RETRY_MAX: int = 5
    RAG_RETRY_BACKOFF_BASE_SECONDS: int = 2

    # ── 站内信 / 外部通知 ──
    # 站内信始终落库；NOTIFICATION_PROVIDERS 为额外启用的外部渠道（逗号分隔，当前仅支持 "logging" 占位）
    NOTIFICATION_PROVIDERS: str = ""
    # 预输入超时扫描
    PRE_INPUT_SCAN_INTERVAL_SECONDS: float = 5.0

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _normalize_path_settings(self):
        self.LOG_DIR = _resolve_backend_path(self.LOG_DIR, fallback="logs")
        self.AI_SESSION_LOG_DIR = _resolve_backend_path(
            self.AI_SESSION_LOG_DIR,
            fallback=os.path.join(self.LOG_DIR, "ai_sessions"),
        )
        self.SKILLS_STORAGE_ROOT = _resolve_backend_path(
            self.SKILLS_STORAGE_ROOT,
            fallback="storage/skills",
        )
        self.API_MOCK_TEMP_ROOT = _resolve_backend_path(
            self.API_MOCK_TEMP_ROOT,
            fallback="tmp/api_mock_workspace",
        )
        self.CLI_STATE_ROOT = _resolve_backend_path(
            self.CLI_STATE_ROOT,
            fallback="tmp/cli_state",
        )
        self.WORKSPACE_ARCHIVE_ROOT = _resolve_backend_path(
            self.WORKSPACE_ARCHIVE_ROOT,
            fallback="tmp/workspace_archive",
        )
        self.TASK_SESSION_SNAPSHOT_ROOT = _resolve_backend_path(
            self.TASK_SESSION_SNAPSHOT_ROOT,
            fallback="tmp/task_session_snapshots",
        )
        return self


settings = Settings()
