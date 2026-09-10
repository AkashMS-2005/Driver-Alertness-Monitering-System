"""Temporal analysis — tracks eye closure duration and PERCLOS.

Simple, rule-based temporal tracking:
- How long eyes have been continuously closed
- PERCLOS: percentage of frames with eyes closed in a rolling window
"""

import time
from collections import deque


# Rolling window for PERCLOS (last 60 seconds worth of samples)
PERCLOS_WINDOW_SECONDS = 60

# Drowsiness thresholds (seconds of continuous eye closure)
DROWSY_TIME = 1.5       # eyes closed > 1.5s → DROWSY
MICROSLEEP_TIME = 3.0   # eyes closed > 3.0s → MICROSLEEP


class TemporalAnalyzer:
    """Tracks eye closure timing and calculates PERCLOS."""

    def __init__(self):
        # Eye closure tracking
        self._eyes_closed = False
        self._closure_start_time = None
        self._closed_duration = 0.0

        # PERCLOS tracking: stores (timestamp, eye_closed_bool)
        self._frame_history = deque()

        # Yawn tracking
        self._yawn_count = 0
        self._last_yawn_time = 0.0
        self._was_yawning = False

    def update(self, eye_closed: bool, yawning: bool = False):
        """Update temporal state with the latest frame's eye/mouth state.

        Args:
            eye_closed: True if eyes are currently closed
            yawning: True if currently yawning
        """
        now = time.time()

        # --- Eye closure duration ---
        if eye_closed:
            if not self._eyes_closed:
                # Eyes just closed
                self._closure_start_time = now
            self._closed_duration = now - self._closure_start_time
        else:
            # Eyes are open — reset closure tracking
            self._eyes_closed = False
            self._closure_start_time = None
            self._closed_duration = 0.0

        self._eyes_closed = eye_closed

        # --- PERCLOS history ---
        self._frame_history.append((now, eye_closed))

        # Remove entries older than the window
        cutoff = now - PERCLOS_WINDOW_SECONDS
        while self._frame_history and self._frame_history[0][0] < cutoff:
            self._frame_history.popleft()

        # --- Yawn counting ---
        if yawning and not self._was_yawning:
            self._yawn_count += 1
            self._last_yawn_time = now
        self._was_yawning = yawning

    @property
    def closed_duration(self) -> float:
        """Seconds the eyes have been continuously closed (0.0 if open)."""
        return round(self._closed_duration, 2)

    @property
    def perclos(self) -> float:
        """PERCLOS: percentage of frames with eyes closed in the rolling window."""
        if not self._frame_history:
            return 0.0

        closed_count = sum(1 for _, closed in self._frame_history if closed)
        total_count = len(self._frame_history)

        return round((closed_count / total_count) * 100, 1)

    @property
    def yawn_count(self) -> int:
        """Number of yawns detected in the session."""
        return self._yawn_count

    def get_state(self) -> dict:
        """Return the current temporal state."""
        return {
            "closed_duration": self.closed_duration,
            "perclos": self.perclos,
            "yawn_count": self.yawn_count,
        }

    def reset(self):
        """Reset all temporal tracking."""
        self._eyes_closed = False
        self._closure_start_time = None
        self._closed_duration = 0.0
        self._frame_history.clear()
        self._yawn_count = 0
        self._last_yawn_time = 0.0
        self._was_yawning = False
