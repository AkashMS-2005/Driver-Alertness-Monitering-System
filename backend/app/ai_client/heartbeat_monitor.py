"""Heartbeat monitor — tracks AI service liveness.

Stub for Phase 1. Will be fully implemented in Phase 3.
"""

import logging

logger = logging.getLogger("smartdrive")


class HeartbeatMonitor:
    """Monitors heartbeat/detection cadence from the AI service.

    If no message arrives within AI_HEARTBEAT_TIMEOUT_SECONDS,
    flips connection state to DISCONNECTED.
    """

    def __init__(self, timeout_seconds: int = 8):
        self.timeout_seconds = timeout_seconds
        self._running = False

    async def start(self):
        """Start monitoring. (Stub — implemented in Phase 3)"""
        logger.info("Heartbeat monitor: stub — will start in Phase 3")

    async def stop(self):
        """Stop monitoring."""
        self._running = False
