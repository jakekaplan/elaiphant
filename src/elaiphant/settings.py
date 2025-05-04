from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    database_url: Optional[PostgresDsn] = Field(None, alias="DATABASE_URL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings() 