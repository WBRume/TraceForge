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

    # ── Agent Backend ──
    AGENT_BACKEND: str = "claude-code"  # claude-code | opencode | dsh | mock
    OPENCODE_SERVER_URL: str = "http://127.0.0.1:4097"
    DSH_CLI_PATH: str = "dsh"
    # DSH 会话持久化根（空 = 跟随 dsh 默认 ~/.dsh/sessions）；
    # 显式配置时子进程写入与 fork 读取都指向该目录树
    DSH_SESSION_ROOT: str = ""
    # DSH Web Host 服务地址（`dsh web --no-open --port N` 启动）；配置后 dsh 后端
    # 走 server 模式（支持 resume / 工具事件 / usage / 多轮），否则回退 headless CLI
    DSH_SERVER_URL: str = ""

    # ── Claude CLI Bridge ──
    SDD_CLI_MODE: str = "real"  # "mock" or "real"
    CLAUDE_CLI_PATH: str = "claude"
    CLAUDE_CLI_TIMEOUT: int = 300  # seconds
    PLATFORM_API_BASE_URL: str = "http://localhost:8000"

    # ── Workflow ──
    MAX_RETRY_COUNT: int = 3
    SKILLS_STORAGE_ROOT: str = "storage/skills"
    SKILL_MAX_TEXT_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
    API_MOCK_TEMP_ROOT: str = "tmp/api_mock_workspace"
    CLI_STATE_ROOT: str = "tmp/cli_state"
    WORKSPACE_ARCHIVE_ROOT: str = "tmp/workspace_archive"
    CLI_BOOTSTRAP_TIMEOUT: int = 1800  # seconds
    CLI_CLEANUP_RETRY_COUNT: int = 5
    CLI_CLEANUP_RETRY_INTERVAL_MS: int = 600
    SKILL_GITHUB_IMPORT_GIT_TIMEOUT_SECONDS: int = 240
    SKILL_GITHUB_IMPORT_STALE_GRACE_SECONDS: int = 60
    TASK_CHANGE_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    TASK_CHANGE_DIFF_EXCERPT_CHARS: int = 12000
    TASK_CHANGE_PROPOSAL_QUEUE_WAIT_TIMEOUT_SECONDS: float = 120.0
    TASK_CHANGE_PROPOSAL_QUEUE_POLL_INTERVAL_SECONDS: float = 0.1

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
        return self


settings = Settings()
