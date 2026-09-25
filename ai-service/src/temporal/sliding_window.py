"""Temporal Sliding Window — short-term feature smoothing and aggregation.

Provides a fixed-duration sliding window for any numerical signal.
Used by the multi-modal fusion engine to smooth rapid fluctuations
and capture temporal behavior patterns.

Design:
  - Each channel (EAR, MAR, pitch, yaw, roll, …) has its own SlidingWindow.
  - The window is time-based (not frame-count-based) so it adapts to variable FPS.
  - Exposes: mean, min, max, std_dev, trend.

Purpose:
  - Reduce false positives from single-frame noise.
  - Capture DURATION of events (e.g., "MAR elevated for X seconds").
  - Detect TREND (improving vs. worsening).

These values are internal to the AI pipeline.
They are NOT sent to the frontend directly.
"""

import time
from collections import deque
from typing import Optional


class SlidingWindow:
    """Fixed-duration sliding window for a single numerical signal.

    Args:
        duration_seconds:  How many seconds of history to retain.
        max_samples:       Soft upper bound on retained samples (prevents
                           unbounded memory growth at very high FPS).
    """

    def __init__(
        self,
        duration_seconds: float = 2.0,
        max_samples: int = 500,
    ):
        self.duration_seconds = duration_seconds
        self.max_samples = max_samples
        # deque of (timestamp, value) pairs
        self._buffer: deque[tuple[float, float]] = deque()

    def add(self, value: float):
        """Add a new sample with the current monotonic timestamp."""
        now = time.monotonic()
        self._buffer.append((now, value))
        self._prune(now)

    def _prune(self, now: float):
        """Remove samples older than the window duration."""
        cutoff = now - self.duration_seconds
        while self._buffer and self._buffer[0][0] < cutoff:
            self._buffer.popleft()
        # Also enforce hard cap
        while len(self._buffer) > self.max_samples:
            self._buffer.popleft()

    # ----------------------------------------------------------------
    # Statistics
    # ----------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._buffer)

    @property
    def values(self) -> list[float]:
        return [v for _, v in self._buffer]

    @property
    def mean(self) -> float:
        """Arithmetic mean of values in window. Returns 0.0 if empty."""
        vals = self.values
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    @property
    def minimum(self) -> float:
        vals = self.values
        return min(vals) if vals else 0.0

    @property
    def maximum(self) -> float:
        vals = self.values
        return max(vals) if vals else 0.0

    @property
    def std_dev(self) -> float:
        """Population standard deviation. Returns 0.0 if < 2 samples."""
        vals = self.values
        n = len(vals)
        if n < 2:
            return 0.0
        mu = sum(vals) / n
        variance = sum((v - mu) ** 2 for v in vals) / n
        return variance ** 0.5

    @property
    def trend(self) -> float:
        """Simple trend: difference between mean of last quarter and first quarter.

        Positive  → signal is increasing over the window.
        Negative  → signal is decreasing.
        Zero      → stable.
        """
        vals = self.values
        n = len(vals)
        if n < 4:
            return 0.0
        quarter = max(1, n // 4)
        first_mean = sum(vals[:quarter]) / quarter
        last_mean = sum(vals[-quarter:]) / quarter
        return round(last_mean - first_mean, 4)

    @property
    def fraction_above(self) -> float:
        """Fraction [0-1] of samples where value > 0 (for boolean signals stored as 0/1)."""
        vals = self.values
        if not vals:
            return 0.0
        return sum(1 for v in vals if v > 0.5) / len(vals)

    def get_stats(self) -> dict:
        """Return all statistics as a dict."""
        return {
            "mean": round(self.mean, 4),
            "min": round(self.minimum, 4),
            "max": round(self.maximum, 4),
            "std_dev": round(self.std_dev, 4),
            "trend": self.trend,
            "count": len(self),
        }

    def clear(self):
        """Clear all samples."""
        self._buffer.clear()


class TemporalFeatureBuffer:
    """Maintains sliding windows for all multi-modal signals.

    Channels:
        ear              — Eye Aspect Ratio (higher = more open)
        eye_closed       — Eye closed state (1.0 / 0.0)
        mar              — Mouth Aspect Ratio
        yawning          — Yawning state (1.0 / 0.0)
        pitch            — Head pitch (degrees)
        yaw              — Head yaw (degrees)
        roll             — Head roll (degrees)
        head_deviated    — Head deviation state (1.0 / 0.0)

    All channels use the same window duration for simplicity.
    The separate 60-second PERCLOS window is maintained in TemporalAnalyzer.
    """

    def __init__(self, window_seconds: float = 2.0):
        self.window_seconds = window_seconds
        self._windows: dict[str, SlidingWindow] = {
            "ear": SlidingWindow(window_seconds),
            "eye_closed": SlidingWindow(window_seconds),
            "mar": SlidingWindow(window_seconds),
            "yawning": SlidingWindow(window_seconds),
            "pitch": SlidingWindow(window_seconds),
            "yaw": SlidingWindow(window_seconds),
            "roll": SlidingWindow(window_seconds),
            "head_deviated": SlidingWindow(window_seconds),
        }

    def update(
        self,
        ear: float = 0.0,
        eye_closed: bool = False,
        mar: float = 0.0,
        yawning: bool = False,
        pitch: float = 0.0,
        yaw: float = 0.0,
        roll: float = 0.0,
        head_deviated: bool = False,
    ):
        """Feed one frame of signals into all windows."""
        self._windows["ear"].add(ear)
        self._windows["eye_closed"].add(1.0 if eye_closed else 0.0)
        self._windows["mar"].add(mar)
        self._windows["yawning"].add(1.0 if yawning else 0.0)
        self._windows["pitch"].add(pitch)
        self._windows["yaw"].add(yaw)
        self._windows["roll"].add(roll)
        self._windows["head_deviated"].add(1.0 if head_deviated else 0.0)

    def get(self, channel: str) -> Optional[SlidingWindow]:
        """Return the SlidingWindow for a named channel."""
        return self._windows.get(channel)

    def get_summary(self) -> dict:
        """Return summary stats for all channels."""
        return {name: win.get_stats() for name, win in self._windows.items()}

    def reset(self):
        """Clear all windows."""
        for win in self._windows.values():
            win.clear()
