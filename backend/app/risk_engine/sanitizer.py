"""Sanitizer — ensures no raw CV metrics leak to frontend.

Validates outbound payloads and strips any forbidden fields.
"""

# Fields that MUST NEVER appear in any API/WebSocket payload to dashboards
FORBIDDEN_FIELDS = {
    "ear", "mar", "eye_aspect_ratio", "mouth_aspect_ratio",
    "eye_closure_percentage", "blink_count", "blink_rate",
    "landmark_coordinates", "landmarks", "raw_confidence",
    "raw_score", "model_output", "tensor", "head_pose_raw",
    "pitch", "yaw", "roll",  # raw angles — only human-readable interpretations allowed
}


def sanitize_payload(payload: dict) -> dict:
    """Remove any forbidden raw CV metric fields from a payload."""
    return {k: v for k, v in payload.items() if k.lower() not in FORBIDDEN_FIELDS}


def validate_no_raw_metrics(payload: dict) -> bool:
    """Validate that a payload contains no raw CV metrics. Returns True if clean."""
    for key in payload:
        if key.lower() in FORBIDDEN_FIELDS:
            return False
    return True
