"""AI event receiver — normalizes incoming AI detection JSON.

Stub for Phase 1. Full implementation in Phase 3-4.
"""

import logging

logger = logging.getLogger("smartdrive")


class AIEventReceiver:
    """Receives and normalizes AI detection events from the AI WebSocket client."""

    @staticmethod
    def normalize(raw_event: dict) -> dict:
        """Normalize an incoming AI event into the internal format.

        Expected input (sanitized — no raw CV metrics):
        {
            "timestamp": "2026-09-09T10:15:32.120Z",
            "driver_status": "Drowsy",
            "risk_level": "HIGH",
            "fatigue_level": 72,
            "distraction_status": "Normal",
            "alert_message": "Please take a break"
        }
        """
        return {
            "timestamp": raw_event.get("timestamp"),
            "driver_status": raw_event.get("driver_status", "Unknown"),
            "risk_level": raw_event.get("risk_level", "SAFE"),
            "fatigue_level": raw_event.get("fatigue_level", 0),
            "distraction_status": raw_event.get("distraction_status", "Normal"),
            "alert_message": raw_event.get("alert_message"),
        }
