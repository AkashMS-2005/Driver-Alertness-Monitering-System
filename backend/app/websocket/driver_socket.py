import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.websocket.connection_manager import manager
from app.services.ai_connection_service import ai_connection_service

logger = logging.getLogger("smartdrive")
router = APIRouter()


async def _send_initial_state(websocket: WebSocket):
    """Send initial drowsiness and connection state to newly connected client."""
    from app.ai_client.ai_ws_client import ai_ws_client
    conn_state = ai_connection_service.get_state()

    # Send AI connection status
    status_payload = {
        "event_type": "AI_CONNECTION_STATUS_UPDATE",
        "status": conn_state.status,
        "last_detection_at": (
            conn_state.last_detection_at.isoformat()
            if conn_state.last_detection_at
            else None
        ),
        "seconds_since_last_detection": conn_state.seconds_since_last_detection,
        "message": "AI CAMERA: " + conn_state.status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await websocket.send_text(json.dumps(status_payload))
    except Exception:
        pass

    # Send latest drowsiness telemetry if present, or default initial telemetry
    if ai_ws_client.latest_drowsiness:
        try:
            await websocket.send_text(json.dumps(ai_ws_client.latest_drowsiness))
        except Exception:
            pass
    else:
        from app.risk_engine.state_machine import risk_engine
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


@router.websocket("/ws/drowsiness")
async def drowsiness_websocket(websocket: WebSocket):
    """Direct drowsiness WebSocket endpoint for the React Driver Dashboard."""
    vehicle_id = "default"
    await manager.connect_driver(vehicle_id, websocket)
    await _send_initial_state(websocket)
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
        manager.disconnect_driver(vehicle_id, websocket)
        logger.info("Driver dashboard (/ws/drowsiness) disconnected")


@router.websocket("/ws/driver/{vehicle_id}")
async def driver_websocket(websocket: WebSocket, vehicle_id: str):
    """WebSocket endpoint for the driver-facing in-car dashboard by vehicle_id."""
    await manager.connect_driver(vehicle_id, websocket)
    await _send_initial_state(websocket)
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
        manager.disconnect_driver(vehicle_id, websocket)
        logger.info(f"Driver WebSocket disconnected: vehicle={vehicle_id}")

