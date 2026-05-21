import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Application configurations using Pydantic Settings.
    These are populated by environment variables or fallback to defaults.
    """
    # MongoDB Configs
    MONGODB_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "notification_db"

    # Redis Configs (Used for Rate Limiting, Celery Broker, and WebSockets Pub/Sub)
    REDIS_URI: str = "redis://localhost:6379/0"

    # Celery Configs
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # WebSocket Configs
    WS_CHANNEL_PREFIX: str = "ws:notification:"

    # Service Port
    PORT: int = 8000

    # Log Level
    LOG_LEVEL: str = "INFO"

    # Pydantic Settings Configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate singleton settings
settings = Settings()
