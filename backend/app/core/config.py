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
    raw = os.getenv(
        "CORS_ORIGINS",
        # Vite dev server auto-increments the port when the default is taken.
        # All common Vite ports (5173–5180) are allowed in development.
        # In production, set CORS_ORIGINS in backend/.env to your actual domain.
        "http://localhost:5173,http://localhost:5174,http://localhost:5175,"
        "http://localhost:5176,http://localhost:5177,http://localhost:5178,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5175,"
        "http://127.0.0.1:5176,http://127.0.0.1:5177,http://127.0.0.1:5178"
    )
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

    # Emergency Engine — configurable thresholds
    # EMERGENCY_COOLDOWN_SECONDS: wait time before a new emergency can fire after
    #   the previous one was CANCELLED or RESOLVED.
    EMERGENCY_COOLDOWN_SECONDS: int = int(
        os.getenv("EMERGENCY_COOLDOWN_SECONDS", "60")
    )
    # RECOVERY_CONFIRMATION_SECONDS: continuous NORMAL + drowsiness <= 50% window
    #   required before the emergency transitions to DRIVER_RECOVERED.
    RECOVERY_CONFIRMATION_SECONDS: int = int(
        os.getenv("RECOVERY_CONFIRMATION_SECONDS", "10")
    )

    # SMS / Highway Assistance Communication (Twilio)
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    TOLL_ASSISTANCE_PHONE_NUMBER: str = os.getenv("TOLL_ASSISTANCE_PHONE_NUMBER", "")
    TWILIO_STATUS_CALLBACK_URL: str = os.getenv("TWILIO_STATUS_CALLBACK_URL", "")
    TWILIO_WEBHOOK_VALIDATE_SIGNATURE: bool = (
        os.getenv("TWILIO_WEBHOOK_VALIDATE_SIGNATURE", "false").lower() == "true"
    )

    @property
    def ai_ws_url(self) -> str:
        """Full WebSocket URL to connect to the AI service on Laptop 1."""
        return f"ws://{self.AI_SERVER_HOST}:{self.AI_SERVER_PORT}/ws/ai"


settings = Settings()
