"""AI Service configuration — reads from environment variables and .env file."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from ai-service root
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


class AISettings:
    """Configuration for the AI service (Laptop 1)."""

    # WebSocket server
    AI_SERVER_HOST: str = os.getenv("AI_SERVER_HOST", "0.0.0.0")
    AI_SERVER_PORT: int = int(os.getenv("AI_SERVER_PORT", "8001"))

    # Mode
    TEST_MODE: bool = os.getenv("TEST_MODE", "false").lower() == "true"

    # Heartbeat
    HEARTBEAT_INTERVAL_SECONDS: float = float(
        os.getenv("HEARTBEAT_INTERVAL_SECONDS", "2")
    )

    # Camera
    CAMERA_INDEX: int = int(os.getenv("CAMERA_INDEX", "0"))
    CAMERA_WIDTH: int = int(os.getenv("CAMERA_WIDTH", "640"))
    CAMERA_HEIGHT: int = int(os.getenv("CAMERA_HEIGHT", "480"))
    CAMERA_FPS: int = int(os.getenv("CAMERA_FPS", "30"))

    # Thresholds file
    THRESHOLDS_PATH: str = str(
        Path(__file__).resolve().parent / "thresholds.yaml"
    )


settings = AISettings()
