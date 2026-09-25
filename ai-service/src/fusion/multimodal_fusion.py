"""Multi-Modal Fusion Engine — Core Research Contribution.

This module is the main research feature of the DAMS project.

Architecture:
    EAR / PERCLOS / eye closure duration
            ↓
    eye_risk  (0.0 – 1.0)
            ↓
    MAR / yawn duration
            ↓
    yawn_risk  (0.0 – 1.0)
            ↓
    head pose / sustained deviation
            ↓
    head_risk  (0.0 – 1.0)
            ↓
    temporal drift (sustained impairment over time)
            ↓
    temporal_drift  (0.0 – 1.0)
            ↓
    Weighted Fusion
    R = w_eye * eye_risk + w_yawn * yawn_risk + w_head * head_risk + w_temporal * temporal_drift
            ↓
    Unified Risk Score  R ∈ [0.0, 1.0]
            ↓
    Alertness Score = 100 × (1 − R)
            ↓
    Alert Level (NORMAL / MILD / MODERATE / CRITICAL)
            ↓
    Recommended Driver State (NORMAL / DROWSY / MICROSLEEP)

Key design decisions:
  - Signals are FUSED, not evaluated independently.
  - Missing/invalid modalities are excluded from weighted average (weights renormalised).
  - No modality alone can drive MICROSLEEP classification — temporal eye closure dominates.
  - Weights and thresholds are configurable (thresholds.yaml).

IMPORTANT:
  These internal risk values are NEVER sent to the frontend in raw form.
  The frontend receives only:
    - driver_status (AWAKE / DROWSY / SLEEPING)
    - drowsiness_percentage
    - alert_message
    - alertness_score (0–100)
"""

import logging

logger = logging.getLogger("smartdrive.ai")

# ---------------------------------------------------------------------------
# Alert level constants
# ---------------------------------------------------------------------------
ALERT_NORMAL   = 0   # Normal alertness
ALERT_MILD     = 1   # Mild inattention / caution
ALERT_MODERATE = 2   # Moderate fatigue / distraction
ALERT_CRITICAL = 3   # Critical / imminent hazard

ALERT_LABELS = {
    ALERT_NORMAL:   "NORMAL",
    ALERT_MILD:     "MILD",
    ALERT_MODERATE: "MODERATE",
    ALERT_CRITICAL: "CRITICAL",
}


# ---------------------------------------------------------------------------
# MultiModalFusion
# ---------------------------------------------------------------------------

