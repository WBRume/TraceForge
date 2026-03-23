"""
SDD Native Platform - Global Configuration
使用 Pydantic Settings 管理环境变量和配置
"""

from pydantic_settings import BaseSettings
from typing import Optional


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
    DB_PASSWORD: str = "root"
    DB_NAME: str = "sdd_platform"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    # ── JWT Authentication ──
    JWT_SECRET_KEY: str = "sdd-native-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Claude CLI Bridge ──
    SDD_CLI_MODE: str = "real"  # "mock" or "real"
    CLAUDE_CLI_PATH: str = "claude"
    CLAUDE_CLI_TIMEOUT: int = 300  # seconds

    # ── Workflow ──
    MAX_RETRY_COUNT: int = 3

    # ── CORS ──
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://localhost:3000"
    ]

    # ── Logging ──
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


settings = Settings()
