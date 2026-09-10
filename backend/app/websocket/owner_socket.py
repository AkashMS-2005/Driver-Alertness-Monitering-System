"""Owner dashboard WebSocket endpoint — /ws/owner/{owner_id}

Owner must be authenticated. Receives updates for all their vehicles.
"""

import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.websocket.connection_manager import manager

logger = logging.getLogger("smartdrive")
router = APIRouter()


@router.websocket("/ws/owner/{owner_id}")
async def owner_websocket(websocket: WebSocket, owner_id: str):
    """WebSocket endpoint for the owner-facing web dashboard.

    Pushes:
    - SAFETY_STATUS_UPDATE: real-time driver/risk status
    - ALERT_NEW / ALERT_ACKNOWLEDGED: alert events
    - TRIP_UPDATE: trip lifecycle
    - LOCATION_UPDATE: vehicle GPS position
    - AI_CONNECTION_STATUS_UPDATE: AI camera connection state
    - ASSISTANCE_UPDATE: highway assistance
    - EMERGENCY_UPDATE: emergency events
    """
    await manager.connect_owner(owner_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "acknowledge_alert":
                    # Will be wired to alert service in Phase 2
                    alert_id = msg.get("alert_id")
                    logger.info(f"Owner {owner_id} acknowledged alert {alert_id}")
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect_owner(owner_id, websocket)
        logger.info(f"Owner WebSocket disconnected: owner={owner_id}")