class MultiModalFusion:
    """Fuses EAR, PERCLOS, MAR, yawning, and head pose into a unified risk score.

    Instantiate once per session. Call update() each frame with fresh signals.
    """

    def __init__(
        self,
        # Fusion weights (must sum to 1.0)
        eye_weight: float     = 0.45,
        yawn_weight: float    = 0.25,
        head_weight: float    = 0.20,
        temporal_weight: float = 0.10,

        # Alertness score thresholds (fused_risk ranges)
        normal_max: float   = 0.25,
        mild_max: float     = 0.45,
        moderate_max: float = 0.65,
        # anything above moderate_max → CRITICAL

        # EAR / PERCLOS risk parameters
        ear_threshold: float     = 0.20,
        ear_open_baseline: float = 0.35,   # Typical fully-open EAR value
        perclos_warning: float   = 30.0,
        perclos_critical: float  = 70.0,

        # Drowsiness time thresholds
        drowsy_time: float     = 1.5,
        microsleep_time: float = 3.0,

        # MAR / yawn thresholds
        mar_threshold: float    = 0.80,
        yawn_min_duration: float = 2.0,

        # Head pose thresholds
        head_deviation_duration: float = 2.0,
    ):
        # Store weights
        self._weights = {
            "eye":      eye_weight,
            "yawn":     yawn_weight,
            "head":     head_weight,
            "temporal": temporal_weight,
        }

        # Alert thresholds
        self._normal_max   = normal_max
        self._mild_max     = mild_max
        self._moderate_max = moderate_max

        # EAR
        self._ear_threshold    = ear_threshold
        self._ear_open_baseline = ear_open_baseline

        # PERCLOS
        self._perclos_warning  = perclos_warning
        self._perclos_critical = perclos_critical

        # Closure duration
        self._drowsy_time     = drowsy_time
        self._microsleep_time = microsleep_time

        # MAR / yawn
        self._mar_threshold     = mar_threshold
        self._yawn_min_duration = yawn_min_duration

        # Head pose
        self._head_deviation_duration = head_deviation_duration

        # Internal state for temporal drift tracking
        self._last_fused_risks: list[float] = []
        self._max_drift_samples = 60  # number of frames to consider

    # ----------------------------------------------------------------
    # Main interface
    # ----------------------------------------------------------------

    def update(
        self,
        # EAR signals
        ear: float             = 0.35,
        eye_closed: bool       = False,
        closed_duration: float = 0.0,
        perclos: float         = 0.0,
        eye_valid: bool        = True,

        # Mouth signals
        mar: float              = 0.0,
        yawning: bool           = False,
        yawn_open_duration: float = 0.0,
        mouth_valid: bool       = True,

        # Head pose signals
        pitch: float            = 0.0,
        yaw: float              = 0.0,
        roll: float             = 0.0,
        head_state: str         = "NORMAL",
        head_pose_valid: bool   = True,
        sustained_deviation: bool = False,
        deviation_duration: float = 0.0,
    ) -> dict:
        """Process all signals for one frame and return the fusion result.

        Returns:
            dict:
                eye_risk         (float)   Internal — [0, 1]
                yawn_risk        (float)   Internal — [0, 1]
                head_risk        (float)   Internal — [0, 1]
                temporal_drift   (float)   Internal — [0, 1]
                fused_risk       (float)   Unified risk score [0, 1]
                alertness_score  (int)     100 × (1 - fused_risk) → [0, 100]
                alert_level      (int)     0 NORMAL / 1 MILD / 2 MODERATE / 3 CRITICAL
                alert_label      (str)     "NORMAL" / "MILD" / "MODERATE" / "CRITICAL"
                recommended_state (str)    "NORMAL" / "DROWSY" / "MICROSLEEP"
                alert_message    (str)     Human-readable alert message
        """
        # ── 1. Compute per-modality risks ─────────────────────────────────
        eye_risk  = self._compute_eye_risk(ear, eye_closed, closed_duration, perclos) if eye_valid else None
        yawn_risk = self._compute_yawn_risk(mar, yawning, yawn_open_duration) if mouth_valid else None
        head_risk = self._compute_head_risk(head_state, sustained_deviation, deviation_duration) if head_pose_valid else None

        # ── 2. Temporal drift (based on recent fused_risk history) ─────────
        temporal_drift = self._compute_temporal_drift()

        # ── 3. Weighted fusion (skip None modalities) ─────────────────────
        fused_risk = self._fuse(eye_risk, yawn_risk, head_risk, temporal_drift)

        # ── 4. Update drift history ────────────────────────────────────────
        self._last_fused_risks.append(fused_risk)
        if len(self._last_fused_risks) > self._max_drift_samples:
            self._last_fused_risks.pop(0)

        # ── 5. Alertness score & alert level ──────────────────────────────
        alertness_score = max(0, min(100, round(100.0 * (1.0 - fused_risk))))
        alert_level = self._compute_alert_level(fused_risk)
        alert_label = ALERT_LABELS[alert_level]

        # ── 6. Recommended state ──────────────────────────────────────────
        recommended_state, alert_message = self._recommended_state(
            closed_duration, eye_closed, fused_risk, alert_level, yawning, sustained_deviation
        )

        return {
            # Internal feature risks (dev/debug only)
            "eye_risk":        round(eye_risk, 3) if eye_risk is not None else None,
            "yawn_risk":       round(yawn_risk, 3) if yawn_risk is not None else None,
            "head_risk":       round(head_risk, 3) if head_risk is not None else None,
            "temporal_drift":  round(temporal_drift, 3),

            # Unified outputs
            "fused_risk":      round(fused_risk, 3),
            "alertness_score": alertness_score,
            "alert_level":     alert_level,
            "alert_label":     alert_label,
            "recommended_state": recommended_state,
            "alert_message":   alert_message,

            # Validity flags
            "eye_valid":       eye_valid,
            "mouth_valid":     mouth_valid,
            "head_pose_valid": head_pose_valid,
        }

    # ----------------------------------------------------------------
    # Per-modality risk functions
    # ----------------------------------------------------------------

    def _compute_eye_risk(
        self,
        ear: float,
        eye_closed: bool,
        closed_duration: float,
        perclos: float,
    ) -> float:
        """Compute eye-based risk [0, 1].

        Combines:
        - Current EAR (normalised)
        - Eye closure duration
        - PERCLOS (60-second rolling window)
        """
        # EAR risk: 0 when fully open, 1 when fully closed
        ear_range = max(0.001, self._ear_open_baseline - self._ear_threshold)
        ear_normalised = 1.0 - max(0.0, min(1.0, (ear - self._ear_threshold) / ear_range))

        # Closure duration risk
        if closed_duration >= self._microsleep_time:
            duration_risk = 1.0
        elif closed_duration >= self._drowsy_time:
            duration_risk = 0.5 + 0.5 * (
                (closed_duration - self._drowsy_time)
                / (self._microsleep_time - self._drowsy_time)
            )
        else:
            duration_risk = min(0.5, closed_duration / self._drowsy_time * 0.5)

        # PERCLOS risk
        if perclos >= self._perclos_critical:
            perclos_risk = 1.0
        elif perclos >= self._perclos_warning:
            perclos_risk = 0.5 + 0.5 * (
                (perclos - self._perclos_warning)
                / (self._perclos_critical - self._perclos_warning)
            )
        else:
            perclos_risk = perclos / self._perclos_warning * 0.5

        # Weighted combination of EAR components
        # Duration carries the most weight (most direct impairment signal)
        eye_risk = 0.3 * ear_normalised + 0.5 * duration_risk + 0.2 * perclos_risk
        return min(1.0, eye_risk)

    def _compute_yawn_risk(
        self,
        mar: float,
        yawning: bool,
        yawn_open_duration: float,
    ) -> float:
        """Compute yawn-based risk [0, 1].

        A confirmed yawn episode contributes more risk than a high MAR alone.
        Short mouth openings (possible talking) contribute much less.
        """
        # MAR above threshold but NOT yet confirmed yawn
        if mar > self._mar_threshold and not yawning:
            candidate_fraction = min(1.0, yawn_open_duration / self._yawn_min_duration)
            return candidate_fraction * 0.3   # Max 0.3 for unconfirmed candidates

        # Confirmed yawn
        if yawning:
            # Risk scales slightly with duration (longer yawn = deeper fatigue)
            duration_bonus = min(0.3, yawn_open_duration / 10.0)
            return min(1.0, 0.6 + duration_bonus)

        # MAR low — no yawn activity
        return 0.0

    def _compute_head_risk(
        self,
        head_state: str,
        sustained_deviation: bool,
        deviation_duration: float,
    ) -> float:
        """Compute head-pose risk [0, 1].

        NORMAL      → 0.0 (including small movements within deadzone & mirror glances)
        DISTRACTED  → moderate risk only when sustained (never saturates alone)
        """
        if head_state == "NORMAL" or not sustained_deviation:
            return 0.0
        elif head_state == "DISTRACTED":
            base_risk = 0.35
            extra = min(0.15, deviation_duration / 10.0)
            return min(0.50, base_risk + extra)
        return 0.0

    def _compute_temporal_drift(self) -> float:
        """Compute temporal drift [0, 1] based on sustained impairment trend.

        If average risk over the last N frames is elevated, drift increases.
        """
        history = self._last_fused_risks
        if not history:
            return 0.0
        avg = sum(history) / len(history)
        # Amplify if the recent history shows sustained elevated risk
        return min(1.0, avg * 1.5)

    # ----------------------------------------------------------------
    # Fusion
    # ----------------------------------------------------------------

    def _fuse(
        self,
        eye_risk: float | None,
        yawn_risk: float | None,
        head_risk: float | None,
        temporal_drift: float,
    ) -> float:
        """Weighted fusion with dynamic weight normalisation for missing modalities."""
        component_keys = ["eye", "yawn", "head", "temporal"]
        component_vals = [eye_risk, yawn_risk, head_risk, temporal_drift]

        total_weight = 0.0
        weighted_sum = 0.0

        for key, val in zip(component_keys, component_vals):
            if val is None:
                continue   # Skip unavailable modality
            w = self._weights[key]
            total_weight += w
            weighted_sum += w * val

        if total_weight < 0.001:
            return 0.0

        # Renormalise for missing modalities
        return min(1.0, weighted_sum / total_weight)

    # ----------------------------------------------------------------
    # Alert level
    # ----------------------------------------------------------------

    def _compute_alert_level(self, fused_risk: float) -> int:
        if fused_risk <= self._normal_max:
            return ALERT_NORMAL
        elif fused_risk <= self._mild_max:
            return ALERT_MILD
        elif fused_risk <= self._moderate_max:
            return ALERT_MODERATE
        else:
            return ALERT_CRITICAL

    # ----------------------------------------------------------------
    # Recommended state and message
    # ----------------------------------------------------------------

    def _recommended_state(
        self,
        closed_duration: float,
        eye_closed: bool,
        fused_risk: float,
        alert_level: int,
        yawning: bool,
        sustained_deviation: bool,
    ) -> tuple[str, str]:
        """Determine recommended driver state and alert message.

        Strict hierarchy:
        1. Temporal eye closure ≥ MICROSLEEP_TIME → MICROSLEEP (primary trigger)
        2. Temporal eye closure ≥ DROWSY_TIME → DROWSY
        3. CRITICAL alert level with eye closure → MICROSLEEP
        4. MODERATE alert level with fatigue (yawn / eye closure) → DROWSY
        5. Sustained head distraction with eyes open → NORMAL (AWAKE) with caution banner
        6. Otherwise → NORMAL (AWAKE)
        """
        # Primary clinical trigger: eye closure duration
        if eye_closed and closed_duration >= self._microsleep_time:
            return "MICROSLEEP", "DANGER: Microsleep detected! Pull over immediately!"

        if eye_closed and closed_duration >= self._drowsy_time:
            return "DROWSY", "Warning: Drowsiness detected. Please take a break."

        # High risk requires eye impairment evidence to escalate to MICROSLEEP
        if alert_level == ALERT_CRITICAL and (eye_closed or closed_duration >= self._drowsy_time):
            return "MICROSLEEP", "DANGER: Critical alertness failure detected!"

        if alert_level >= ALERT_MODERATE:
            if yawning:
                return "DROWSY", "Warning: Fatigue and yawning detected. Take a break soon."
            if eye_closed or closed_duration >= 0.8:
                return "DROWSY", "Warning: Elevated drowsiness indicators. Consider taking a break."
            if sustained_deviation:
                # Eyes are open; sustained head deviation should not cause false drowsiness
                return "NORMAL", "Warning: Sustained head distraction detected. Focus on the road."
            return "DROWSY", "Warning: Elevated drowsiness indicators. Consider taking a break."

        if alert_level == ALERT_MILD:
            if yawning:
                return "NORMAL", "Yawning detected. Consider taking a break."
            if sustained_deviation:
                return "NORMAL", "Head deviation detected. Stay focused."
            return "NORMAL", None

        # NORMAL -> AWAKE
        return "NORMAL", None

    # ----------------------------------------------------------------
    # Configuration update
    # ----------------------------------------------------------------

    def update_weights(
        self,
        eye_weight: float,
        yawn_weight: float,
        head_weight: float,
        temporal_weight: float,
    ):
        """Update fusion weights (must sum to 1.0).

        Called when thresholds.yaml is reloaded at runtime.
        """
        total = eye_weight + yawn_weight + head_weight + temporal_weight
        if abs(total - 1.0) > 0.01:
            logger.warning(
                f"Fusion weights do not sum to 1.0 (sum={total:.3f}). "
                "Normalising automatically."
            )
            if total > 0:
                eye_weight    /= total
                yawn_weight   /= total
                head_weight   /= total
                temporal_weight /= total

        self._weights = {
            "eye":      eye_weight,
            "yawn":     yawn_weight,
            "head":     head_weight,
            "temporal": temporal_weight,
        }
        logger.info(
            f"Fusion weights updated: eye={eye_weight:.2f} "
            f"yawn={yawn_weight:.2f} head={head_weight:.2f} "
            f"temporal={temporal_weight:.2f}"
        )

    def reset(self):
        """Reset temporal drift history (call on new session)."""
        self._last_fused_risks = []
