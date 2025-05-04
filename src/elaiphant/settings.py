from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, Field
from typing import Optional
from pydantic_ai.models import KnownModelName


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    database_url: Optional[PostgresDsn] = Field(default=None)

    ai_model: KnownModelName = Field(
        default="openai:gpt-4o",
        description="LLM model string to use (e.g., openai:gpt-4o).",
    )

    model_config = SettingsConfigDict(
        env_prefix="ELAIPHANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
