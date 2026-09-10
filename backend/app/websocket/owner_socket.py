"""Owner dashboard WebSocket endpoint — /ws/owner/{owner_id}

Provides real-time safety status snapshots, vehicle status, and drowsiness events to the Owner Dashboard.
"""

import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.websocket.connection_manager import manager
from app.services.ai_connection_service import ai_connection_service

logger = logging.getLogger("smartdrive")
router = APIRouter()


async def _send_owner_initial_state(websocket: WebSocket):
    """Send initial safety snapshot, AI connection, and recent events to Owner Dashboard."""
    from app.ai_client.ai_ws_client import ai_ws_client
    from app.risk_engine.state_machine import risk_engine

    conn_state = ai_connection_service.get_state()

    # Send AI connection status
    status_payload = {
        "event_type": "AI_CONNECTION_STATUS_UPDATE",
        "status": conn_state.status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await websocket.send_text(json.dumps(status_payload))
    except Exception:
        pass

    # Send latest drowsiness & risk state
    if ai_ws_client.latest_drowsiness:
        try:
            await websocket.send_text(json.dumps(ai_ws_client.latest_drowsiness))
        except Exception:
            pass
    else:
        initial_drowsiness = {
            "type": "drowsiness_update",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": "NORMAL",
            "risk_level": "LOW",
            "alert_message": "Driver Alert",
            "state_changed": False,
            "ear": 0.0,
            "eye_closed": False,
            "closed_duration": 0.0,
            "perclos": 0.0,
            "mar": 0.0,
            "yawning": False,
            "recent_events": risk_engine.get_recent_events(),
        }
        try:
            await websocket.send_text(json.dumps(initial_drowsiness))
        except Exception:
            pass


@router.websocket("/ws/owner/{owner_id}")
async def owner_websocket(websocket: WebSocket, owner_id: str):
    """WebSocket endpoint for the owner-facing web dashboard."""
    await manager.connect_owner(owner_id, websocket)
    await _send_owner_initial_state(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect_owner(owner_id, websocket)
        logger.info(f"Owner WebSocket disconnected: owner={owner_id}")
