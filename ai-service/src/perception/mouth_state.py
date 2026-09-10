"""Mouth state analysis — MAR calculation and yawn detection.

Uses the Mouth Aspect Ratio (MAR) to detect yawning.
These are internal measurements — never sent to the frontend.
"""

import numpy as np

# MediaPipe FaceMesh landmark indices for mouth
# Upper lip: 13, Lower lip: 14
# Left corner: 78, Right corner: 308
# Upper inner: 82, 312 (left/right upper)
# Lower inner: 87, 317 (left/right lower)
MOUTH_INDICES = {
    "upper": 13,
    "lower": 14,
    "left": 78,
    "right": 308,
    "upper_left": 82,
    "upper_right": 312,
    "lower_left": 87,
    "lower_right": 317,
}

# Threshold
MAR_THRESHOLD = 0.60  # Above this = yawning


def _distance(p1, p2):
    """Euclidean distance between two 2D points."""
    return np.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)


def calculate_mar(landmarks):
    """Calculate the Mouth Aspect Ratio (MAR).

    MAR = (|upper-lower| + |upper_left-lower_left| + |upper_right-lower_right|)
          / (2 * |left-right|)

    Args:
        landmarks: list of (x, y, z) tuples from MediaPipe

    Returns:
        float: MAR value
    """
    upper = landmarks[MOUTH_INDICES["upper"]][:2]
    lower = landmarks[MOUTH_INDICES["lower"]][:2]
    left = landmarks[MOUTH_INDICES["left"]][:2]
    right = landmarks[MOUTH_INDICES["right"]][:2]
    upper_left = landmarks[MOUTH_INDICES["upper_left"]][:2]
    upper_right = landmarks[MOUTH_INDICES["upper_right"]][:2]
    lower_left = landmarks[MOUTH_INDICES["lower_left"]][:2]
    lower_right = landmarks[MOUTH_INDICES["lower_right"]][:2]

    # Vertical distances
    vertical_center = _distance(upper, lower)
    vertical_left = _distance(upper_left, lower_left)
    vertical_right = _distance(upper_right, lower_right)

    # Horizontal distance
    horizontal = _distance(left, right)

    if horizontal == 0:
        return 0.0

    mar = (vertical_center + vertical_left + vertical_right) / (2.0 * horizontal)
    return mar


def get_mouth_state(landmarks):
    """Calculate MAR and determine if the driver is yawning.

    Args:
        landmarks: list of (x, y, z) tuples from MediaPipe

    Returns:
        dict with keys:
            - mar (float): Mouth Aspect Ratio
            - yawning (bool): True if MAR > threshold
    """
    mar = calculate_mar(landmarks)
    yawning = mar > MAR_THRESHOLD

    return {
        "mar": round(mar, 4),
        "yawning": yawning,
    }
