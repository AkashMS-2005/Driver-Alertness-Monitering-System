"""Backend configuration — reads from environment variables and .env file."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend root BEFORE pydantic-settings reads anything
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)


def _parse_backoff() -> list[int]:
    raw = os.getenv("AI_RECONNECT_BACKOFF_SECONDS", "2,5,10,20")
    return [int(x.strip()) for x in raw.split(",")]


def _parse_cors() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")
    return [x.strip() for x in raw.split(",")]


class Settings:
    """Application settings for the backend (Laptop 2)."""

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://smartdrive:smartdrive_secret@localhost:5432/smartdrive_guardian",
    )
    DATABASE_URL_SYNC: str = os.getenv(
        "DATABASE_URL_SYNC",
        "postgresql://smartdrive:smartdrive_secret@localhost:5432/smartdrive_guardian",
    )

    # AI Service connection (Laptop 1)
    AI_SERVER_HOST: str = os.getenv("AI_SERVER_HOST", "192.168.1.101")
    AI_SERVER_PORT: int = int(os.getenv("AI_SERVER_PORT", "8001"))
    AI_HEARTBEAT_TIMEOUT_SECONDS: int = int(
        os.getenv("AI_HEARTBEAT_TIMEOUT_SECONDS", "8")
    )
    AI_RECONNECT_BACKOFF_SECONDS: list[int] = _parse_backoff()

    # Server
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "0.0.0.0")
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    CORS_ORIGINS: list[str] = _parse_cors()

    @property
    def ai_ws_url(self) -> str:
        """Full WebSocket URL to connect to the AI service on Laptop 1."""
        return f"ws://{self.AI_SERVER_HOST}:{self.AI_SERVER_PORT}/ws/ai"


settings = Settings()
