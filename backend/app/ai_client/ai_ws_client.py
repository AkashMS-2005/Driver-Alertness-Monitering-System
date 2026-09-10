"""AI WebSocket client — connects to the AI service on Laptop 1.

Phase 3: Connects to ws://{AI_SERVER_HOST}:{AI_SERVER_PORT}/ws/ai on Laptop 1.
Receives real-time drowsiness telemetry, caches the latest state in memory,
and broadcasts the telemetry to connected React driver dashboards.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
import websockets
from websockets.exceptions import ConnectionClosed

from app.core.config import settings
from app.services.ai_connection_service import ai_connection_service
from app.websocket.connection_manager import manager

logger = logging.getLogger("smartdrive.ai_client")

VALID_STATES = {"NORMAL", "DROWSY", "MICROSLEEP"}


class AIWebSocketClient:
    """Connects to the AI Service on Laptop 1 and forwards telemetry."""

    def __init__(self):
        self._running = False
        self._ws = None
        self.latest_drowsiness: Optional[Dict[str, Any]] = None
        self._backoff_index = 0

    def _validate_drowsiness_payload(self, data: dict) -> bool:
        """Validate that the incoming payload has the required drowsiness fields."""
        if not isinstance(data, dict):
            return False
        if data.get("type") != "drowsiness":
            return False
        if data.get("state") not in VALID_STATES:
            return False
        return True

    async def _handle_message(self, message: str):
        """Parse, validate, enrich with risk engine, and broadcast telemetry."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received from AI service: {message[:100]}")
            return

        if not self._validate_drowsiness_payload(data):
            logger.debug(f"Non-drowsiness or invalid payload ignored: {data}")
            return

        # Process through Risk Engine (state transitions, risk level mapping, safety events)
        from app.risk_engine.state_machine import risk_engine
        enriched_data = await risk_engine.process_ai_event(data)

        # Cache latest result in memory
        self.latest_drowsiness = enriched_data

        # Update connection service detection timestamp
        await ai_connection_service.on_detection_received()

        # Forward enriched telemetry to connected driver dashboard clients
        await manager.broadcast_to_all_drivers(enriched_data)

    async def _connect_and_listen(self):
        """Single connection session to the AI WebSocket server."""
        url = settings.ai_ws_url
        logger.info(f"Connecting to AI service at {url}...")

        async with websockets.connect(url, ping_interval=None) as ws:
            self._ws = ws
            self._backoff_index = 0
            await ai_connection_service.on_connected(settings.AI_SERVER_HOST, settings.AI_SERVER_PORT)
            logger.info(f"Connected to AI service at {url}")

            # Listen for incoming detection stream
            async for message in ws:
                if not self._running:
                    break
                await self._handle_message(message)

    async def start(self):
        """Start the background connection loop with retry backoff."""
        self._running = True
        logger.info(f"AI WebSocket client loop starting (target: {settings.ai_ws_url})")

        backoff_schedule = settings.AI_RECONNECT_BACKOFF_SECONDS or [2, 5, 10, 20]

        while self._running:
            try:
                await self._connect_and_listen()
            except (ConnectionRefusedError, OSError, ConnectionClosed, asyncio.TimeoutError) as e:
                if self._running:
                    await ai_connection_service.on_disconnected(str(e))
                    delay = backoff_schedule[min(self._backoff_index, len(backoff_schedule) - 1)]
                    self._backoff_index += 1
                    logger.warning(
                        f"AI service connection failed ({e}). Retrying in {delay}s... "
                        f"[target: {settings.ai_ws_url}]"
                    )
                    await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"Unexpected error in AI client: {e}")
                    await ai_connection_service.on_disconnected(str(e))
                    await asyncio.sleep(3)

        logger.info("AI WebSocket client loop terminated.")

    async def stop(self):
        """Stop the client and close connection."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        await ai_connection_service.on_disconnected("Client stopped")
        logger.info("AI WebSocket client stopped.")


# Singleton instance
ai_ws_client = AIWebSocketClient()
