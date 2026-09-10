"""Quick API test script for Phase 0/1 verification."""

import httpx
import sys

BASE = "http://localhost:8000"

def main():
    print("=" * 60)
    print("SmartDrive Guardian — Phase 0/1 API Test")
    print("=" * 60)

    # Health check
    r = httpx.get(f"{BASE}/health")
    print(f"\n[1] Health check: {r.status_code}")
    print(f"    Response: {r.json()}")
    assert r.status_code == 200, "Health check failed!"

    # Register owner
    r = httpx.post(f"{BASE}/api/v1/owners/register", json={
        "name": "Test Owner",
        "email": "owner@smartdrive.test",
        "phone": "+1234567890",
        "password": "testpassword123",
    })
    print(f"\n[2] Register owner: {r.status_code}")
    if r.status_code == 201:
        owner = r.json()
    elif r.status_code == 400:
        # Already exists — login instead
        r2 = httpx.post(f"{BASE}/api/v1/owners/login", json={
            "email": "owner@smartdrive.test",
            "password": "testpassword123",
        })
        owner = r2.json()["owner"]
    else:
        print(f"    Error: {r.text}")
        sys.exit(1)
    
    owner_id = owner["id"]
    print(f"    Owner ID: {owner_id}")
    print(f"    Name: {owner['name']}")

    # Register vehicle
    r = httpx.post(f"{BASE}/api/v1/vehicles/{owner_id}", json={
        "plate_number": "MH-01-AB-1234",
        "make": "Toyota",
        "model": "Camry",
        "year": 2024,
    })
    print(f"\n[3] Register vehicle: {r.status_code}")
    if r.status_code == 201:
        vehicle = r.json()
    elif r.status_code == 400:
        r2 = httpx.get(f"{BASE}/api/v1/vehicles/{owner_id}")
        vehicle = r2.json()[0]
    else:
        print(f"    Error: {r.text}")
        sys.exit(1)
    
    vehicle_id = vehicle["id"]
    print(f"    Vehicle ID: {vehicle_id}")
    print(f"    Plate: {vehicle['plate_number']}")

    # Start trip
    r = httpx.post(f"{BASE}/api/v1/trips/", json={
        "vehicle_id": vehicle_id,
        "start_latitude": 19.076,
        "start_longitude": 72.877,
    })
    print(f"\n[4] Start trip: {r.status_code}")
    trip = r.json()
    trip_id = trip["id"]
    print(f"    Trip ID: {trip_id}")
    print(f"    Status: {trip['status']}")

    # Check AI connection
    r = httpx.get(f"{BASE}/api/v1/ai/connection-status")
    print(f"\n[5] AI connection status: {r.status_code}")
    print(f"    Status: {r.json()['status']}")

    # List safety events
    r = httpx.get(f"{BASE}/api/v1/safety/vehicle/{vehicle_id}")
    print(f"\n[6] Safety events: {r.status_code}")
    print(f"    Count: {len(r.json())}")

    # Get vehicle details
    r = httpx.get(f"{BASE}/api/v1/vehicles/detail/{vehicle_id}")
    print(f"\n[7] Vehicle detail: {r.status_code}")

    # API docs
    r = httpx.get(f"{BASE}/docs")
    print(f"\n[8] API docs page: {r.status_code}")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)
    print(f"\nOwner ID:   {owner_id}")
    print(f"Vehicle ID: {vehicle_id}")
    print(f"Trip ID:    {trip_id}")
    print(f"\nDriver WS:  ws://localhost:8000/ws/driver/{vehicle_id}")
    print(f"Owner WS:   ws://localhost:8000/ws/owner/{owner_id}")


if __name__ == "__main__":
    main()
