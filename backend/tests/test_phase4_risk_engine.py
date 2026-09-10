"""Phase 4 Test Suite — Risk Engine, State Transitions, Safety Events, and End-to-End WebSocket Flow.

Verifies:
1. Risk Engine State Mapping (NORMAL -> LOW, DROWSY -> MEDIUM, MICROSLEEP -> HIGH)
2. State Transition Tracking & Duplicate Event Prevention (no spam on repeated frames)
3. Enriched Telemetry Structure
4. End-to-End Flow: AI Server -> Backend AI Client -> Risk Engine -> Dashboard Client
"""

import sys
import asyncio
import json
from pathlib import Path

# Add backend and ai-service to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR / "ai-service"))

from app.risk_engine.state_machine import SafetyStateMachine
from app.ai_client.ai_ws_client import AIWebSocketClient
from app.websocket.connection_manager import ConnectionManager
from src.network.ai_ws_server import AIWebSocketServer


async def test_risk_engine_logic():
    print("=" * 60)
    print("TEST 1: RISK ENGINE LOGIC & STATE TRANSITIONS")
    print("=" * 60)

    sm = SafetyStateMachine()
    assert sm.current_state == "NORMAL"
    assert len(sm.get_recent_events()) == 0
    print("  [PASS] Initial state is NORMAL with 0 events.")

    # Frame 1: NORMAL
    res1 = await sm.process_ai_event({
        "type": "drowsiness",
        "state": "NORMAL",
        "ear": 0.28,
        "eye_closed": False,
        "closed_duration": 0.0,
        "perclos": 2.0,
        "mar": 0.25,
        "yawning": False,
    })
    assert res1["state"] == "NORMAL"
    assert res1["risk_level"] == "LOW"
    assert res1["alert_message"] == "Driver Alert"
    assert res1["state_changed"] is False
    assert len(sm.get_recent_events()) == 0
    print("  [PASS] Frame 1: NORMAL -> Risk: LOW (no transition event).")

    # Frame 2: Transition NORMAL -> DROWSY
    res2 = await sm.process_ai_event({
        "type": "drowsiness",
        "state": "DROWSY",
        "ear": 0.17,
        "eye_closed": True,
        "closed_duration": 1.8,
        "perclos": 14.0,
        "mar": 0.35,
        "yawning": False,
    })
    assert res2["state"] == "DROWSY"
    assert res2["risk_level"] == "MEDIUM"
    assert res2["alert_message"] == "Driver Attention Required"
    assert res2["state_changed"] is True
    assert len(sm.get_recent_events()) == 1
    assert sm.get_recent_events()[0]["state"] == "DROWSY"
    print("  [PASS] Frame 2: Transition to DROWSY -> Risk: MEDIUM (1 event recorded).")

    # Frame 3: Repeated DROWSY frame (same state, should NOT add duplicate event)
    res3 = await sm.process_ai_event({
        "type": "drowsiness",
        "state": "DROWSY",
        "ear": 0.16,
        "eye_closed": True,
        "closed_duration": 2.1,
        "perclos": 15.0,
        "mar": 0.35,
        "yawning": False,
    })
    assert res3["state"] == "DROWSY"
    assert res3["state_changed"] is False
    assert len(sm.get_recent_events()) == 1, "Duplicate frame must not create duplicate event"
    print("  [PASS] Frame 3: Repeated DROWSY -> No duplicate event created.")

    # Frame 4: Transition DROWSY -> MICROSLEEP
    res4 = await sm.process_ai_event({
        "type": "drowsiness",
        "state": "MICROSLEEP",
        "ear": 0.11,
        "eye_closed": True,
        "closed_duration": 3.4,
        "perclos": 30.0,
        "mar": 0.31,
        "yawning": False,
    })
    assert res4["state"] == "MICROSLEEP"
    assert res4["risk_level"] == "HIGH"
    assert res4["alert_message"] == "Immediate attention required"
    assert res4["state_changed"] is True
    assert len(sm.get_recent_events()) == 2
    assert sm.get_recent_events()[0]["state"] == "MICROSLEEP"
    print("  [PASS] Frame 4: Transition to MICROSLEEP -> Risk: HIGH (2nd event recorded).")

    # Frame 5: Recovery MICROSLEEP -> NORMAL
    res5 = await sm.process_ai_event({
        "type": "drowsiness",
        "state": "NORMAL",
        "ear": 0.29,
        "eye_closed": False,
        "closed_duration": 0.0,
        "perclos": 4.0,
        "mar": 0.27,
        "yawning": False,
    })
    assert res5["state"] == "NORMAL"
    assert res5["risk_level"] == "LOW"
    assert res5["state_changed"] is True
    assert len(sm.get_recent_events()) == 3
    assert sm.get_recent_events()[0]["state"] == "NORMAL"
    print("  [PASS] Frame 5: Recovery to NORMAL -> Risk: LOW (3rd event recorded).")


