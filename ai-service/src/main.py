"""SmartDrive Guardian AI Service — Main Entry Point (Laptop 1).

Runs the camera → AI pipeline → WebSocket server.
In TEST_MODE, publishes simulated events instead of camera data.
"""

import asyncio
import logging
import sys

from src.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("smartdrive.ai")


async def main():
    """Main entry point for the AI service."""
    logger.info("=" * 60)
    logger.info("SmartDrive Guardian AI Service — Starting")
    logger.info(f"  Host: {settings.AI_SERVER_HOST}")
    logger.info(f"  Port: {settings.AI_SERVER_PORT}")
    logger.info(f"  Test Mode: {settings.TEST_MODE}")
    logger.info("=" * 60)

    if settings.TEST_MODE:
        logger.info("Running in TEST/SIMULATION mode — no camera required")
        # Will be implemented in Phase 3
        logger.info("Test mode publisher: stub — implemented in Phase 3")
    else:
        logger.info("Running in PRODUCTION mode — camera required")
        logger.info(f"  Camera Index: {settings.CAMERA_INDEX}")
        logger.info(f"  Resolution: {settings.CAMERA_WIDTH}x{settings.CAMERA_HEIGHT}")
        # Will be implemented in Phase 2-3
        logger.info("Camera pipeline: stub — implemented in Phase 2")

    logger.info("AI service main: stub — WebSocket server implemented in Phase 3")

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("AI service shutting down")


if __name__ == "__main__":
    asyncio.run(main())
