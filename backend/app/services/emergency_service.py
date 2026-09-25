"""Emergency Service — DB persistence and WebSocket broadcast for all emergency events.

This service handles ALL database writes for the emergency escalation system.
The EmergencyEngine (risk_engine/emergency_engine.py) calls this service for
all persistent operations.

Broadcast event types:
  EMERGENCY_TRIGGERED      — new auto emergency created
  EMERGENCY_UPDATED        — generic status update
  ASSISTANCE_RESPONSE      — toll/highway responded
  DRIVER_RECOVERED         — driver confirmed NORMAL for 10s
  EMERGENCY_CANCELLED      — driver cancelled after recovery
  EMERGENCY_RESOLVED       — fully resolved
"""

import asyncio
import math
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.emergency_event import EmergencyEvent
from app.models.highway_assistance import HighwayAssistance
from app.models.emergency_sms_log import EmergencySmsLog
from app.models.location import Location
from app.models.vehicle import Vehicle
from app.models.owner import Owner
from app.models.trip import Trip

logger = logging.getLogger("smartdrive.emergency_service")

# ---------------------------------------------------------------------------
# Static mock toll plaza database (real GPS coordinates of Indian NH toll plazas)
# NOTE: [DEV] In production, replace with live NHAI / HERE Maps / Google Places API.
# ---------------------------------------------------------------------------
TOLL_PLAZAS = [
    {"name": "Tumkur Toll Plaza",      "lat": 13.3409, "lon": 77.1019, "highway": "NH-48"},
    {"name": "Nelamangala Toll Plaza",  "lat": 13.0966, "lon": 77.3922, "highway": "NH-48"},
    {"name": "Nidaghatta Toll Plaza",   "lat": 12.8520, "lon": 76.6200, "highway": "NH-275"},
    {"name": "Mandya Toll Plaza",       "lat": 12.5218, "lon": 76.8951, "highway": "NH-275"},
    {"name": "Kengeri Toll Plaza",      "lat": 12.9037, "lon": 77.4863, "highway": "NICE Road"},
    {"name": "Hoskote Toll Plaza",      "lat": 13.0679, "lon": 77.7983, "highway": "NH-75"},
    {"name": "Bommasandra Toll Plaza",  "lat": 12.8130, "lon": 77.6940, "highway": "NICE Road"},
    {"name": "Ramanagara Toll Plaza",   "lat": 12.7177, "lon": 77.2857, "highway": "NH-275"},
    {"name": "Channapatna Toll Plaza",  "lat": 12.6518, "lon": 77.2057, "highway": "NH-275"},
    {"name": "Bidadi Toll Plaza",       "lat": 12.7986, "lon": 77.3827, "highway": "NH-275"},
    {"name": "Yelahanka Toll Plaza",    "lat": 13.1047, "lon": 77.5963, "highway": "NH-44"},
    {"name": "Devanahalli Toll Plaza",  "lat": 13.2329, "lon": 77.7148, "highway": "NH-44"},
    {"name": "Attibele Toll Plaza",     "lat": 12.7699, "lon": 77.7756, "highway": "NH-44"},
    {"name": "Electronic City Toll",    "lat": 12.8456, "lon": 77.6598, "highway": "Hosur Road"},
    {"name": "Mysuru Road Toll Plaza",  "lat": 12.9305, "lon": 77.4568, "highway": "NH-275"},
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_nearest_toll(lat: float, lon: float) -> Optional[dict]:
    best, best_dist = None, float("inf")
    for plaza in TOLL_PLAZAS:
        d = _haversine_km(lat, lon, plaza["lat"], plaza["lon"])
        if d < best_dist:
            best_dist, best = d, plaza
    return {"toll": best, "distance_km": round(best_dist, 2)} if best else None


class _EmergencyService:
    """All database operations for the emergency escalation system."""

    # ----------------------------------------------------------------
    # Query helpers
    # ----------------------------------------------------------------

    async def get_active_emergency(
        self, vehicle_id: str, db: AsyncSession, trip_id: Optional[str] = None
    ) -> Optional[EmergencyEvent]:
        """Return the active EmergencyEvent for a vehicle and trip, or None."""
        query = (
            select(EmergencyEvent)
            .where(EmergencyEvent.status.in_(["ACTIVE", "DRIVER_RECOVERED"]))
        )
        if vehicle_id and vehicle_id != "vehicle-1":
            query = query.where(EmergencyEvent.vehicle_id == vehicle_id)
        if trip_id and trip_id != "trip-active-1":
            query = query.where(EmergencyEvent.trip_id == trip_id)
        result = await db.execute(
            query.order_by(EmergencyEvent.detected_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def revert_to_active(
        self, emergency_id: str, db: AsyncSession
    ) -> Optional[EmergencyEvent]:
        """Revert a DRIVER_RECOVERED emergency back to ACTIVE."""
        result = await db.execute(
            select(EmergencyEvent).where(EmergencyEvent.id == emergency_id)
        )
        emergency = result.scalar_one_or_none()
        if emergency and emergency.status == "DRIVER_RECOVERED":
            emergency.status = "ACTIVE"
            await db.flush()
        return emergency

    async def _get_vehicle_location(
        self, vehicle_id: str, db: AsyncSession
    ) -> tuple[float, float, bool]:
        """Return (lat, lon, gps_available) for vehicle. Falls back to Bengaluru center."""
        loc_res = await db.execute(
            select(Location)
            .where(Location.vehicle_id == vehicle_id)
            .order_by(Location.timestamp.desc())
            .limit(1)
        )
        loc = loc_res.scalar_one_or_none()
        if loc:
            return loc.latitude, loc.longitude, True
        # Fallback — GPS not connected
        return 12.9716, 77.5946, False

    async def _get_active_trip(self, vehicle_id: str, db: AsyncSession) -> Optional[Trip]:
        res = await db.execute(
            select(Trip)
            .where(Trip.vehicle_id == vehicle_id, Trip.status == "ACTIVE")
            .limit(1)
        )
        return res.scalar_one_or_none()

    # ----------------------------------------------------------------
    # Create automatic emergency
    # ----------------------------------------------------------------

    async def create_auto_emergency(
        self,
        vehicle_id: str,
        trip_id: str,
        microsleep_count: int,
        drowsiness_percentage: float,
        db: AsyncSession,
    ) -> EmergencyEvent:
        """Create EmergencyEvent + HighwayAssistance and broadcast to owner & driver dashboards."""

        # Resolve vehicle + owner (fallback to first vehicle if ID invalid)
        veh_res = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
        vehicle = veh_res.scalar_one_or_none()
        if not vehicle:
            veh_res = await db.execute(select(Vehicle).limit(1))
            vehicle = veh_res.scalar_one_or_none()
            if vehicle:
                vehicle_id = vehicle.id
        owner_id = vehicle.owner_id if vehicle else None

        # Resolve trip (fallback to active/latest trip for this vehicle)
        trip_res = await db.execute(select(Trip).where(Trip.id == trip_id))
        trip = trip_res.scalar_one_or_none()
        if not trip:
            trip = await self._get_active_trip(vehicle_id, db)
            if not trip:
                trip_res = await db.execute(
                    select(Trip)
                    .where(Trip.vehicle_id == vehicle_id)
                    .order_by(Trip.created_at.desc())
                    .limit(1)
                )
                trip = trip_res.scalar_one_or_none()
            if trip:
                trip_id = trip.id

        # Get location
        lat, lon, gps_available = await self._get_vehicle_location(vehicle_id, db)
        gps_label = "GPS" if gps_available else "PLACEHOLDER — GPS not connected"

        # Find nearest toll
        toll_result = _find_nearest_toll(lat, lon)
        toll_name = (
            f"{toll_result['toll']['name']} ({toll_result['toll']['highway']})"
            if toll_result else "Demo Highway Assistance"
        )
        toll_dist = toll_result["distance_km"] if toll_result else 0.0

        now = datetime.now(timezone.utc)
        default_place = "Ashokanagar, Bengaluru" if not gps_available else f"{lat:.4f}, {lon:.4f}"

        # Create EmergencyEvent
        emergency = EmergencyEvent(
            trip_id=trip_id,
            vehicle_id=vehicle_id,
            owner_id=owner_id,
            emergency_type="AUTO_DROWSINESS",
            status="ACTIVE",
            trigger_source="AUTO_DROWSINESS",
            description=(
                f"Automatic emergency triggered: {microsleep_count} microsleep events, "
                f"drowsiness {drowsiness_percentage:.1f}%. Location: {lat:.4f}, {lon:.4f} ({gps_label})."
            ),
            latitude=lat,
            longitude=lon,
            place_name=default_place,
            microsleep_count=microsleep_count,
            drowsiness_percentage=round(drowsiness_percentage, 1),
            detected_at=now,
            triggered_at=now,
        )
        db.add(emergency)
        await db.flush()
        await db.refresh(emergency)

        # Create HighwayAssistance record
        assistance = HighwayAssistance(
            trip_id=trip_id,
            vehicle_id=vehicle_id,
            emergency_id=emergency.id,
            assistance_type="EMERGENCY_ASSISTANCE",
            assistance_name=toll_name,
            status="REQUESTED",
            description=(
                f"[DEV] Demo assistance. Nearest: {toll_name} ({toll_dist:.1f} km). "
                "No real toll authority has been contacted."
            ),
            latitude=lat,
            longitude=lon,
            distance_km=toll_dist,
        )
        db.add(assistance)
        await db.flush()

        # Broadcast EMERGENCY_TRIGGERED to ALL connected clients (owners + drivers)
        try:
            from app.websocket.connection_manager import manager
            await manager.broadcast_to_all({
                "type": "EMERGENCY_TRIGGERED",
                "emergency_id": emergency.id,
                "status": "ACTIVE",
                "vehicle_id": vehicle_id,
                "trip_id": trip_id,
                "microsleep_count": microsleep_count,
                "drowsiness_percentage": round(drowsiness_percentage, 1),
                "latitude": lat,
                "longitude": lon,
                "place_name": default_place,
                "gps_source": gps_label,
                "assistance_name": toll_name,
                "assistance_distance_km": toll_dist,
                "triggered_at": now.isoformat(),
            })
        except Exception as exc:
            logger.error(f"Failed to broadcast EMERGENCY_TRIGGERED: {exc}")

        # Automatically dispatch emergency SMS alert to configured highway assistance
        try:
            from app.services.sms_service import sms_service
            asyncio.create_task(sms_service.send_emergency_alert(emergency.id))
        except Exception as sms_exc:
            logger.error(f"[SMS] Failed to schedule emergency SMS dispatch: {sms_exc}")

        logger.warning(
            f"AUTO EMERGENCY TRIGGERED — id={emergency.id} "
            f"vehicle={vehicle_id} microsleeps={microsleep_count} "
            f"drowsiness={drowsiness_percentage:.1f}% "
            f"nearest_toll={toll_name} ({toll_dist:.1f}km)"
        )
        return emergency

    # ----------------------------------------------------------------
    # Mark driver recovered
    # ----------------------------------------------------------------

    async def mark_driver_recovered(
        self, emergency_id: str, drowsiness_percentage: float, db: AsyncSession
    ):
        """Transition ACTIVE emergency to DRIVER_RECOVERED."""
        result = await db.execute(
            select(EmergencyEvent).where(EmergencyEvent.id == emergency_id)
        )
        emergency = result.scalar_one_or_none()
        if not emergency or emergency.status != "ACTIVE":
            return

        emergency.status = "DRIVER_RECOVERED"
        await db.flush()

        # Broadcast
        try:
            from app.websocket.connection_manager import manager
            await manager.broadcast_to_all({
                "type": "DRIVER_RECOVERED",
                "emergency_id": emergency_id,
                "status": "DRIVER_RECOVERED",
                "drowsiness_percentage": round(drowsiness_percentage, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.error(f"Failed to broadcast DRIVER_RECOVERED: {exc}")

        logger.info(f"DRIVER RECOVERED — emergency={emergency_id} drowsiness={drowsiness_percentage:.1f}%")

    # ----------------------------------------------------------------
    # Assistance response
    # ----------------------------------------------------------------

    async def respond_to_emergency(
        self,
        emergency_id: str,
        message: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        action: str = "ACCEPT",
        response_source: str = "MANUAL",
    ) -> EmergencyEvent:
        """Record assistance response (manual or automated) and transition to ASSISTANCE_RESPONDED."""
        result = await db.execute(
            select(EmergencyEvent).where(EmergencyEvent.id == emergency_id)
        )
        emergency = result.scalar_one_or_none()
        if not emergency:
            raise ValueError(f"Emergency {emergency_id} not found")
        if emergency.status not in ("ACTIVE", "DRIVER_RECOVERED"):
            raise ValueError(
                f"Cannot respond to emergency in status '{emergency.status}'. "
                "Only ACTIVE or DRIVER_RECOVERED emergencies can receive responses."
            )

        now = datetime.now(timezone.utc)
        action_norm = "REJECTED" if action.upper().startswith("REJECT") else "ACCEPTED"
        short_id = emergency.id.replace("-", "")[-8:].upper()

        if action_norm == "ACCEPTED":
            default_expl = message or "Highway assistance team has accepted the request."
            default_raw = f"ACCEPT {short_id}"
        else:
            default_expl = message or "Highway assistance rejected the request."
            default_raw = f"REJECT {short_id}"

        response_msg = message or default_raw

        emergency.status = "ASSISTANCE_RESPONDED"
        emergency.assistance_response_status = action_norm
        emergency.response_source = response_source
        emergency.response_message = response_msg
        emergency.responded_at = now
        await db.flush()

        # Update HighwayAssistance table record if exists
        try:
            assist_res = await db.execute(
                select(HighwayAssistance)
                .where(HighwayAssistance.emergency_id == emergency.id)
                .limit(1)
            )
            assist = assist_res.scalar_one_or_none()
            if assist:
                assist.status = action_norm
                assist.resolved_at = now
        except Exception as e:
            logger.error(f"Could not update HighwayAssistance for {emergency.id}: {e}")

        # Update EmergencySmsLog if exists
        try:
            sms_res = await db.execute(
                select(EmergencySmsLog)
                .where(EmergencySmsLog.emergency_id == emergency.id)
                .order_by(EmergencySmsLog.sent_at.desc())
                .limit(1)
            )
            sms_log = sms_res.scalar_one_or_none()
            if sms_log:
                sms_log.assistance_response_status = action_norm
                sms_log.assistance_response_message = response_msg
                sms_log.assistance_responded_at = now
        except Exception as e:
            logger.debug(f"Could not sync EmergencySmsLog for {emergency.id}: {e}")

        # Update in-memory engine state
        try:
            from app.risk_engine.emergency_engine import emergency_engine
            emergency_engine.on_emergency_responded(emergency_id)
        except Exception as eng_err:
            logger.debug(f"Emergency engine sync: {eng_err}")

        # Broadcast ASSISTANCE_RESPONSE to ALL connected dashboards (owner AND driver)
        try:
            from app.websocket.connection_manager import manager
            await manager.broadcast_to_all({
                "type": "ASSISTANCE_RESPONSE",
                "emergency_id": emergency_id,
                "status": "ASSISTANCE_RESPONDED",
                "response_status": action_norm,
                "response_source": response_source,
                "message": default_expl,
                "response_message": response_msg,
                "raw_response": response_msg,
                "responded_at": now.isoformat(),
            })
        except Exception as exc:
            logger.error(f"Failed to broadcast ASSISTANCE_RESPONSE: {exc}")

        logger.info(f"ASSISTANCE RESPONSE RECORDED ({response_source}) — emergency={emergency_id} action={action_norm}")
        return emergency

    async def _auto_resolve(self, emergency: EmergencyEvent, db: AsyncSession):
        """Automatically resolve after assistance responds."""
        now = datetime.now(timezone.utc)
        emergency.status = "RESOLVED"
        emergency.resolved_at = now
        await db.flush()

        from app.risk_engine.emergency_engine import emergency_engine
        emergency_engine.on_emergency_resolved(emergency.id)

        try:
            from app.websocket.connection_manager import manager
            await manager.broadcast_to_all_owners({
                "type": "EMERGENCY_RESOLVED",
                "emergency_id": emergency.id,
                "status": "RESOLVED",
                "timestamp": now.isoformat(),
            })
        except Exception as exc:
            logger.error(f"Failed to broadcast EMERGENCY_RESOLVED: {exc}")

        logger.info(f"EMERGENCY RESOLVED — id={emergency.id}")

    # ----------------------------------------------------------------
    # Cancel emergency
    # ----------------------------------------------------------------

    async def cancel_emergency(
        self, emergency_id: str, reason: str, db: AsyncSession
    ) -> EmergencyEvent:
        """Driver cancels the emergency after recovery confirmation."""
        result = await db.execute(
            select(EmergencyEvent).where(EmergencyEvent.id == emergency_id)
        )
        emergency = result.scalar_one_or_none()
        if not emergency:
            raise ValueError(f"Emergency {emergency_id} not found")
        if emergency.status == "ASSISTANCE_RESPONDED":
            raise ValueError(
                "Emergency cannot be cancelled because assistance has already responded."
            )
        if emergency.status not in ("ACTIVE", "DRIVER_RECOVERED"):
            raise ValueError(
                f"Emergency in status '{emergency.status}' cannot be cancelled."
            )
        if emergency.status != "DRIVER_RECOVERED":
            raise ValueError(
                "Emergency can only be cancelled after driver recovery is confirmed."
            )

        now = datetime.now(timezone.utc)
        emergency.status = "CANCELLED"
        emergency.cancelled_at = now
        emergency.cancelled_reason = reason
        await db.flush()

        # Update in-memory engine
        from app.risk_engine.emergency_engine import emergency_engine
        emergency_engine.on_emergency_cancelled(emergency_id)

        # Broadcast EMERGENCY_CANCELLED
        try:
            from app.websocket.connection_manager import manager
            await manager.broadcast_to_all_owners({
                "type": "EMERGENCY_CANCELLED",
                "emergency_id": emergency_id,
                "status": "CANCELLED",
                "reason": reason,
                "cancelled_at": now.isoformat(),
            })
        except Exception as exc:
            logger.error(f"Failed to broadcast EMERGENCY_CANCELLED: {exc}")

        logger.info(f"EMERGENCY CANCELLED — id={emergency_id} reason='{reason}'")
        return emergency

    # ----------------------------------------------------------------
    # Get emergency history
    # ----------------------------------------------------------------

    async def get_emergency_history(
        self, vehicle_id: str, db: AsyncSession, limit: int = 50
    ) -> list[EmergencyEvent]:
        """Return emergency history for a vehicle, newest first."""
        result = await db.execute(
            select(EmergencyEvent)
            .where(EmergencyEvent.vehicle_id == vehicle_id)
            .order_by(EmergencyEvent.detected_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ----------------------------------------------------------------
    # Build active emergency payload (for WebSocket initial state)
    # ----------------------------------------------------------------

    async def build_active_emergency_payload(
        self, vehicle_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """Return the active emergency as a dict suitable for WebSocket broadcast."""
        emergency = await self.get_active_emergency(vehicle_id, db)
        if not emergency:
            return None

        # Get assistance record
        assist_res = await db.execute(
            select(HighwayAssistance)
            .where(HighwayAssistance.emergency_id == emergency.id)
            .limit(1)
        )
        assist = assist_res.scalar_one_or_none()

        # Get latest SMS log if exists
        sms_res = await db.execute(
            select(EmergencySmsLog)
            .where(EmergencySmsLog.emergency_id == emergency.id)
            .order_by(EmergencySmsLog.sent_at.desc())
            .limit(1)
        )
        sms_log = sms_res.scalar_one_or_none()

        return {
            "type": "EMERGENCY_TRIGGERED",
            "emergency_id": emergency.id,
            "status": emergency.status,
            "vehicle_id": vehicle_id,
            "trip_id": emergency.trip_id,
            "microsleep_count": emergency.microsleep_count or 0,
            "drowsiness_percentage": emergency.drowsiness_percentage or 0.0,
            "latitude": emergency.latitude,
            "longitude": emergency.longitude,
            "place_name": emergency.place_name,
            "gps_source": "GPS" if emergency.latitude else "UNAVAILABLE",
            "assistance_name": assist.assistance_name if assist else None,
            "assistance_distance_km": assist.distance_km if assist else None,
            "triggered_at": emergency.triggered_at.isoformat() if emergency.triggered_at else None,
            "response_source": getattr(emergency, "response_source", None) or ("SMS" if (sms_log and sms_log.assistance_responded_at) else None),
            "response_message": (sms_log.assistance_response_message if sms_log and sms_log.assistance_response_message else None) or emergency.response_message,
            "raw_response": (sms_log.assistance_response_message if sms_log and sms_log.assistance_response_message else None) or emergency.response_message,
            "responded_at": (sms_log.assistance_responded_at.isoformat() if sms_log and sms_log.assistance_responded_at else None) or (emergency.responded_at.isoformat() if emergency.responded_at else None),
            "cancelled_at": emergency.cancelled_at.isoformat() if emergency.cancelled_at else None,
            "cancelled_reason": emergency.cancelled_reason,
            "sms_status": sms_log.sms_status if sms_log else None,
            "sms_sent_at": sms_log.sent_at.isoformat() if (sms_log and sms_log.sent_at) else None,
            "assistance_response_status": getattr(emergency, "assistance_response_status", None) or (sms_log.assistance_response_status if sms_log else None),
            "assistance_phone_number": sms_log.assistance_phone_number if sms_log else None,
        }


# Singleton
emergency_service = _EmergencyService()
