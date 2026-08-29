"""Application settings, loaded from environment / .env (git-ignored)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- App ----
    app_env: str = "development"
    api_base_url: str = "http://localhost:8000"
    secret_key: str = "dev-secret-key-not-for-production"
    access_token_expire_minutes: int = 720

    # ---- Persistence ----
    # sqlite:///./data/app.db  (zero-config) or postgresql+psycopg://app:app@localhost:5432/app
    database_url: str = "sqlite:///./data/app.db"

    # ---- Rate limiting (fixed window) ----
    rate_limit_ip_window_seconds: int = 60
    rate_limit_ip_max: int = 30
    rate_limit_widget_window_seconds: int = 60
    rate_limit_widget_max: int = 20
    # Number of trusted reverse proxies sitting between the internet and this
    # app. 0 (default): X-Forwarded-For is ignored entirely and the socket
    # peer address is used, so spoofed headers can't deflect rate limits or
    # pollute geo/IP records. With N>0 the XFF entry written by the outermost
    # trusted proxy is used as the client address; anything left of it is
    # untrusted forgeries.
    trust_proxy_count: int = 0

    # ---- Payload guard ----
    max_payload_bytes: int = 16384

    # ---- Geo enrichment ----
    geo_mode: str = "live"  # live | mock
    geo_provider_a_url: str = "https://ip-api.com/json/"
    geo_provider_b_url: str = "https://ipapi.co/{ip}/json/"
    geo_provider_b_api_key: str = ""
    geo_timeout_seconds: float = 2.0
    # Only read when geo_mode == "mock" — deterministic toggles for the
    # fallback-chain proof:
    geo_provider_a_enabled: bool = True
    geo_provider_b_enabled: bool = True

    # ---- Side effects (email / webhook) ----
    mail_mode: str = "console"  # console | stderr | fail | smtp
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "noreply@localhost"
    webhook_url: str = ""

    # ---- Background worker ----
    worker_poll_seconds: float = 2.0
    worker_max_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()