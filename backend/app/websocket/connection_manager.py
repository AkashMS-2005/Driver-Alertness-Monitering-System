"""WebSocket connection manager — tracks active driver and owner connections."""

import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("smartdrive")


class ConnectionManager:
    """Manages WebSocket connections for both driver and owner dashboards.

    - Driver connections: keyed by vehicle_id
    - Owner connections: keyed by owner_id
    """

    def __init__(self):
        # vehicle_id → set of WebSocket connections
        self._driver_connections: Dict[str, Set[WebSocket]] = {}
        # owner_id → set of WebSocket connections
        self._owner_connections: Dict[str, Set[WebSocket]] = {}

    async def connect_driver(self, vehicle_id: str, websocket: WebSocket):
        """Accept and register a driver dashboard WebSocket connection."""
        await websocket.accept()
        if vehicle_id not in self._driver_connections:
            self._driver_connections[vehicle_id] = set()
        self._driver_connections[vehicle_id].add(websocket)
        logger.info(f"Driver dashboard connected for vehicle {vehicle_id}")

    async def connect_owner(self, owner_id: str, websocket: WebSocket):
        """Accept and register an owner dashboard WebSocket connection."""
        await websocket.accept()
        if owner_id not in self._owner_connections:
            self._owner_connections[owner_id] = set()
        self._owner_connections[owner_id].add(websocket)
        logger.info(f"Owner dashboard connected for owner {owner_id}")

    def disconnect_driver(self, vehicle_id: str, websocket: WebSocket):
        """Remove a driver dashboard WebSocket connection."""
        if vehicle_id in self._driver_connections:
            self._driver_connections[vehicle_id].discard(websocket)
            if not self._driver_connections[vehicle_id]:
                del self._driver_connections[vehicle_id]
        logger.info(f"Driver dashboard disconnected for vehicle {vehicle_id}")

    def disconnect_owner(self, owner_id: str, websocket: WebSocket):
        """Remove an owner dashboard WebSocket connection."""
        if owner_id in self._owner_connections:
            self._owner_connections[owner_id].discard(websocket)
            if not self._owner_connections[owner_id]:
                del self._owner_connections[owner_id]
        logger.info(f"Owner dashboard disconnected for owner {owner_id}")

    async def send_to_vehicle(self, vehicle_id: str, data: dict):
        """Send a message to all driver dashboard connections for a vehicle."""
        connections = self._driver_connections.get(vehicle_id, set())
        dead = set()
        for ws in connections:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect_driver(vehicle_id, ws)

    async def send_to_owner(self, owner_id: str, data: dict):
        """Send a message to all owner dashboard connections for an owner."""
        connections = self._owner_connections.get(owner_id, set())
        dead = set()
        for ws in connections:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect_owner(owner_id, ws)

    async def broadcast_to_all_drivers(self, data: dict):
        """Broadcast to all connected driver dashboards."""
        for vehicle_id in list(self._driver_connections.keys()):
            await self.send_to_vehicle(vehicle_id, data)

    async def broadcast_to_all_owners(self, data: dict):
        """Broadcast to all connected owner dashboards."""
        for owner_id in list(self._owner_connections.keys()):
            await self.send_to_owner(owner_id, data)

    async def broadcast_to_all(self, data: dict):
        """Broadcast to every connected dashboard."""
        await self.broadcast_to_all_drivers(data)
        await self.broadcast_to_all_owners(data)

    @property
    def active_driver_count(self) -> int:
        return sum(len(v) for v in self._driver_connections.values())

    @property
    def active_owner_count(self) -> int:
        return sum(len(v) for v in self._owner_connections.values())


# Singleton instance used across the application
manager = ConnectionManager()
