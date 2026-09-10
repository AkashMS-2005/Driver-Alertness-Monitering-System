"""Risk Engine — State Machine & State Transition Manager.

Phase 4: Drowsiness risk interpretation, state transitions, and safety event generation.
Maps:
  NORMAL     → Risk: LOW     | Alert: Driver Alert
  DROWSY     → Risk: MEDIUM  | Alert: Driver Attention Required
  MICROSLEEP → Risk: HIGH    | Alert: Immediate attention required
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("smartdrive.risk_engine")

STATE_NORMAL = "NORMAL"
STATE_DROWSY = "DROWSY"
STATE_MICROSLEEP = "MICROSLEEP"

RISK_MAP = {
    STATE_NORMAL: "LOW",
    STATE_DROWSY: "MEDIUM",
    STATE_MICROSLEEP: "HIGH",
}

ALERT_MAP = {
    STATE_NORMAL: "Driver Alert",
    STATE_DROWSY: "Driver Attention Required",
    STATE_MICROSLEEP: "Immediate attention required",
}


class SafetyStateMachine:
    """Interprets AI drowsiness detections, detects transitions, and logs safety events."""

    def __init__(self):
        self._current_state = STATE_NORMAL
        self._previous_state = None
        self._recent_events: List[Dict[str, Any]] = []
        self._max_recent_events = 20

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def previous_state(self) -> Optional[str]:
        return self._previous_state

    def get_recent_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent safety events (newest first)."""
        return self._recent_events[:limit]

    async def _persist_safety_event(
        self,
        event_state: str,
        risk_level: str,
        description: str,
        fatigue_level: int = 0,
        vehicle_id: str = "vehicle-1",
        trip_id: str = "trip-active-1",
    ):
        """Asynchronously persist a SafetyEvent to the database without blocking the live stream."""
        try:
            from app.db.database import async_session
            from app.models.safety_event import SafetyEvent

            async with async_session() as session:
                event = SafetyEvent(
                    id=str(uuid.uuid4()),
                    trip_id=trip_id,
                    vehicle_id=vehicle_id,
                    event_type=f"{event_state}_EVENT",
                    risk_level=risk_level,
                    driver_status=event_state.capitalize(),
                    distraction_status="Normal",
                    description=description,
                    fatigue_level=fatigue_level,
                    timestamp=datetime.now(timezone.utc),
                )
                session.add(event)
                await session.commit()
                logger.info(
                    f"SafetyEvent persisted to DB: state={event_state} risk={risk_level} id={event.id}"
                )
        except Exception as e:
            # Non-fatal — log and proceed so live stream remains uninterrupted
            logger.debug(f"Could not persist safety event to database: {e}")

    async def process_ai_event(self, ai_event: dict) -> dict:
        """Process an AI detection event, track state transitions, and produce enriched telemetry."""
        new_state = ai_event.get("state", STATE_NORMAL)
        if new_state not in RISK_MAP:
            new_state = STATE_NORMAL

        risk_level = RISK_MAP.get(new_state, "LOW")
        alert_message = ALERT_MAP.get(new_state, "Driver Alert")

        state_changed = (new_state != self._current_state)

        if state_changed:
            self._previous_state = self._current_state
            self._current_state = new_state
            
            timestamp_iso = datetime.now(timezone.utc).isoformat()

            # Record transition in recent events log
            event_entry = {
                "id": str(uuid.uuid4())[:8],
                "timestamp": timestamp_iso,
                "state": new_state,
                "risk_level": risk_level,
                "description": alert_message,
            }
            # Insert at top (newest first)
            self._recent_events.insert(0, event_entry)
            if len(self._recent_events) > self._max_recent_events:
                self._recent_events.pop()

            logger.warning(
                f"State Transition: {self._previous_state} -> {self._current_state} (Risk: {risk_level})"
            )

            # Persist safety events on warning / high risk transitions
            if new_state in (STATE_DROWSY, STATE_MICROSLEEP):
                asyncio.create_task(
                    self._persist_safety_event(
                        event_state=new_state,
                        risk_level=risk_level,
                        description=alert_message,
                    )
                )

        # Build normalized and enriched telemetry payload for the driver dashboard
        return {
            "type": "drowsiness_update",
            "timestamp": ai_event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "state": self._current_state,
            "risk_level": risk_level,
            "alert_message": alert_message,
            "state_changed": state_changed,
            "ear": round(float(ai_event.get("ear", 0.0)), 3),
            "eye_closed": bool(ai_event.get("eye_closed", False)),
            "closed_duration": round(float(ai_event.get("closed_duration", 0.0)), 2),
            "perclos": round(float(ai_event.get("perclos", 0.0)), 1),
            "mar": round(float(ai_event.get("mar", 0.0)), 3),
            "yawning": bool(ai_event.get("yawning", False)),
            "recent_events": self.get_recent_events(limit=10),
        }

    def reset(self):
        """Reset state machine to NORMAL."""
        self._previous_state = self._current_state
        self._current_state = STATE_NORMAL


# Singleton instance
risk_engine = SafetyStateMachine()
