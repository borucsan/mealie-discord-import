"""Configuration settings for the Mealie Discord bot"""

import os
from typing import Optional
from pathlib import Path

from pydantic import field_validator, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = ConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Discord settings
    discord_token: str = "test_token"  # Default for testing
    discord_guild_id: Optional[int] = None
    discord_command_prefix: str = "!mealie"

    # Mealie settings
    mealie_base_url: str = "https://test-mealie.com"  # Default for testing
    mealie_api_token: str = "test_api_token"  # Default for testing
    mealie_username: Optional[str] = None
    mealie_password: Optional[str] = None

    # Bot settings
    bot_log_level: str = "INFO"
    bot_timeout: int = 30  # seconds

    # Recipe settings
    default_recipe_tags: str = "Discord Import,Verify"  # Comma-separated string
    require_instructions: bool = True
    require_ingredients: bool = True

    # AI settings (for future use)
    openai_api_key: Optional[str] = None
    ai_enabled: bool = False
    ai_model: str = "gpt-3.5-turbo"

    @field_validator('mealie_base_url')
    @classmethod
    def validate_mealie_url(cls, v):
        """Ensure Mealie URL is properly formatted"""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Mealie URL must start with http:// or https://')
        return v.rstrip('/')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Load from .env file in project root if it exists
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)


# Global settings instance
settings = Settings()
