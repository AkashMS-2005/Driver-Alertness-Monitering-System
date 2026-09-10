"""Driver dashboard WebSocket endpoint — /ws/driver/{vehicle_id}

Driver never logs in. Connection is keyed by vehicle_id.
Receives real-time safety updates, alerts, and AI connection status.
"""

import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.websocket.connection_manager import manager

logger = logging.getLogger("smartdrive")
router = APIRouter()


@router.websocket("/ws/driver/{vehicle_id}")
async def driver_websocket(websocket: WebSocket, vehicle_id: str):
    """WebSocket endpoint for the driver-facing in-car dashboard.

    Pushes:
    - SAFETY_STATUS_UPDATE: real-time driver/risk status from the AI pipeline
    - ALERT_NEW: safety alerts
    - TRIP_UPDATE: trip lifecycle events
    - LOCATION_UPDATE: GPS position changes
    - AI_CONNECTION_STATUS_UPDATE: AI camera connection state
    - ASSISTANCE_UPDATE: highway assistance status
    - EMERGENCY_UPDATE: emergency events
    """
    await manager.connect_driver(vehicle_id, websocket)
    try:
        while True:
            # Driver dashboard is primarily receive-only, but we keep
            # the socket alive and handle any client messages (e.g. pings)
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                # Future: handle driver-initiated actions (SOS, etc.)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect_driver(vehicle_id, websocket)
        logger.info(f"Driver WebSocket disconnected: vehicle={vehicle_id}")
