from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Emporia OS API"
    environment: str = "development"
    database_url: str = "sqlite:///./emporia.db"
    api_token: str = "change-me-before-deploy"
    workspace_id: str = "local-workspace"
    cors_origins: str = ""

    model_config = SettingsConfigDict(env_prefix="EMPORIA_", env_file=".env", extra="ignore")


settings = Settings()
