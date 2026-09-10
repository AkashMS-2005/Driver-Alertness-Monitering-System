"""Eye state analysis — EAR calculation and eye open/closed detection.

Uses the Eye Aspect Ratio (EAR) formula from Soukupová & Čech (2016).
These are internal measurements — never sent to the frontend.
"""

import numpy as np

# MediaPipe FaceMesh landmark indices for left and right eyes
# Left eye (from the viewer's perspective = person's right eye)
LEFT_EYE_INDICES = [362, 385, 387, 263, 373, 380]
# Right eye (from the viewer's perspective = person's left eye)
RIGHT_EYE_INDICES = [33, 160, 158, 133, 153, 144]

# Thresholds
EAR_THRESHOLD = 0.20      # Below this = eyes closed
BLINK_THRESHOLD = 0.70    # Not used in drowsiness, kept for compatibility


def _distance(p1, p2):
    """Euclidean distance between two 2D points (x, y)."""
    return np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def calculate_ear(landmarks, eye_indices):
    """Calculate the Eye Aspect Ratio (EAR) for one eye.

    EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)

    Args:
        landmarks: list of (x, y, z) tuples from MediaPipe
        eye_indices: 6 landmark indices [p1, p2, p3, p4, p5, p6]

    Returns:
        float: EAR value
    """
    p1 = landmarks[eye_indices[0]][:2]
    p2 = landmarks[eye_indices[1]][:2]
    p3 = landmarks[eye_indices[2]][:2]
    p4 = landmarks[eye_indices[3]][:2]
    p5 = landmarks[eye_indices[4]][:2]
    p6 = landmarks[eye_indices[5]][:2]

    # Vertical distances
    vertical_1 = _distance(p2, p6)
    vertical_2 = _distance(p3, p5)

    # Horizontal distance
    horizontal = _distance(p1, p4)

    if horizontal == 0:
        return 0.0

    ear = (vertical_1 + vertical_2) / (2.0 * horizontal)
    return ear


def get_eye_state(landmarks):
    """Calculate EAR for both eyes and determine open/closed state.

    Args:
        landmarks: list of (x, y, z) tuples from MediaPipe (478 landmarks)

    Returns:
        dict with keys:
            - left_ear (float): Left eye EAR
            - right_ear (float): Right eye EAR
            - ear (float): Average EAR
            - eye_closed (bool): True if average EAR < threshold
    """
    left_ear = calculate_ear(landmarks, LEFT_EYE_INDICES)
    right_ear = calculate_ear(landmarks, RIGHT_EYE_INDICES)
    avg_ear = (left_ear + right_ear) / 2.0

    eye_closed = avg_ear < EAR_THRESHOLD

    return {
        "left_ear": round(left_ear, 4),
        "right_ear": round(right_ear, 4),
        "ear": round(avg_ear, 4),
        "eye_closed": eye_closed,
    }
