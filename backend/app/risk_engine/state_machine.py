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

# Cached active vehicle/trip IDs resolved at startup from the database.
# Updated whenever a new dashboard event provides context.
_active_vehicle_id: str = "vehicle-1"
_active_trip_id: str = "trip-active-1"


def update_active_vehicle_trip(vehicle_id: str, trip_id: str):
    """Called by startup seed / dashboard poll to keep vehicle/trip IDs current."""
    global _active_vehicle_id, _active_trip_id
    _active_vehicle_id = vehicle_id
    _active_trip_id = trip_id

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

        # ---------------------------------------------------------------
        # Emergency Engine — process every frame for microsleep counting
        # and automatic emergency trigger logic.
        # ---------------------------------------------------------------
        drowsiness_pct = round(float(ai_event.get("perclos", 0.0)), 1)
        alertness_score = int(ai_event.get("alertness_score", 100))
        head_state = str(ai_event.get("head_state", "NORMAL"))
        asyncio.create_task(
            self._run_emergency_engine(new_state, drowsiness_pct, alertness_score, head_state)
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
            "alertness_score": alertness_score,
            "head_state": head_state,
            "alert_label": str(ai_event.get("alert_label", "NORMAL")),
            "fused_risk": round(float(ai_event.get("fused_risk", 0.0)), 3),
            "recent_events": self.get_recent_events(limit=10),
        }

    async def _resolve_vehicle_trip_ids(self) -> tuple[str, str]:
        """Dynamically resolve real DB vehicle and trip IDs if still using defaults."""
        global _active_vehicle_id, _active_trip_id
        if _active_vehicle_id != "vehicle-1" and _active_trip_id != "trip-active-1":
            return _active_vehicle_id, _active_trip_id
        try:
            from app.db.database import async_session
            from sqlalchemy import select
            from app.models.vehicle import Vehicle
            from app.models.trip import Trip

            async with async_session() as session:
                veh_res = await session.execute(select(Vehicle).limit(1))
                veh = veh_res.scalar_one_or_none()
                if veh:
                    _active_vehicle_id = veh.id
                    trip_res = await session.execute(
                        select(Trip).where(Trip.vehicle_id == veh.id, Trip.status == "ACTIVE").limit(1)
                    )
                    trip = trip_res.scalar_one_or_none()
                    if not trip:
                        trip_res = await session.execute(
                            select(Trip).where(Trip.vehicle_id == veh.id).order_by(Trip.created_at.desc()).limit(1)
                        )
                        trip = trip_res.scalar_one_or_none()
                    if trip:
                        _active_trip_id = trip.id
        except Exception as e:
            logger.debug(f"Could not auto-resolve vehicle/trip: {e}")
        return _active_vehicle_id, _active_trip_id

    async def _run_emergency_engine(
        self, state: str, drowsiness_pct: float,
        alertness_score: int = 100, head_state: str = "NORMAL"
    ):
        """Non-blocking delegation to the EmergencyEngine."""
        try:
            from app.risk_engine.emergency_engine import emergency_engine
            vid, tid = await self._resolve_vehicle_trip_ids()
            await emergency_engine.on_ai_event(
                state=state,
                drowsiness_percentage=drowsiness_pct,
                vehicle_id=vid,
                trip_id=tid,
                alertness_score=alertness_score,
                head_state=head_state,
            )
        except Exception as exc:
            # Non-fatal — log and proceed so live stream remains uninterrupted
            logger.debug(f"EmergencyEngine error (non-fatal): {exc}")

    def reset(self):
        """Reset state machine to NORMAL."""
        self._previous_state = self._current_state
        self._current_state = STATE_NORMAL


# Singleton instance
risk_engine = SafetyStateMachine()
