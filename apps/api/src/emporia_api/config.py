from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Emporia OS API"
    environment: str = "development"
    database_url: str = "sqlite:///./emporia.db"
    api_token: str = "change-me-before-deploy"
    workspace_id: str = "local-workspace"
    cors_origins: str = ""
    agent_max_output_tokens: int = Field(default=2048, ge=1, le=4096)
    skill_max_output_tokens: int = Field(default=2048, ge=1, le=4096)
    agent_runs_per_minute: int = Field(default=10, ge=1, le=600)
    skill_runs_per_minute: int = Field(default=20, ge=1, le=600)
    agent_max_concurrent_runs: int = Field(default=3, ge=1, le=100)
    skill_max_concurrent_runs: int = Field(default=5, ge=1, le=100)
    execution_lease_seconds: int = Field(default=300, ge=60, le=3600)
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "emporia-os"
    jwt_access_token_minutes: int = 60
    allow_registration: bool = False
    legacy_workspace_owner_email: str | None = None
    worker_poll_seconds: int = Field(default=2, ge=1, le=60)
    worker_lease_seconds: int = Field(default=300, ge=30, le=3600)
    worker_backoff_base_seconds: int = Field(default=5, ge=1, le=300)
    worker_backoff_max_seconds: int = Field(default=300, ge=1, le=3600)
    job_submissions_per_minute: int = Field(default=20, ge=1, le=600)
    research_reports_per_minute: int = Field(default=5, ge=1, le=120)
    shopify_api_version: str = Field(default="2026-10", pattern=r"^\d{4}-\d{2}$")
    login_attempts_per_email_window: int = Field(default=5, ge=1, le=100)
    login_attempts_per_ip_window: int = Field(default=30, ge=1, le=1000)
    login_rate_limit_window_seconds: int = Field(default=60, ge=10, le=3600)

    # Provider credentials are server-side secrets; never return these values from an API.
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    brave_search_api_key: SecretStr | None = None
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: SecretStr | None = None
    shopify_client_id: str | None = None
    shopify_client_secret: SecretStr | None = None
    shopify_redirect_uri: str | None = None
    shopify_encryption_key: SecretStr | None = None

    model_config = SettingsConfigDict(env_prefix="EMPORIA_", env_file=".env", extra="ignore")


settings = Settings()
