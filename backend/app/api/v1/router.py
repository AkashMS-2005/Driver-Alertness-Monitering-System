"""API router — aggregates all v1 route modules."""

from fastapi import APIRouter
from app.api.v1 import (
    owner_routes,
    vehicle_routes,
    trip_routes,
    safety_routes,
    assistance_routes,
    emergency_routes,
    ai_connection_routes,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(owner_routes.router, prefix="/owners", tags=["Owners"])
api_router.include_router(vehicle_routes.router, prefix="/vehicles", tags=["Vehicles"])
api_router.include_router(trip_routes.router, prefix="/trips", tags=["Trips"])
api_router.include_router(safety_routes.router, prefix="/safety", tags=["Safety"])
api_router.include_router(
    assistance_routes.router, prefix="/assistance", tags=["Highway Assistance"]
)
api_router.include_router(
    emergency_routes.router, prefix="/emergency", tags=["Emergency"]
)
api_router.include_router(ai_connection_routes.router, prefix="/ai", tags=["AI Connection"])
