from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(default=...)
    redis_url: str = Field(default=...)
    jwt_secret: str = Field(default=...)
    frontend_url: str = Field(default=...)

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 365  # TODO: 1 year, tune later

    ws_auth_timeout_seconds: int = 10

    youdosudoku_api_key: str = Field(default=...)
    youdosudoku_endpoint: str = "https://youdosudoku.com/api"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


Config = Settings()
