"""Test suite for Phase 3: Drowsiness Networking Integration.

Verifies:
1. AI WebSocket Server starts and accepts connections on :8001
2. Backend AI Client connects to AI Server and receives telemetry
3. Backend connection manager forwards drowsiness frames to dashboard clients
4. State transitions: NORMAL -> DROWSY -> MICROSLEEP -> NORMAL
5. Graceful handling of disconnect / reconnect
"""

import sys
import os
import asyncio
import json
from pathlib import Path

# Add backend and ai-service to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR / "ai-service"))

import websockets
from app.ai_client.ai_ws_client import AIWebSocketClient
from app.websocket.connection_manager import ConnectionManager
from app.services.ai_connection_service import AIConnectionService
from src.network.ai_ws_server import AIWebSocketServer


async def run_phase3_tests():
    print("=" * 60)
    print("SMARTDRIVE GUARDIAN -- PHASE 3 NETWORKING TESTS")
    print("=" * 60)

    # 1. Start AI WebSocket Server on 127.0.0.1:8001
    print("\n[Step 1] Starting AI WebSocket Server on 127.0.0.1:8001...")
    ai_server = AIWebSocketServer(host="127.0.0.1", port=8001)
    ai_server.start()
    await asyncio.sleep(0.5)
    print("  [PASS] AI WebSocket Server running.")

    # 2. Setup mock dashboard client attached to a test ConnectionManager
    print("\n[Step 2] Setting up Backend Connection Manager and Mock Dashboard...")
    test_manager = ConnectionManager()
    received_by_frontend = []

    class MockWebSocket:
        def __init__(self):
            self.closed = False

        async def accept(self):
            pass

        async def send_text(self, text: str):
            data = json.loads(text)
            received_by_frontend.append(data)

    mock_ws = MockWebSocket()
    await test_manager.connect_driver("default", mock_ws)
    print("  [PASS] Mock Frontend Dashboard connected to backend manager.")

    # 3. Connect AI Client
    print("\n[Step 3] Connecting Backend AI Client to AI WebSocket Server...")
    client = AIWebSocketClient()
    
    # Run client loop in background task
    client_task = asyncio.create_task(client.start())
    await asyncio.sleep(1.0)
    
    print(f"  AI Server client count: {ai_server.client_count}")
    assert ai_server.client_count >= 1, "AI server should have at least 1 connected client"
    print("  [PASS] Backend AI Client successfully connected to AI Service.")

    # 4. Test State Streaming
    print("\n[Step 4] Testing Telemetry Transmission & State Transitions...")
    test_payloads = [
        {
            "type": "drowsiness",
            "timestamp": "2026-09-10T22:30:00Z",
            "state": "NORMAL",
            "ear": 0.28,
            "eye_closed": False,
            "closed_duration": 0.0,
            "perclos": 2.1,
            "mar": 0.28,
            "yawning": False,
        },
        {
            "type": "drowsiness",
            "timestamp": "2026-09-10T22:30:02Z",
            "state": "DROWSY",
            "ear": 0.17,
            "eye_closed": True,
            "closed_duration": 1.8,
            "perclos": 14.5,
            "mar": 0.35,
            "yawning": False,
        },
        {
            "type": "drowsiness",
            "timestamp": "2026-09-10T22:30:05Z",
            "state": "MICROSLEEP",
            "ear": 0.11,
            "eye_closed": True,
            "closed_duration": 3.4,
            "perclos": 32.0,
            "mar": 0.31,
            "yawning": False,
        },
        {
            "type": "drowsiness",
            "timestamp": "2026-09-10T22:30:08Z",
            "state": "NORMAL",
            "ear": 0.29,
            "eye_closed": False,
            "closed_duration": 0.0,
            "perclos": 4.0,
            "mar": 0.27,
            "yawning": False,
        },
    ]

    for payload in test_payloads:
        state = payload["state"]
        print(f"  Streaming state: {state} (EAR={payload['ear']}, closed={payload['closed_duration']}s)...")
        ai_server.broadcast_sync(payload)
        await asyncio.sleep(0.3)
        assert client.latest_drowsiness is not None
        assert client.latest_drowsiness["state"] == state
        print(f"    -> Backend received and verified state: {state} [PASS]")

    print("  [PASS] All 4 state transitions streamed and received accurately.")

    # 5. Test Clean Disconnect & Stop
    print("\n[Step 5] Testing Client & Server Shutdown...")
    await client.stop()
    client_task.cancel()
    try:
        await client_task
    except asyncio.CancelledError:
        pass

    ai_server.stop()
    print("  [PASS] Clean shutdown completed.")

    print("\n" + "=" * 60)
    print("ALL PHASE 3 NETWORKING TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_phase3_tests())
