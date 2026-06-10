"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration.

    Values are read from environment variables (case-insensitive) and an
    optional ``.env`` file. See ``.env.example`` for documentation of each
    field.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- QRadar connection -------------------------------------------------
    qradar_host: str = Field(
        default="127.0.0.1",
        description="QRadar Console IP address or FQDN (no scheme).",
    )
    qradar_api_token: str = Field(
        default="",
        description="QRadar SEC authentication token.",
    )
    qradar_verify_ssl: bool = Field(
        default=False,
        description="Verify QRadar's TLS certificate. Disable for self-signed.",
    )
    qradar_api_version: str = Field(
        default="20.0",
        description="QRadar REST API version sent via the 'Version' header.",
    )

    # --- Reference set names ----------------------------------------------
    refset_ip: str = Field(default="Blocked_IPs")
    refset_hash: str = Field(default="Blocked_Hashes")
    refset_domain: str = Field(default="Blocked_Domains")
    refset_url: str = Field(default="Blocked_URLs")

    # --- Sync schedule -----------------------------------------------------
    sync_interval_seconds: int = Field(
        default=300,
        ge=10,
        description="Seconds between automatic QRadar polls.",
    )
    initial_sync_on_startup: bool = Field(
        default=True,
        description="Run a sync immediately when the service starts.",
    )

    # --- Service -----------------------------------------------------------
    service_port: int = Field(default=8443, ge=1, le=65535)
    log_level: str = Field(default="INFO")
    api_key: str = Field(
        default="changeme-secret-key",
        description="Bearer token required to read the feed endpoints.",
    )
    require_auth: bool = Field(
        default=True,
        description=(
            "Require 'Authorization: Bearer <API_KEY>' on the feed/metrics/"
            "admin endpoints. Set false (or leave API_KEY empty) to serve the "
            "feeds without any authentication."
        ),
    )

    # --- TLS ---------------------------------------------------------------
    enable_tls: bool = Field(
        default=True,
        description=(
            "Serve feeds over HTTPS with a self-signed cert. Set false to "
            "serve plain HTTP (e.g. when Fortigate cannot validate the "
            "self-signed certificate, or TLS is terminated upstream)."
        ),
    )
    cert_dir: str = Field(default="certs")
    log_dir: str = Field(default="logs")

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        value = value.upper().strip()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if value not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return value

    @field_validator("qradar_host")
    @classmethod
    def _strip_scheme(cls, value: str) -> str:
        """Accept a bare host even if the user pasted a full URL."""
        value = value.strip()
        for scheme in ("https://", "http://"):
            if value.lower().startswith(scheme):
                value = value[len(scheme) :]
        return value.rstrip("/")

    @property
    def qradar_base_url(self) -> str:
        return f"https://{self.qradar_host}"

    @property
    def scheme(self) -> str:
        """URL scheme this service listens on ('https' or 'http')."""
        return "https" if self.enable_tls else "http"

    @property
    def auth_enabled(self) -> bool:
        """Auth is enforced only when required AND a non-empty key is set."""
        return self.require_auth and bool(self.api_key.strip())

    @property
    def reference_sets(self) -> dict[str, str]:
        """Map feed type -> QRadar reference set name."""
        return {
            "ip": self.refset_ip,
            "hash": self.refset_hash,
            "domain": self.refset_domain,
            "url": self.refset_url,
        }


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (load env once per process)."""
    return Settings()
