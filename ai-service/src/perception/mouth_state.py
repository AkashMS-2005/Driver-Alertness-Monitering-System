"""Mouth state analysis — MAR calculation and temporal yawn detection.

Uses the Mouth Aspect Ratio (MAR) to detect yawning.
These are internal measurements — never sent to the frontend.

Yawn detection design
─────────────────────
The old single-frame approach (yawning = MAR > threshold) caused false positives
when drivers talked, smiled, or laughed — brief mouth movements that cross the
MAR threshold but close again quickly.

The new approach uses a three-state machine inside YawnDetector:

  MOUTH_NORMAL           MAR < mar_threshold
  MOUTH_OPEN_CANDIDATE   MAR ≥ threshold — timer counting
  YAWNING                timer reached yawn_min_duration

This ensures that normal talking (short bursts above threshold) is not
classified as yawning, while a genuine prolonged yawn is correctly detected.

Usage
─────
Instantiate YawnDetector once per session and call update(mar) each frame:

    detector = YawnDetector(mar_threshold=0.60, min_duration=1.0, reset_duration=0.3)
    result = detector.update(mar_value)
    # result["yawning"] is True only after mouth has been open >= min_duration

The legacy get_mouth_state() function is kept for backward compatibility and tests
but is NO LONGER used in the live pipeline (main.py uses YawnDetector instead).
"""

import time
import numpy as np

# MediaPipe FaceMesh landmark indices for mouth
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

    vertical_center = _distance(upper, lower)
    vertical_left = _distance(upper_left, lower_left)
    vertical_right = _distance(upper_right, lower_right)
    horizontal = _distance(left, right)

    if horizontal == 0:
        return 0.0

    return (vertical_center + vertical_left + vertical_right) / (2.0 * horizontal)


def get_mouth_state(landmarks):
    """Calculate MAR and return instant (single-frame) mouth state.

    LEGACY / TEST USE ONLY — the live pipeline uses YawnDetector.update() instead.

    Args:
        landmarks: list of (x, y, z) tuples from MediaPipe

    Returns:
        dict: {"mar": float, "yawning": bool}
              yawning is True if MAR > 0.60 (instant, no temporal filter)
    """
    mar = calculate_mar(landmarks)
    return {
        "mar": round(mar, 4),
        "yawning": mar > 0.80,  # legacy threshold — only used in get_mouth_state
    }


# ─────────────────────────────────────────────────────────────────────────────
# Temporal Yawn Detector — Three-State Machine
# ─────────────────────────────────────────────────────────────────────────────

class YawnDetector:
    """Temporal yawn detector using a three-state machine.

    Prevents false yawn detections from normal talking, smiling, or brief
    mouth movements by requiring the mouth to remain above the MAR threshold
    for a configurable minimum duration.

    States
    ──────
    MOUTH_NORMAL          MAR below threshold  → no yawn activity
    MOUTH_OPEN_CANDIDATE  MAR above threshold  → timer counting (not yet a yawn)
    YAWNING               Timer reached min_duration → confirmed yawn episode

    Transitions
    ───────────
    NORMAL → CANDIDATE    : MAR first crosses above threshold
    CANDIDATE → NORMAL    : MAR drops below threshold before min_duration
    CANDIDATE → YAWNING   : MAR stays above threshold for >= min_duration
    YAWNING → NORMAL      : MAR stays below threshold for >= reset_duration

    Parameters (set in thresholds.yaml → mouth_state section)
    ──────────────────────────────────────────────────────────
    mar_threshold    : float, default 0.60
        MAR value above which the mouth is considered "open enough".
        Increase if talking still triggers yawns.

    min_duration     : float, default 1.0 (seconds)
        How long the mouth must stay above threshold to confirm a yawn.
        Normal talking rarely exceeds 0.3–0.5 s per syllable cluster.
        Genuine yawns typically last 1–4 s.

    reset_duration   : float, default 0.3 (seconds)
        How long the mouth must stay below threshold to end a yawn episode.
        Prevents rapid state flickering at the end of a yawn.
    """

    MOUTH_NORMAL = "MOUTH_NORMAL"
    MOUTH_OPEN_CANDIDATE = "MOUTH_OPEN_CANDIDATE"
    YAWNING = "YAWNING"

    def __init__(
        self,
        mar_threshold: float = 0.60,
        min_duration: float = 1.0,
        reset_duration: float = 0.3,
        time_fn=None,
    ):
        self.mar_threshold = mar_threshold
        self.min_duration = min_duration
        self.reset_duration = reset_duration
        # Injected clock — defaults to time.monotonic.
        # Tests pass a fake clock to control simulated time without sleeping.
        self._now = time_fn if time_fn is not None else time.monotonic

        self._state = self.MOUTH_NORMAL
        self._open_start: float | None = None   # when mouth crossed threshold
        self._close_start: float | None = None  # when mouth dropped below threshold (in YAWNING)

    @property
    def state(self) -> str:
        """Current yawn state machine state."""
        return self._state

    @property
    def is_yawning(self) -> bool:
        """True when currently in a confirmed yawn episode."""
        return self._state == self.YAWNING

    def update(self, mar: float) -> dict:
        """Process one frame's MAR value and update the yawn state machine.

        Call this every frame with the current MAR value.

        Args:
            mar: Mouth Aspect Ratio for the current frame

        Returns:
            dict: {
                "yawning": bool   — True only during a confirmed yawn episode,
                "mouth_state": str — "MOUTH_NORMAL" / "MOUTH_OPEN_CANDIDATE" / "YAWNING",
                "open_duration": float — seconds mouth has been above threshold (0 if normal),
            }
        """
        now = self._now()
        above_threshold = mar > self.mar_threshold

        # ── State transitions ──────────────────────────────────────────────
        if self._state == self.MOUTH_NORMAL:
            if above_threshold:
                # Mouth just crossed threshold — start candidate timer
                self._state = self.MOUTH_OPEN_CANDIDATE
                self._open_start = now
                self._close_start = None

        elif self._state == self.MOUTH_OPEN_CANDIDATE:
            if above_threshold:
                # Mouth still open — check if held long enough
                open_duration = now - (self._open_start or now)
                if open_duration >= self.min_duration:
                    # Promoted to confirmed yawn
                    self._state = self.YAWNING
                    self._close_start = None
            else:
                # Mouth dropped below threshold before qualifying → not a yawn
                self._state = self.MOUTH_NORMAL
                self._open_start = None
                self._close_start = None

        elif self._state == self.YAWNING:
            if above_threshold:
                # Still yawning — clear any pending close timer
                self._close_start = None
            else:
                # Mouth starting to close — start reset timer
                if self._close_start is None:
                    self._close_start = now
                elif now - self._close_start >= self.reset_duration:
                    # Mouth has been closed long enough — yawn episode ended
                    self._state = self.MOUTH_NORMAL
                    self._open_start = None
                    self._close_start = None

        # ── Build result ───────────────────────────────────────────────────
        open_duration = 0.0
        if self._open_start is not None and above_threshold:
            open_duration = now - self._open_start

        return {
            "yawning": self._state == self.YAWNING,
            "mouth_state": self._state,
            "open_duration": round(open_duration, 2),
        }

    def reset(self):
        """Reset the detector to initial state (call on session restart)."""
        self._state = self.MOUTH_NORMAL
        self._open_start = None
        self._close_start = None
