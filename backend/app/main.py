"""SmartDrive Guardian — FastAPI Application.

Main entry point for the backend server. Handles:
- REST API for owners, vehicles, trips, safety, assistance, emergency, location, dashboard
- WebSocket endpoints for the unified dashboard
- AI WebSocket client connection to the AI service
- Risk Engine processing
- Default data seeding for single-laptop development
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.router import api_router
from app.websocket.driver_socket import router as driver_ws_router
from app.websocket.owner_socket import router as owner_ws_router
from app.db.database import init_db, async_session
from app.services.ai_connection_service import ai_connection_service
from app.ai_client.ai_ws_client import ai_ws_client
from app.api.v1.ai_connection_routes import set_ai_connection_state

logger = logging.getLogger("smartdrive")


async def seed_default_data():
    """Seed a default Owner, Vehicle, and active Trip if none exist.

    This allows the unified dashboard to work immediately without
    manual registration steps during development.
    """
    try:
        from sqlalchemy import select
        from app.models.owner import Owner
        from app.models.vehicle import Vehicle
        from app.models.trip import Trip
        from app.core.security import hash_password

        async with async_session() as session:
            # Check if any owner exists
            result = await session.execute(select(Owner).limit(1))
            existing_owner = result.scalar_one_or_none()

            if existing_owner:
                logger.info(f"Default owner already exists: {existing_owner.name} ({existing_owner.email})")
                # Ensure there's an active trip
                veh_result = await session.execute(
                    select(Vehicle).where(Vehicle.owner_id == existing_owner.id).limit(1)
                )
                vehicle = veh_result.scalar_one_or_none()
                if vehicle:
                    trip_result = await session.execute(
                        select(Trip).where(
                            Trip.vehicle_id == vehicle.id, Trip.status == "ACTIVE"
                        ).limit(1)
                    )
                    active_trip = trip_result.scalar_one_or_none()
                    if not active_trip:
                        # Start a fresh trip
                        new_trip = Trip(
                            vehicle_id=vehicle.id,
                            status="ACTIVE",
                            start_latitude=12.9716,
                            start_longitude=77.5946,
                            distance_km=0.0,
                        )
                        session.add(new_trip)
                        await session.commit()
                        logger.info(f"New active trip started for vehicle {vehicle.plate_number}")
                return

            # Seed default owner
            owner = Owner(
                name="SmartDrive Owner",
                email="owner@smartdrive.local",
                phone="+91-9876543210",
                password_hash=hash_password("smartdrive123"),
            )
            session.add(owner)
            await session.flush()
            await session.refresh(owner)
            logger.info(f"Default owner seeded: {owner.name} ({owner.email})")

            # Seed default vehicle
            vehicle = Vehicle(
                owner_id=owner.id,
                plate_number="KA-09-AB-1234",
                make="Toyota",
                model="Innova Crysta",
                year=2023,
            )
            session.add(vehicle)
            await session.flush()
            await session.refresh(vehicle)
            logger.info(f"Default vehicle seeded: {vehicle.plate_number}")

            # Seed active trip (starting at Bengaluru city center)
            trip = Trip(
                vehicle_id=vehicle.id,
                status="ACTIVE",
                start_latitude=12.9716,
                start_longitude=77.5946,
                distance_km=0.0,
            )
            session.add(trip)
            await session.commit()
            logger.info(f"Default active trip started for vehicle {vehicle.plate_number}")

    except Exception as exc:
        logger.warning(f"Default data seeding failed (non-fatal): {exc}")


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

    # Seed default owner/vehicle/trip for development
    await seed_default_data()

    # Register AI connection state for the REST endpoint
    set_ai_connection_state(ai_connection_service.get_state())
    logger.info(f"AI Service target: {settings.ai_ws_url}")

    # Start AI WebSocket Client background worker
    ai_task = asyncio.create_task(ai_ws_client.start())

    logger.info(f"Backend ready at http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("SmartDrive Guardian Backend — Shutting down")
    await ai_ws_client.stop()
    ai_task.cancel()
    try:
        await ai_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="SmartDrive Guardian",
    description="Driver drowsiness detection, trip tracking, and emergency assistance system",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware — allow unified dashboard on ports 5173 and 5174
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routes
app.include_router(api_router)

# WebSocket routes (both endpoints kept — dashboard connects to /ws/drowsiness)
app.include_router(driver_ws_router)
app.include_router(owner_ws_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "SmartDrive Guardian Backend",
        "version": "2.0.0",
        "ai_connection": ai_connection_service.get_state().status,
    }
