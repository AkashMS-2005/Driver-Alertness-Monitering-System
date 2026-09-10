"""AI connection status route — GET /ai/connection-status."""

from fastapi import APIRouter
from app.schemas.ai_connection import AIConnectionResponse

router = APIRouter()

# This will be populated by the AI client module when it starts
_ai_connection_state = None


def set_ai_connection_state(state):
    """Called by the AI client module to register the connection state object."""
    global _ai_connection_state
    _ai_connection_state = state


@router.get("/connection-status", response_model=AIConnectionResponse)
async def get_ai_connection_status():
    """Get the current AI service connection status.

    Returns CONNECTED/DISCONNECTED/RECONNECTING state plus
    last detection timestamp and seconds since last detection.
    """
    if _ai_connection_state is None:
        return AIConnectionResponse(
            status="DISCONNECTED",
            message="AI client not initialized",
        )
    state_dict = _ai_connection_state.to_dict()
    return AIConnectionResponse(**state_dict)
