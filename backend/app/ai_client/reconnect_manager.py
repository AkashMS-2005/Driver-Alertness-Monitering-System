"""Reconnect manager — handles exponential backoff for AI WebSocket reconnection.

Stub for Phase 1. Will be fully implemented in Phase 3.
"""

import logging

logger = logging.getLogger("smartdrive")


class ReconnectManager:
    """Manages reconnection attempts with configurable backoff."""

    def __init__(self, backoff_seconds=None):
        self.backoff_seconds = backoff_seconds or [2, 5, 10, 20]
        self._attempt = 0

    def next_delay(self) -> int:
        """Get the next backoff delay in seconds."""
        delay = self.backoff_seconds[min(self._attempt, len(self.backoff_seconds) - 1)]
        self._attempt += 1
        return delay

    def reset(self):
        """Reset the backoff counter (called on successful connection)."""
        self._attempt = 0
