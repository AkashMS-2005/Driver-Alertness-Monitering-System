"""Emergency event routes — recording and triggering emergency assistance.

Endpoints:
  POST /api/v1/emergency/trigger              — manual emergency trigger (frontend button)
  POST /api/v1/emergency/{id}/respond         — assistance response [NEW]
  POST /api/v1/emergency/{id}/cancel          — driver cancel after recovery [NEW]
  GET  /api/v1/emergency/active/{vehicle_id}  — get active emergency [NEW]
  GET  /api/v1/emergency/history/{vehicle_id} — full history [NEW]
  POST /api/v1/emergency/                     — low-level emergency event creation
  PUT  /api/v1/emergency/{id}/resolve         — resolve an emergency
  GET  /api/v1/emergency/vehicle/{id}         — list emergencies for a vehicle (legacy)
"""

import math
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.db.database import get_db
from app.models.emergency_event import EmergencyEvent
from app.models.highway_assistance import HighwayAssistance
from app.models.location import Location
from app.models.vehicle import Vehicle
from app.models.owner import Owner
from app.models.trip import Trip
from app.services.emergency_service import emergency_service

logger = logging.getLogger("smartdrive")
router = APIRouter()

# ---------------------------------------------------------------------------
# Static mock toll plaza database (real GPS coordinates of Indian NH toll plazas)
# NOTE: [DEV] This is static reference data. In production, replace with a live
# toll/highway assistance API (e.g., NHAI, HERE Maps, or Google Places API).
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
    """Calculate the great-circle distance between two points in kilometres."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_nearest_toll(lat: float, lon: float) -> dict:
    """Return the nearest toll plaza from the static database."""
    best = None
    best_dist = float("inf")
    for plaza in TOLL_PLAZAS:
        d = _haversine_km(lat, lon, plaza["lat"], plaza["lon"])
        if d < best_dist:
            best_dist = d
            best = plaza
    return {"toll": best, "distance_km": round(best_dist, 2)} if best else None


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class EmergencyCreate(BaseModel):
    trip_id: str
    vehicle_id: str
    emergency_type: str
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class EmergencyResponse(BaseModel):
    id: str
    trip_id: str
    vehicle_id: str
    emergency_type: str
    status: str
    trigger_source: str = "MANUAL"
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_name: str | None = None
    microsleep_count: int | None = None
    drowsiness_percentage: float | None = None
    detected_at: datetime
    triggered_at: datetime | None = None
    response_message: str | None = None
    responded_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancelled_reason: str | None = None
    resolved_at: datetime | None = None
    assistance_name: str | None = None
    assistance_distance_km: float | None = None
    model_config = {"from_attributes": True}


class EmergencyTriggerRequest(BaseModel):
    """Unified emergency trigger payload for the frontend button."""
    vehicle_id: str | None = None          # If None, uses the first registered vehicle
    reason: str = "DRIVER_UNRESPONSIVE"    # Free-text reason shown in notification
    driver_status: str = "UNKNOWN"         # NORMAL / DROWSY / MICROSLEEP
    drowsiness_level: float = 0.0          # PERCLOS % at time of emergency


class EmergencyTriggerResponse(BaseModel):
    """Full result returned to the frontend after emergency is triggered."""
    emergency_id: str
    vehicle_location: dict
    nearest_toll: dict | None
    owner_notified: bool
    owner_notification_method: str
    status: str
    message: str
    note: str
    triggered_at: str


class AssistanceRespondRequest(BaseModel):
    """Payload for assistance response endpoint."""
    message: str = (
        "Emergency request received. Highway assistance team is responding to the vehicle location. "
        "Please remain calm and stay safely inside the vehicle if possible."
    )


class CancelEmergencyRequest(BaseModel):
    """Payload for driver cancel endpoint."""
    reason: str = "Driver recovered and cancelled emergency."


class ActiveEmergencyResponse(BaseModel):
    """Active emergency payload for the owner dashboard."""
    emergency_id: str
    status: str
    vehicle_id: str
    trip_id: str
    microsleep_count: int
    drowsiness_percentage: float
    latitude: float | None
    longitude: float | None
    place_name: str | None
    gps_source: str
    assistance_name: str | None
    assistance_distance_km: float | None
    triggered_at: str | None
    response_message: str | None
    responded_at: str | None
    cancelled_at: str | None
    cancelled_reason: str | None


# ---------------------------------------------------------------------------
# NEW Endpoints
# ---------------------------------------------------------------------------

@router.get("/active/{vehicle_id}")
async def get_active_emergency(
    vehicle_id: str, db: AsyncSession = Depends(get_db)
):
    """Return the currently active emergency for a vehicle, or null."""
    payload = await emergency_service.build_active_emergency_payload(vehicle_id, db)
    if not payload:
        return {"active": False, "emergency": None}
    return {"active": True, "emergency": payload}


@router.get("/history")
@router.get("/history/all")
async def get_all_emergency_history(
    limit: int = 100, db: AsyncSession = Depends(get_db)
):
    """Return emergency history for ALL vehicles, newest first.

    Used by the owner dashboard Emergency History section.
    Response is enriched with assistance_name and assistance_distance_km
    from the linked HighwayAssistance record.
    """
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(EmergencyEvent)
        .order_by(EmergencyEvent.detected_at.desc())
        .limit(limit)
    )
    events = list(result.scalars().all())

    # Enrich each event with HighwayAssistance data
    enriched = []
    for ev in events:
        ev_dict = {
            "id": ev.id,
            "emergency_id": ev.id,
            "trip_id": ev.trip_id,
            "vehicle_id": ev.vehicle_id,
            "emergency_type": ev.emergency_type,
            "status": ev.status,
            "trigger_source": getattr(ev, "trigger_source", "UNKNOWN"),
            "description": ev.description,
            "latitude": ev.latitude,
            "longitude": ev.longitude,
            "place_name": ev.place_name,
            "microsleep_count": ev.microsleep_count if ev.microsleep_count is not None else 0,
            "drowsiness_percentage": ev.drowsiness_percentage,
            "detected_at": ev.detected_at.isoformat() if ev.detected_at else None,
            "triggered_at": ev.triggered_at.isoformat() if ev.triggered_at else None,
            "response_message": ev.response_message,
            "responded_at": ev.responded_at.isoformat() if ev.responded_at else None,
            "cancelled_at": ev.cancelled_at.isoformat() if ev.cancelled_at else None,
            "cancelled_reason": ev.cancelled_reason,
            "resolved_at": ev.resolved_at.isoformat() if ev.resolved_at else None,
            "assistance_name": None,
            "assistance_distance_km": None,
        }
        # Fetch linked HighwayAssistance
        try:
            assist_res = await db.execute(
                sa_select(HighwayAssistance)
                .where(HighwayAssistance.emergency_id == ev.id)
                .limit(1)
            )
            assist = assist_res.scalar_one_or_none()
            if assist:
                ev_dict["assistance_name"] = assist.assistance_name
                ev_dict["assistance_distance_km"] = assist.distance_km
        except Exception:
            pass
        enriched.append(ev_dict)

    return enriched


@router.get("/history/{vehicle_id}", response_model=list[EmergencyResponse])
async def get_emergency_history(
    vehicle_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)
):
    """Return emergency history for a vehicle, newest first."""
    events = await emergency_service.get_emergency_history(vehicle_id, db, limit=limit)
    return events


@router.post("/{emergency_id}/respond")
async def respond_to_emergency(
    emergency_id: str,
    payload: AssistanceRespondRequest,
    db: AsyncSession = Depends(get_db),
):
    """[DEV] Simulate highway assistance response.

    In production this would be called by the toll operator's application.
    This endpoint validates the emergency, records the response, and
    broadcasts ASSISTANCE_RESPONSE to all connected owner dashboards.
    """
    try:
        msg = payload.message or (
            "Emergency request received. Highway assistance team is responding to the vehicle location. "
            "Please remain calm and stay safely inside the vehicle if possible."
        )
        emergency = await emergency_service.respond_to_emergency(
            emergency_id=emergency_id,
            message=msg,
            db=db,
        )
        await db.commit()
        return {
            "success": True,
            "emergency_id": emergency.id,
            "status": emergency.status,
            "message": msg,
            "responded_at": emergency.responded_at.isoformat() if emergency.responded_at else None,
            "note": "[DEV] This is a development/mock response endpoint. No real toll operator was contacted.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error responding to emergency {emergency_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{emergency_id}/cancel")
async def cancel_emergency(
    emergency_id: str,
    payload: CancelEmergencyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Cancel an emergency after driver recovery confirmation.

    Only allowed when:
    - Emergency status is DRIVER_RECOVERED
    - Assistance has NOT yet responded
    """
    try:
        emergency = await emergency_service.cancel_emergency(
            emergency_id=emergency_id,
            reason=payload.reason,
            db=db,
        )
        return {
            "success": True,
            "emergency_id": emergency.id,
            "status": emergency.status,
            "cancelled_at": emergency.cancelled_at.isoformat() if emergency.cancelled_at else None,
            "reason": emergency.cancelled_reason,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error cancelling emergency {emergency_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Existing Endpoints (unchanged)
# ---------------------------------------------------------------------------

@router.post("/trigger", response_model=EmergencyTriggerResponse, status_code=201)
async def trigger_emergency(
    payload: EmergencyTriggerRequest, db: AsyncSession = Depends(get_db)
):
    """Unified emergency trigger — called when the frontend 🚨 EMERGENCY button is pressed.

    Trigger source: MANUAL (distinguishes from AUTO_DROWSINESS triggers).

    Workflow:
      1. Resolve the vehicle (use payload.vehicle_id or first registered)
      2. Get latest GPS location from DB
      3. Find nearest toll plaza (Haversine distance, static database)
      4. Create EmergencyEvent record (trigger_source=MANUAL)
      5. Create HighwayAssistance record
      6. Notify owner via WebSocket (and log for future SMS/email integration)
      7. Return result to frontend

    NOTE: [DEV] SMS and Email notifications require external provider configuration.
    See NOTIFICATION_SERVICE_NOTE below for setup instructions.
    """
    # 1. Resolve vehicle
    if payload.vehicle_id:
        veh_res = await db.execute(select(Vehicle).where(Vehicle.id == payload.vehicle_id))
        vehicle = veh_res.scalar_one_or_none()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")
    else:
        veh_res = await db.execute(select(Vehicle).limit(1))
        vehicle = veh_res.scalar_one_or_none()
        if not vehicle:
            raise HTTPException(status_code=404, detail="No vehicle registered in the system")

    # Get owner
    owner_res = await db.execute(select(Owner).where(Owner.id == vehicle.owner_id))
    owner = owner_res.scalar_one_or_none()

    # 2. Latest GPS location
    loc_res = await db.execute(
        select(Location)
        .where(Location.vehicle_id == vehicle.id)
        .order_by(Location.timestamp.desc())
        .limit(1)
    )
    latest_loc = loc_res.scalar_one_or_none()

    # Use DB location or default Bengaluru placeholder
    if latest_loc:
        veh_lat = latest_loc.latitude
        veh_lon = latest_loc.longitude
        gps_label = "GPS"
    else:
        # Default placeholder — Bengaluru city center
        veh_lat = 12.9716
        veh_lon = 77.5946
        gps_label = "PLACEHOLDER — GPS not connected"

    # 3. Find nearest toll plaza
    toll_result = _find_nearest_toll(veh_lat, veh_lon)

    # 4. Get or find active trip
    trip_res = await db.execute(
        select(Trip)
        .where(Trip.vehicle_id == vehicle.id, Trip.status == "ACTIVE")
        .limit(1)
    )
    active_trip = trip_res.scalar_one_or_none()

    if not active_trip:
        # Create a minimal trip record for the emergency event
        active_trip = Trip(
            vehicle_id=vehicle.id,
            status="EMERGENCY_STOPPED",
            start_latitude=veh_lat,
            start_longitude=veh_lon,
        )
        db.add(active_trip)
        await db.flush()
        await db.refresh(active_trip)

    # 5. Create EmergencyEvent (trigger_source=MANUAL)
    description = (
        f"Emergency triggered by dashboard. Reason: {payload.reason}. "
        f"Driver status: {payload.driver_status}. "
        f"Drowsiness level: {payload.drowsiness_level:.1f}%. "
        f"Location: {veh_lat:.4f}, {veh_lon:.4f} ({gps_label})."
    )
    now = datetime.now(timezone.utc)
    emergency = EmergencyEvent(
        trip_id=active_trip.id,
        vehicle_id=vehicle.id,
        owner_id=vehicle.owner_id,
        emergency_type="DRIVER_EMERGENCY",
        status="ACTIVE",
        trigger_source="MANUAL",
        description=description,
        latitude=veh_lat,
        longitude=veh_lon,
        drowsiness_percentage=payload.drowsiness_level,
        detected_at=now,
        triggered_at=now,
    )
    db.add(emergency)
    await db.flush()
    await db.refresh(emergency)

    # 6. Create HighwayAssistance record
    toll_name = toll_result["toll"]["name"] if toll_result else "Unknown"
    toll_dist = toll_result["distance_km"] if toll_result else 0.0
    full_toll_name = (
        f"{toll_result['toll']['name']} ({toll_result['toll']['highway']})"
        if toll_result else "Demo Highway Assistance"
    )

    assistance_desc = (
        f"Emergency assistance requested. "
        f"Nearest toll: {toll_name} ({toll_dist:.1f} km away)."
    )
    assistance = HighwayAssistance(
        trip_id=active_trip.id,
        vehicle_id=vehicle.id,
        emergency_id=emergency.id,
        assistance_type="EMERGENCY_ASSISTANCE",
        assistance_name=full_toll_name,
        status="REQUESTED",
        description=assistance_desc,
        latitude=veh_lat,
        longitude=veh_lon,
        distance_km=toll_dist,
    )
    db.add(assistance)
    await db.flush()

    # 7. Notify owner via WebSocket + log
    owner_notified = False
    notification_method = "WEBSOCKET"
    try:
        from app.websocket.connection_manager import manager

        notification_payload = {
            "type": "EMERGENCY_TRIGGERED",
            "event_type": "EMERGENCY_ALERT",  # legacy compat
            "emergency_id": emergency.id,
            "status": "ACTIVE",
            "vehicle_id": vehicle.id,
            "trip_id": active_trip.id,
            "vehicle": f"{vehicle.make} {vehicle.model} ({vehicle.plate_number})",
            "location": {"latitude": veh_lat, "longitude": veh_lon, "source": gps_label},
            "latitude": veh_lat,
            "longitude": veh_lon,
            "gps_source": gps_label,
            "driver_status": payload.driver_status,
            "drowsiness_percentage": payload.drowsiness_level,
            "microsleep_count": 0,  # manual trigger — no microsleep count
            "assistance_name": full_toll_name,
            "assistance_distance_km": toll_dist,
            "nearest_toll": toll_result["toll"] if toll_result else None,
            "distance_to_toll_km": toll_dist,
            "reason": payload.reason,
            "trigger_source": "MANUAL",
            "triggered_at": now.isoformat(),
            "timestamp": now.isoformat(),
        }
        # Broadcast to all connected dashboards
        await manager.broadcast_to_all(notification_payload)
        owner_notified = True

        logger.warning(
            f"MANUAL EMERGENCY TRIGGERED — Vehicle: {vehicle.plate_number} | "
            f"Location: {veh_lat:.4f},{veh_lon:.4f} | "
            f"Nearest toll: {toll_name} ({toll_dist:.1f}km) | "
            f"Driver: {payload.driver_status} | "
            f"Owner: {owner.name if owner else 'N/A'} ({owner.email if owner else 'N/A'}) | "
            f"[DEV] SMS not configured — WebSocket notification sent."
        )

    except Exception as exc:
        logger.error(f"Failed to send owner notification: {exc}")

    # NOTE: NOTIFICATION_SERVICE_NOTE
    # To enable SMS notifications, configure the following in backend/.env:
    #   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    #   TWILIO_AUTH_TOKEN=your_auth_token
    #   TWILIO_FROM_NUMBER=+1xxxxxxxxxx
    # Then call: await sms_service.send_emergency_sms(owner.phone, notification_text)
    # The abstraction is in app/services/notification_service.py

    return EmergencyTriggerResponse(
        emergency_id=emergency.id,
        vehicle_location={
            "latitude": veh_lat,
            "longitude": veh_lon,
            "source": gps_label,
        },
        nearest_toll={
            "name": toll_result["toll"]["name"] if toll_result else None,
            "highway": toll_result["toll"]["highway"] if toll_result else None,
            "latitude": toll_result["toll"]["lat"] if toll_result else None,
            "longitude": toll_result["toll"]["lon"] if toll_result else None,
            "distance_km": toll_dist,
        } if toll_result else None,
        owner_notified=owner_notified,
        owner_notification_method=notification_method,
        status="ACTIVE",
        message=(
            f"Emergency registered. Nearest assistance: {toll_name} ({toll_dist:.1f} km). "
            f"Owner notified via WebSocket."
        ),
        note=(
            "[DEV] Toll gate data is static reference data (real GPS coordinates of Indian NH "
            "toll plazas). No external agency has been contacted. "
            "SMS notifications require Twilio credentials in backend/.env."
        ),
        triggered_at=emergency.detected_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Low-level CRUD endpoints (kept for API completeness)
# ---------------------------------------------------------------------------

@router.post("/", response_model=EmergencyResponse, status_code=status.HTTP_201_CREATED)
async def create_emergency(
    payload: EmergencyCreate, db: AsyncSession = Depends(get_db)
):
    """Record a new emergency event (low-level — prefer /trigger for dashboard use)."""
    event = EmergencyEvent(
        trip_id=payload.trip_id,
        vehicle_id=payload.vehicle_id,
        emergency_type=payload.emergency_type,
        description=payload.description,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


@router.put("/{emergency_id}/resolve")
async def resolve_emergency(
    emergency_id: str, new_status: str = "RESOLVED", db: AsyncSession = Depends(get_db)
):
    """Resolve an emergency event."""
    result = await db.execute(
        select(EmergencyEvent).where(EmergencyEvent.id == emergency_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Emergency event not found")

    event.status = new_status
    event.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "resolved", "new_status": new_status}


@router.get("/vehicle/{vehicle_id}", response_model=list[EmergencyResponse])
async def list_emergencies_for_vehicle(
    vehicle_id: str, db: AsyncSession = Depends(get_db)
):
    """List emergency events for a vehicle (legacy endpoint — use /history/{vehicle_id} instead)."""
    result = await db.execute(
        select(EmergencyEvent)
        .where(EmergencyEvent.vehicle_id == vehicle_id)
        .order_by(EmergencyEvent.detected_at.desc())
    )
    return result.scalars().all()
