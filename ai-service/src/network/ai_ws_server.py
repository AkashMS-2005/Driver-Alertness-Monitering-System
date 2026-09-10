"""AI WebSocket server — streams real-time drowsiness detection results.

Runs on Laptop 1 on port 8001 (path /ws/ai).
Serves detection results from the Phase 2 computer vision pipeline to the
FastAPI backend on Laptop 2.
"""

import asyncio
import json
import logging
import threading
from typing import Set
import websockets

logger = logging.getLogger("smartdrive.ai.ws")


class AIWebSocketServer:
    """Thread-safe WebSocket server for streaming AI telemetry to Laptop 2."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8001):
        self.host = host
        self.port = port
        self._clients: Set[websockets.WebSocketServerProtocol] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server = None
        self._running = False

    async def _handler(self, websocket, path=None):
        """Handle incoming WebSocket client connections."""
        client_addr = getattr(websocket, "remote_address", "unknown")
        logger.info(f"Client connected to AI WebSocket: {client_addr}")
        self._clients.add(websocket)
        try:
            # Keep connection open and read any incoming messages (e.g. pings)
            async for msg in websocket:
                try:
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                except Exception:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.warning(f"Error handling client {client_addr}: {e}")
        finally:
            self._clients.discard(websocket)
            logger.info(f"Client disconnected from AI WebSocket: {client_addr}")

    async def _start_server(self):
        """Internal coroutine to start websockets server."""
        self._server = await websockets.serve(self._handler, self.host, self.port)
        logger.info(f"AI WebSocket server listening on ws://{self.host}:{self.port}/ws/ai")
        await asyncio.Future()  # run forever until cancelled

    def _run_event_loop(self):
        """Runs the event loop in a dedicated background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_server())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self._running:
                logger.error(f"WebSocket server exception: {e}")
        finally:
            self._loop.close()

    def start(self):
        """Start the WebSocket server in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()
        logger.info(f"AI WebSocket server background thread started (port {self.port})")

    async def _broadcast_coroutine(self, message_str: str):
        """Coroutine to send message to all connected clients."""
        if not self._clients:
            return
        # Broadcast concurrently to all clients
        websockets_list = list(self._clients)
        for ws in websockets_list:
            try:
                await ws.send(message_str)
            except Exception:
                self._clients.discard(ws)

    def broadcast_sync(self, data: dict):
        """Thread-safe method to broadcast telemetry to all connected clients.
        
        Called from the camera loop on the main thread.
        """
        if not self._running or not self._loop or self._loop.is_closed() or not self._clients:
            return
        try:
            message_str = json.dumps(data, default=str)
            asyncio.run_coroutine_threadsafe(
                self._broadcast_coroutine(message_str),
                self._loop
            )
        except Exception as e:
            logger.debug(f"Broadcast error: {e}")

    def stop(self):
        """Stop the WebSocket server cleanly."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("AI WebSocket server stopped.")

    @property
    def client_count(self) -> int:
        return len(self._clients)
