import os
import secrets
from pathlib import Path
from ipaddress import ip_address
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

load_dotenv()

DEFAULT_DATABASE_URL = f"sqlite:///{(Path(__file__).resolve().parents[2] / 'sem5.db').as_posix()}"


def local_llm_url(value: str) -> str:
    """Permit only credential-free loopback model servers, never hosted inference."""
    message = "OLLAMA_BASE_URL must be an HTTP(S) loopback URL without credentials, query or fragment."
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        raise ValueError(message) from None
    try:
        local = host == "localhost" or ip_address(host).is_loopback
    except ValueError:
        local = False
    if (not local or parsed.scheme not in {"http", "https"} or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or port == 0):
        raise ValueError(message)
    return value.rstrip("/")


def local_llm_model(value: str) -> str:
    if not value.strip() or 'cloud' in value.casefold().split(':')[-1] or '://' in value:
        raise ValueError("OLLAMA_MODEL must name an installed local model; cloud model tags are not permitted.")
    return value

class Settings(BaseSettings):
    model_config = {"hide_input_in_errors": True}
    API_V1_STR: str = "/api"
    DATABASE_URL: str = DEFAULT_DATABASE_URL
    DATASET_MAX_BYTES: int = Field(default=209715200, ge=1, le=209715200)
    DATASET_MAX_SPREADSHEET_EXPANDED_BYTES: int = Field(default=209715200, ge=1, le=536870912)
    DATASET_MAX_ROWS: int = Field(default=100000, ge=1)
    DATASET_MAX_COLUMNS: int = Field(default=100, ge=1, le=100)
    DATASET_MAX_CELLS: int = Field(default=2000000, ge=1)
    DATASET_MAX_SECONDS: int = Field(default=60, ge=1)
    BUNDLE_MAX_EXPANDED_BYTES: int = Field(default=536870912, ge=1, le=1073741824)
    BUNDLE_MAX_TABLE_ROWS: int = Field(default=1500000, ge=1)
    BUNDLE_MAX_TABLE_CELLS: int = Field(default=12000000, ge=1)
    BUNDLE_MAX_ROWS: int = Field(default=5000000, ge=1)
    BUNDLE_MAX_CELLS: int = Field(default=40000000, ge=1)
    BUNDLE_MAX_SECONDS: int = Field(default=900, ge=1, le=3600)
    SECRET_KEY: str = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    REFRESH_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_MINUTES", "10080"))
    ENV: str = os.getenv("ENV", "dev")

    # Auth / RBAC. Two roles only: admin and analyst.
    # Defaults to true: every protected router rejects anonymous callers with 401.
    AUTH_REQUIRED: bool = os.getenv("AUTH_REQUIRED", "true").lower() in {"1", "true", "yes"}
    AUTH_ADMIN_PASSWORD: str = os.getenv("AUTH_ADMIN_PASSWORD", "")
    AUTH_ANALYST_PASSWORD: str = os.getenv("AUTH_ANALYST_PASSWORD", "")

    # AI assistant (provider-agnostic; Ollama preferred)
    ENABLE_LLM_ASSISTANT: bool = os.getenv("ENABLE_LLM_ASSISTANT", "false").lower() in {"1", "true", "yes"}
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

    @field_validator("SECRET_KEY")
    @classmethod
    def private_secret_key(cls, value):
        if any(marker in value.casefold() for marker in ("replace_with_", "change_me_", "placeholder")):
            raise ValueError("Replace the SECRET_KEY example with a private random value before startup.")
        return value

    @field_validator("LLM_PROVIDER")
    @classmethod
    def free_provider(cls, value):
        if value != "ollama":
            raise ValueError("LLM_PROVIDER supports only ollama; use ENABLE_LLM_ASSISTANT=false for deterministic-only mode.")
        return value

    @field_validator("OLLAMA_BASE_URL")
    @classmethod
    def loopback_provider(cls, value):
        return local_llm_url(value)

    @field_validator("OLLAMA_MODEL")
    @classmethod
    def local_model(cls, value):
        return local_llm_model(value)

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def stable_default_database(cls, value):
        # The documented dev database must not depend on the launch directory.
        # Preserve explicit custom databases, including disposable test storage.
        if value in (None, "", "sqlite:///./sem5.db", "sqlite:///sem5.db"):
            return DEFAULT_DATABASE_URL
        return value

settings = Settings()
