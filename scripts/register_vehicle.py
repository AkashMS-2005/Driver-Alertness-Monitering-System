"""Register a vehicle for testing — run from backend directory.

Usage:
  python -m scripts.register_vehicle

Creates a test owner and vehicle via the REST API.
"""

import httpx
import sys

BACKEND_URL = "http://localhost:8000"


def main():
    print("=" * 50)
    print("SmartDrive Guardian — Vehicle Registration")
    print("=" * 50)

    # Register owner
    print("\nRegistering test owner...")
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/owners/register",
        json={
            "name": "Test Owner",
            "email": "owner@smartdrive.test",
            "phone": "+1234567890",
            "password": "testpassword123",
        },
    )
    if resp.status_code == 201:
        owner = resp.json()
        print(f"  Owner created: {owner['name']} (ID: {owner['id']})")
    elif resp.status_code == 400:
        print("  Owner already exists, logging in...")
        resp = httpx.post(
            f"{BACKEND_URL}/api/v1/owners/login",
            json={"email": "owner@smartdrive.test", "password": "testpassword123"},
        )
        if resp.status_code != 200:
            print(f"  Login failed: {resp.text}")
            sys.exit(1)
        owner = resp.json()["owner"]
        print(f"  Logged in as: {owner['name']} (ID: {owner['id']})")
    else:
        print(f"  Error: {resp.text}")
        sys.exit(1)

    owner_id = owner["id"]

    # Register vehicle
    print("\nRegistering test vehicle...")
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/vehicles/{owner_id}",
        json={
            "plate_number": "MH-01-AB-1234",
            "make": "Toyota",
            "model": "Camry",
            "year": 2024,
        },
    )
    if resp.status_code == 201:
        vehicle = resp.json()
        print(f"  Vehicle created: {vehicle['make']} {vehicle['model']} (ID: {vehicle['id']})")
    elif resp.status_code == 400:
        print("  Vehicle already registered")
        resp = httpx.get(f"{BACKEND_URL}/api/v1/vehicles/{owner_id}")
        vehicles = resp.json()
        if vehicles:
            vehicle = vehicles[0]
            print(f"  Using existing: {vehicle['make']} {vehicle['model']} (ID: {vehicle['id']})")
        else:
            print("  No vehicles found!")
            sys.exit(1)
    else:
        print(f"  Error: {resp.text}")
        sys.exit(1)

    # Start a trip
    vehicle_id = vehicle["id"]
    print("\nStarting test trip...")
    resp = httpx.post(
        f"{BACKEND_URL}/api/v1/trips/",
        json={
            "vehicle_id": vehicle_id,
            "start_latitude": 19.0760,
            "start_longitude": 72.8777,
        },
    )
    if resp.status_code == 201:
        trip = resp.json()
        print(f"  Trip started: {trip['id']}")
    else:
        print(f"  Error: {resp.text}")

    print("\n" + "=" * 50)
    print("Registration complete!")
    print(f"  Owner ID:   {owner_id}")
    print(f"  Vehicle ID: {vehicle_id}")
    print(f"\nDriver dashboard WebSocket: ws://localhost:8000/ws/driver/{vehicle_id}")
    print(f"Owner dashboard WebSocket:  ws://localhost:8000/ws/owner/{owner_id}")
    print("=" * 50)


if __name__ == "__main__":
    main()
