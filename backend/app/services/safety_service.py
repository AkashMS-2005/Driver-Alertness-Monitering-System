"""Safety service — records safety events and pushes updates."""

import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.safety_event import SafetyEvent
from app.websocket.connection_manager import manager

logger = logging.getLogger("smartdrive")


class SafetyService:
    """Processes AI detection results into safety events and dashboard updates."""

    @staticmethod
    async def record_safety_event(
        db: AsyncSession,
        trip_id: str,
        vehicle_id: str,
        event_type: str,
        risk_level: str,
        driver_status: str,
        distraction_status: str = "Normal",
        description: str | None = None,
        fatigue_level: int = 0,
        speed_kmh: float | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> SafetyEvent:
        """Record a safety event in the database."""
        event = SafetyEvent(
            trip_id=trip_id,
            vehicle_id=vehicle_id,
            event_type=event_type,
            risk_level=risk_level,
            driver_status=driver_status,
            distraction_status=distraction_status,
            description=description,
            fatigue_level=fatigue_level,
            speed_kmh=speed_kmh,
            latitude=latitude,
            longitude=longitude,
        )
        db.add(event)
        await db.flush()
        await db.refresh(event)
        logger.info(
            f"Safety event recorded: type={event_type} risk={risk_level} "
            f"driver={driver_status} vehicle={vehicle_id}"
        )
        return event

    @staticmethod
    async def push_safety_update_to_dashboards(
        vehicle_id: str,
        owner_id: str,
        driver_status: str,
        risk_level: str,
        safety_state: str,
        fatigue_level: int,
        distraction_status: str,
        alert_message: str | None = None,
        speed_kmh: float | None = None,
    ):
        """Push a SAFETY_STATUS_UPDATE to both driver and owner dashboards."""
        payload = {
            "event_type": "SAFETY_STATUS_UPDATE",
            "vehicle_id": vehicle_id,
            "driver_status": driver_status,
            "risk_level": risk_level,
            "safety_state": safety_state,
            "fatigue_level": fatigue_level,
            "distraction_status": distraction_status,
            "alert_message": alert_message,
            "speed_kmh": speed_kmh,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.send_to_vehicle(vehicle_id, payload)
        await manager.send_to_owner(owner_id, payload)
