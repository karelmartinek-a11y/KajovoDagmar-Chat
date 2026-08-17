from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InfrastructureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KAJOVODAGMAR_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    public_origin: str = "https://chat.hcasc.cz"
    database_url: str = "postgresql+asyncpg://kajovodagmar@db/kajovodagmar"
    root_encryption_key: SecretStr
    initialization_secret_hash: SecretStr
    session_cookie_name: str = "__Host-kajovodagmar_session"
    log_level: str = "INFO"
    log_directory: Path = Path("runtime/logs")
    static_directory: Path = Path("web/dist")
    export_directory: Path = Path("runtime/exports")
    metrics_token: SecretStr | None = None
    trusted_proxy_cidrs: tuple[str, ...] = ()
    otlp_endpoint: str | None = None
    telemetry_service_name: str = "kajovodagmar"
    voice_service_api_key_file: Path = Path("/run/secrets/voice-service-api-key")

    @field_validator("public_origin")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        if not value.startswith("https://") and value not in {
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        }:
            raise ValueError("Veřejný origin musí používat HTTPS.")
        return value.rstrip("/")

    @field_validator("root_encryption_key")
    @classmethod
    def validate_root_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 43:
            raise ValueError("Kořenový šifrovací klíč musí být URL-safe base64 klíč o 32 bytech.")
        return value


@lru_cache(maxsize=1)
def get_settings() -> InfrastructureSettings:
    return InfrastructureSettings()  # type: ignore[call-arg]
