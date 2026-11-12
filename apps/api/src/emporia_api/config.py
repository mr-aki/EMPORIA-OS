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
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "emporia-os"
    jwt_access_token_minutes: int = 60
    allow_registration: bool = False
    legacy_workspace_owner_email: str | None = None

    # Provider credentials are server-side secrets; never return these values from an API.
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    brave_search_api_key: SecretStr | None = None
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(env_prefix="EMPORIA_", env_file=".env", extra="ignore")


settings = Settings()
