"""Environment-driven application configuration for Bid2Work AI."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field, field_validator


def _load_dotenv_file(dotenv_path: Path) -> None:
    """Lightweight .env reader that populates os.environ if keys are not already set."""
    if not dotenv_path.is_file():
        return
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


# Attempt to load backend/.env if present
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_load_dotenv_file(_BACKEND_ROOT / ".env")


def _parse_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in ("true", "1", "yes", "t", "on")


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    app_name: str = Field(
        default_factory=lambda: os.getenv("APP_NAME", "Bid2Work AI")
    )
    app_env: str = Field(
        default_factory=lambda: os.getenv("APP_ENV", "development")
    )
    app_version: str = Field(
        default_factory=lambda: os.getenv("APP_VERSION", "0.1.0")
    )
    log_level: str = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper()
    )

    host: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))

    cors_allowed_origins_raw: str = Field(
        default_factory=lambda: os.getenv(
            "CORS_ALLOWED_ORIGINS",
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ),
        )
    )

    # Authentication and security
    secret_key: str = Field(
        default_factory=lambda: os.getenv(
            "SECRET_KEY",
            os.getenv("JWT_SECRET", "bid2work-ai-development-secret-key-change-in-production-2026"),
        )
    )
    token_expiry_hours: int = Field(
        default_factory=lambda: int(os.getenv("TOKEN_EXPIRY_HOURS", "72")),
        ge=1,
    )

    # Document & PDF upload safeguards
    max_upload_size_mb: int = Field(
        default_factory=lambda: int(
            os.getenv("MAX_UPLOAD_SIZE_MB", os.getenv("MAX_UPLOAD_MB", "25"))
        ),
        ge=1,
        le=200,
    )
    max_bidder_files: int = Field(
        default_factory=lambda: int(os.getenv("MAX_BIDDER_FILES", "10")),
        ge=1,
        le=50,
    )
    max_pages_per_pdf: int = Field(
        default_factory=lambda: int(os.getenv("MAX_PAGES_PER_PDF", "200")),
        ge=1,
        le=2000,
    )
    max_extracted_text_chars: int = Field(
        default_factory=lambda: int(os.getenv("MAX_EXTRACTED_TEXT_CHARS", "2000000")),
        ge=1000,
    )
    temp_upload_dir: str = Field(
        default_factory=lambda: os.getenv("TEMP_UPLOAD_DIR", "/tmp/bid2work_uploads")
    )

    # Persistence / SQLite database path
    sqlite_db_path: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            os.getenv(
                "SQLITE_DB_PATH",
                str(_BACKEND_ROOT / "data" / "bid2work_audit.db"),
            ),
        )
    )

    # External LLM API settings
    llm_enabled: bool = Field(
        default_factory=lambda: _parse_bool(os.getenv("LLM_ENABLED", "false"))
    )
    llm_provider: str = Field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "openai")
    )
    llm_api_key: str = Field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "")
    )
    llm_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "LLM_BASE_URL", "https://api.openai.com/v1"
        )
    )
    llm_model: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini")
    )
    llm_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        ge=5,
        le=300,
    )
    llm_max_retries: int = Field(
        default_factory=lambda: int(os.getenv("LLM_MAX_RETRIES", "2")),
        ge=0,
        le=5,
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        return upper if upper in allowed else "INFO"

    @property
    def cors_allowed_origins(self) -> List[str]:
        """Parse comma-separated origins into a clean list."""
        raw = self.cors_allowed_origins_raw.strip()
        if not raw:
            return []
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def is_llm_configured(self) -> bool:
        """Check whether a non-placeholder API key has been provided."""
        key = (self.llm_api_key or "").strip()
        placeholders = {
            "",
            "your_api_key_here",
            "your_llm_api_key_placeholder_here",
            "changeme",
            "none",
            "sk-placeholder",
        }
        return key.lower() not in placeholders

    def validate_live_llm_config(self) -> None:
        """Raise ConfigurationError if live mode is enabled but no valid key is present."""
        if self.llm_enabled and not self.is_llm_configured:
            from app.core.exceptions import ConfigurationError

            raise ConfigurationError(
                "Live LLM mode is enabled (LLM_ENABLED=true), but LLM_API_KEY is missing or contains "
                "a placeholder value. Set a valid LLM_API_KEY or configure LLM_ENABLED=false for mock mode."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
