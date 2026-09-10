"""Drowsiness classifier — rule-based drowsiness detection.

Determines driver state based on eye closure duration:
  - NORMAL:     eyes open or briefly closed (< 1.5s)
  - DROWSY:     eyes closed continuously for 1.5s–3.0s
  - MICROSLEEP: eyes closed continuously for > 3.0s

Yawning is an additional indicator but does NOT replace eye-closure logic.
"""

from src.temporal.temporal_analyzer import DROWSY_TIME, MICROSLEEP_TIME


# Drowsiness states
STATE_NORMAL = "NORMAL"
STATE_DROWSY = "DROWSY"
STATE_MICROSLEEP = "MICROSLEEP"


def classify_drowsiness(
    eye_closed: bool,
    closed_duration: float,
    perclos: float,
    yawning: bool = False,
) -> dict:
    """Classify the current drowsiness state.

    Args:
        eye_closed: True if eyes are currently closed
        closed_duration: seconds of continuous eye closure
        perclos: PERCLOS percentage (0-100)
        yawning: True if currently yawning

    Returns:
        dict with:
            - state: "NORMAL", "DROWSY", or "MICROSLEEP"
            - alert_message: human-readable message or None
    """
    state = STATE_NORMAL
    alert_message = None

    if eye_closed:
        if closed_duration >= MICROSLEEP_TIME:
            state = STATE_MICROSLEEP
            alert_message = "DANGER: Microsleep detected! Pull over immediately!"
        elif closed_duration >= DROWSY_TIME:
            state = STATE_DROWSY
            alert_message = "Warning: Drowsiness detected. Please take a break."

    # Yawning contributes to fatigue awareness but doesn't override eye logic
    if state == STATE_NORMAL and yawning:
        alert_message = "Yawning detected. Consider taking a break."

    # High PERCLOS is a sign of fatigue even if not currently in a closure event
    if state == STATE_NORMAL and perclos > 30.0 and not yawning:
        alert_message = "Elevated fatigue indicators. Stay alert."

    return {
        "state": state,
        "alert_message": alert_message,
    }
