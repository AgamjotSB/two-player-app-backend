from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(default=...)
    redis_url: str = Field(default=...)
    jwt_secret: str = Field(default=...)

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 365  # TODO: 1 year, tune later

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


Config = Settings()