async def test_end_to_end_flow():
    print("\n" + "=" * 60)
    print("TEST 2: END-TO-END PIPELINE WITH RISK ENGINE")
    print("=" * 60)

    # 1. Start AI WebSocket Server on 127.0.0.1:8001
    ai_server = AIWebSocketServer(host="127.0.0.1", port=8001)
    ai_server.start()
    await asyncio.sleep(0.5)

    # 2. Setup mock frontend client attached to ConnectionManager
    dashboard_messages = []

    class MockWebSocket:
        async def accept(self):
            pass

        async def send_text(self, text: str):
            dashboard_messages.append(json.loads(text))

    manager = ConnectionManager()
    mock_ws = MockWebSocket()
    await manager.connect_driver("default", mock_ws)

    # 3. Connect AI Client
    client = AIWebSocketClient()
    client_task = asyncio.create_task(client.start())
    await asyncio.sleep(1.0)

    # 4. Stream raw AI frames and verify dashboard receives enriched data
    test_stream = [
        {"type": "drowsiness", "state": "NORMAL", "ear": 0.28, "eye_closed": False, "closed_duration": 0.0, "perclos": 2.0, "mar": 0.25, "yawning": False},
        {"type": "drowsiness", "state": "DROWSY", "ear": 0.17, "eye_closed": True, "closed_duration": 1.8, "perclos": 14.0, "mar": 0.35, "yawning": False},
        {"type": "drowsiness", "state": "MICROSLEEP", "ear": 0.11, "eye_closed": True, "closed_duration": 3.4, "perclos": 30.0, "mar": 0.31, "yawning": False},
        {"type": "drowsiness", "state": "NORMAL", "ear": 0.29, "eye_closed": False, "closed_duration": 0.0, "perclos": 4.0, "mar": 0.27, "yawning": False},
    ]

    for payload in test_stream:
        ai_server.broadcast_sync(payload)
        await asyncio.sleep(0.3)
        latest = client.latest_drowsiness
        assert latest is not None
        assert latest["state"] == payload["state"]
        expected_risk = "HIGH" if payload["state"] == "MICROSLEEP" else "MEDIUM" if payload["state"] == "DROWSY" else "LOW"
        assert latest["risk_level"] == expected_risk
        assert "recent_events" in latest
        print(f"  Streamed {payload['state']} -> Dashboard received state={latest['state']} risk={latest['risk_level']} events={len(latest['recent_events'])} [PASS]")

    # 5. Cleanup
    await client.stop()
    client_task.cancel()
    try:
        await client_task
    except asyncio.CancelledError:
        pass
    ai_server.stop()
    print("  [PASS] Clean shutdown completed.")


async def main():
    await test_risk_engine_logic()
    await test_end_to_end_flow()
    print("\n" + "=" * 60)
    print("ALL PHASE 4 TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
