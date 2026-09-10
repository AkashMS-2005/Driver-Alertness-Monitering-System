"""AI WebSocket client — connects to the AI service on Laptop 1.

Stub for Phase 1. Will be fully implemented in Phase 3 (AI networking layer).
"""

import logging

logger = logging.getLogger("smartdrive")


class AIWebSocketClient:
    """Connects to ws://{AI_SERVER_HOST}:{AI_SERVER_PORT}/ws/ai on Laptop 1.

    Receives sanitized AI detection results and forwards them to the
    ingestion pipeline → risk engine → dashboard WebSocket channels.
    """

    def __init__(self):
        self._connected = False
        self._ws = None

    async def start(self):
        """Start the AI WebSocket client. (Stub — implemented in Phase 3)"""
        logger.info("AI WebSocket client: stub — will connect in Phase 3")

    async def stop(self):
        """Stop the AI WebSocket client."""
        self._connected = False
