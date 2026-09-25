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
from datetime import datetime, timezone
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


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger("smartdrive")


# ============================================================
# DEFAULT DEVELOPMENT DATA
# ============================================================

async def seed_default_data():
    """Seed a default Owner, Vehicle, and active Trip if none exist.

    This allows the unified dashboard to work immediately during
    development without requiring manual registration.
    """

    try:
        from sqlalchemy import select

        from app.models.owner import Owner
        from app.models.vehicle import Vehicle
        from app.models.trip import Trip

        from app.core.security import hash_password

        async with async_session() as session:

            # ------------------------------------------------
            # Check whether an owner already exists
            # ------------------------------------------------

            result = await session.execute(
                select(Owner).limit(1)
            )

            existing_owner = result.scalar_one_or_none()

            # ------------------------------------------------
            # Existing owner
            # ------------------------------------------------

            if existing_owner:

                logger.info(
                    "Default owner already exists: "
                    f"{existing_owner.name} ({existing_owner.email})"
                )

                # --------------------------------------------
                # Find owner's vehicle
                # --------------------------------------------

                vehicle_result = await session.execute(
                    select(Vehicle)
                    .where(Vehicle.owner_id == existing_owner.id)
                    .limit(1)
                )

                vehicle = vehicle_result.scalar_one_or_none()

                if vehicle:

                    # ----------------------------------------
                    # Check for active trip
                    # ----------------------------------------

                    trip_result = await session.execute(
                        select(Trip)
                        .where(
                            Trip.vehicle_id == vehicle.id,
                            Trip.status == "ACTIVE",
                        )
                        .limit(1)
                    )

                    active_trip = trip_result.scalar_one_or_none()

                    # ----------------------------------------
                    # Create active trip if missing
                    # ----------------------------------------

                    if not active_trip:

                        new_trip = Trip(
                            vehicle_id=vehicle.id,
                            status="ACTIVE",
                            start_latitude=12.9716,
                            start_longitude=77.5946,
                            distance_km=0.0,
                        )

                        session.add(new_trip)

                        await session.commit()

                        logger.info(
                            "New active trip started for vehicle "
                            f"{vehicle.plate_number}"
                        )

                return

            # =================================================
            # CREATE DEFAULT OWNER
            # =================================================

            owner = Owner(
                name="SmartDrive Owner",
                email="owner@smartdrive.local",
                phone="+91-9876543210",
                password_hash=hash_password("smartdrive123"),
            )

            session.add(owner)

            await session.flush()
            await session.refresh(owner)

            logger.info(
                "Default owner seeded: "
                f"{owner.name} ({owner.email})"
            )

            # =================================================
            # CREATE DEFAULT VEHICLE
            # =================================================

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

            logger.info(
                "Default vehicle seeded: "
                f"{vehicle.plate_number}"
            )

            # =================================================
            # CREATE DEFAULT ACTIVE TRIP
            # =================================================

            trip = Trip(
                vehicle_id=vehicle.id,
                status="ACTIVE",
                start_latitude=12.9716,
                start_longitude=77.5946,
                distance_km=0.0,
            )

            session.add(trip)

            await session.commit()

            logger.info(
                "Default active trip started for vehicle "
                f"{vehicle.plate_number}"
            )

    except Exception as exc:

        # Seeding failure should NOT prevent the backend
        # from starting.
        logger.warning(
            f"Default data seeding failed (non-fatal): {exc}"
        )


# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""

    # ========================================================
    # STARTUP
    # ========================================================

    logger.info("=" * 60)
    logger.info("SmartDrive Guardian Backend — Starting")
    logger.info("=" * 60)

    # --------------------------------------------------------
    # Initialize database
    # --------------------------------------------------------

    await init_db()

    logger.info("Database initialized")

    # --------------------------------------------------------
    # Seed development data
    # --------------------------------------------------------

    await seed_default_data()

    # --------------------------------------------------------
    # Register active vehicle/trip IDs with the Risk Engine
    # --------------------------------------------------------
    # This gives the EmergencyEngine real DB IDs so it can
    # create EmergencyEvent records with correct foreign keys.
    try:
        from sqlalchemy import select, update
        from app.models.vehicle import Vehicle
        from app.models.trip import Trip
        from app.models.emergency_event import EmergencyEvent
        from app.risk_engine.state_machine import update_active_vehicle_trip

        async with async_session() as session:
            # Resolve dangling emergencies left over from prior aborted server runs
            now = datetime.now(timezone.utc)
            await session.execute(
                update(EmergencyEvent)
                .where(EmergencyEvent.status.in_(["ACTIVE", "DRIVER_RECOVERED"]))
                .values(status="RESOLVED", resolved_at=now)
            )
            await session.commit()
            logger.info("Dangling unclosed emergencies from prior runs marked as RESOLVED")

            veh_res = await session.execute(select(Vehicle).limit(1))
            veh = veh_res.scalar_one_or_none()
            if veh:
                trip_res = await session.execute(
                    select(Trip)
                    .where(Trip.vehicle_id == veh.id, Trip.status == "ACTIVE")
                    .limit(1)
                )
                trip = trip_res.scalar_one_or_none()
                if trip:
                    update_active_vehicle_trip(veh.id, trip.id)
                    logger.info(
                        f"Risk engine vehicle/trip IDs registered: "
                        f"vehicle={veh.id[:8]}… trip={trip.id[:8]}…"
                    )
    except Exception as exc:
        logger.warning(f"Could not register vehicle/trip IDs (non-fatal): {exc}")

    # --------------------------------------------------------
    # Register AI connection state
    # --------------------------------------------------------

    set_ai_connection_state(
        ai_connection_service.get_state()
    )

    logger.info(
        f"AI Service target: {settings.ai_ws_url}"
    )

    # --------------------------------------------------------
    # Start AI WebSocket background worker
    # --------------------------------------------------------

    ai_task = asyncio.create_task(
        ai_ws_client.start()
    )

    logger.info(
        "Backend ready at "
        f"http://{settings.BACKEND_HOST}:{settings.BACKEND_PORT}"
    )

    logger.info("=" * 60)

    # --------------------------------------------------------
    # Application is now running
    # --------------------------------------------------------

    yield

    # ========================================================
    # SHUTDOWN
    # ========================================================

    logger.info(
        "SmartDrive Guardian Backend — Shutting down"
    )

    await ai_ws_client.stop()

    ai_task.cancel()

    try:
        await ai_task

    except asyncio.CancelledError:
        pass


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="SmartDrive Guardian",
    description=(
        "Driver drowsiness detection, trip tracking, "
        "and emergency assistance system"
    ),
    version="2.0.0",
    lifespan=lifespan,
)


# ============================================================
# CORS CONFIGURATION
# ============================================================
#
# Development frontend:
#
#   http://localhost:5176
#
# Backend:
#
#   http://localhost:8000
#
# We explicitly allow the development frontend ports used
# by the SmartDrive Guardian project.
#
# JWT is stored in localStorage, NOT in cookies.
# Therefore allow_credentials=False is intentional.
#
# ============================================================

DEV_FRONTEND_ORIGINS = [
    "http://localhost:5176",
    "http://localhost:5174",
    "http://localhost:5173",
    "http://127.0.0.1:5176",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5173",
    "*",
]


app.add_middleware(
    CORSMiddleware,

    # Allow all origins so local, LAN (e.g., 192.168.151.242), and mobile browsers can access API
    allow_origins=["*"],

    # JWT is stored in localStorage.
    # We are NOT using browser cookies.
    allow_credentials=False,

    # Allow all HTTP methods
    allow_methods=["*"],

    # Allow all request headers
    allow_headers=["*"],
)


# ============================================================
# REST API ROUTES
# ============================================================

app.include_router(api_router)


# ============================================================
# WEBSOCKET ROUTES
# ============================================================

# Driver/dashboard WebSocket
app.include_router(driver_ws_router)

# Owner/dashboard WebSocket
app.include_router(owner_ws_router)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""

    return {
        "status": "healthy",
        "service": "SmartDrive Guardian Backend",
        "version": "2.0.0",
        "ai_connection": (
            ai_connection_service
            .get_state()
            .status
        ),
    }


# ============================================================
# CORS / DEVELOPMENT TEST ENDPOINT
# ============================================================
#
# This endpoint is useful for confirming that the frontend
# can communicate with FastAPI.
#
# Open from:
#
#   http://localhost:5176
#
# and call:
#
#   GET http://localhost:8000/api-test
#
# ============================================================

@app.get("/api-test")
async def api_test():
    """Simple API connectivity test."""

    return {
        "success": True,
        "message": "SmartDrive Guardian Backend is reachable",
        "backend": "http://localhost:8000",
    }