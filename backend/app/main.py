"""SmartDrive Guardian — FastAPI Application (Laptop 2).

Main entry point for the backend server. Handles:
- REST API for owners, vehicles, trips, safety, assistance, emergency
- WebSocket endpoints for driver and owner dashboards
- AI WebSocket client connection to Laptop 1 (Phase 3)
- Risk Engine processing (Phase 4)
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.router import api_router
from app.websocket.driver_socket import router as driver_ws_router
from app.websocket.owner_socket import router as owner_ws_router
from app.db.database import init_db
from app.services.ai_connection_service import ai_connection_service
from app.api.v1.ai_connection_routes import set_ai_connection_state

logger = logging.getLogger("smartdrive")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # Startup
    logger.info("=" * 60)
    logger.info("SmartDrive Guardian Backend — Starting")
    logger.info("=" * 60)

    # Initialize database tables (development — use Alembic in production)
    await init_db()
    logger.info("Database initialized")

    # Register AI connection state for the REST endpoint
    set_ai_connection_state(ai_connection_service.get_state())
    logger.info(f"AI Service target: ws://{settings.AI_SERVER_HOST}:{settings.AI_SERVER_PORT}/ws/ai")
    logger.info("AI WebSocket client: will be started in Phase 3")

    logger.info(f"Backend ready at http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("SmartDrive Guardian Backend — Shutting down")


app = FastAPI(
    title="SmartDrive Guardian",
    description="Highway-only driver safety monitoring system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routes
app.include_router(api_router)

# WebSocket routes
app.include_router(driver_ws_router)
app.include_router(owner_ws_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "SmartDrive Guardian Backend",
        "ai_connection": ai_connection_service.get_state().status,
    }
