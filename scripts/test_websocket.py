"""Test WebSocket connectivity for Phase 1."""

import asyncio
import json
import websockets


async def test_driver_ws():
    vehicle_id = "test-vehicle-123"
    uri = f"ws://localhost:8000/ws/driver/{vehicle_id}"
    print(f"Connecting to driver WS: {uri}")
    try:
        async with websockets.connect(uri) as ws:
            print("  CONNECTED!")
            # Send ping
            await ws.send(json.dumps({"type": "ping"}))
            resp = await asyncio.wait_for(ws.recv(), timeout=3)
            print(f"  Ping response: {resp}")
            assert json.loads(resp)["type"] == "pong"
            print("  Ping/Pong OK!")
    except Exception as e:
        print(f"  Error: {e}")
        return False
    return True


async def test_owner_ws():
    owner_id = "test-owner-456"
    uri = f"ws://localhost:8000/ws/owner/{owner_id}"
    print(f"\nConnecting to owner WS: {uri}")
    try:
        async with websockets.connect(uri) as ws:
            print("  CONNECTED!")
            await ws.send(json.dumps({"type": "ping"}))
            resp = await asyncio.wait_for(ws.recv(), timeout=3)
            print(f"  Ping response: {resp}")
            assert json.loads(resp)["type"] == "pong"
            print("  Ping/Pong OK!")
    except Exception as e:
        print(f"  Error: {e}")
        return False
    return True


async def main():
    print("=" * 50)
    print("WebSocket Connectivity Test")
    print("=" * 50)
    r1 = await test_driver_ws()
    r2 = await test_owner_ws()
    print("\n" + "=" * 50)
    if r1 and r2:
        print("ALL WEBSOCKET TESTS PASSED!")
    else:
        print("SOME TESTS FAILED!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
