"""Head Pose Estimation — 3D orientation from MediaPipe face landmarks.

Estimates PITCH, YAW, ROLL using a PnP-style approach:
  2D facial landmarks → solvePnP → rotation vector → Euler angles

Architecture:
  2D facial landmarks
        ↓
  3D reference face points (canonical model)
        ↓
  Camera parameters (estimated from frame size)
        ↓
  cv2.solvePnP
        ↓
  Rotation vector → Rotation matrix (Rodrigues)
        ↓
  Euler angles (Pitch / Yaw / Roll)
        ↓
  Head deviation detection (relative to neutral forward pose)
        ↓
  Distraction / fatigue signals

These are INTERNAL signals — never sent raw to the frontend.
The frontend receives only the high-level driver_status and alert_message.

Key landmarks used (MediaPipe FaceMesh 478-point model):
  Nose tip:         1
  Chin:             152
  Left eye corner:  263
  Right eye corner: 33
  Left mouth:       287
  Right mouth:      57
"""

import numpy as np
import logging
import time

logger = logging.getLogger("smartdrive.ai")

# ---------------------------------------------------------------------------
# 3D Reference Face Model
# ---------------------------------------------------------------------------
# These are canonical 3D coordinates for the key facial landmarks,
# expressed in millimetres relative to the nose tip as origin.
# This is a widely-used generic face model compatible with MediaPipe.
# Reference: Kazemi & Sullivan (2014), OpenCV face model conventions.

REFERENCE_3D_POINTS = np.array([
    [0.0,    0.0,    0.0],      # Nose tip (landmark 1) — origin
    [0.0,  -330.0, -65.0],      # Chin (landmark 152)
    [-225.0,  170.0, -135.0],   # Left eye outer corner (landmark 263)
    [225.0,   170.0, -135.0],   # Right eye outer corner (landmark 33)
    [-150.0, -150.0, -125.0],   # Left mouth corner (landmark 287)
    [150.0,  -150.0, -125.0],   # Right mouth corner (landmark 57)
], dtype=np.float64)

# Indices of the MediaPipe landmarks used in PnP
_LANDMARK_INDICES = [1, 152, 263, 33, 287, 57]


def _get_2d_points(landmarks, frame_w: int, frame_h: int) -> np.ndarray:
    """Extract 2D pixel coordinates for the 6 PnP landmarks."""
    pts = []
    for idx in _LANDMARK_INDICES:
        lm = landmarks[idx]
        pts.append([lm[0] * frame_w, lm[1] * frame_h])
    return np.array(pts, dtype=np.float64)


def _build_camera_matrix(frame_w: int, frame_h: int) -> np.ndarray:
    """Approximate camera intrinsics from frame dimensions.

    In production, use actual camera calibration values.
    For development, the focal-length approximation (focal ≈ max(W, H))
    gives reasonable results for standard webcams.
    """
    focal_length = max(frame_w, frame_h)
    cx = frame_w / 2.0
    cy = frame_h / 2.0
    return np.array([
        [focal_length, 0,            cx],
        [0,            focal_length, cy],
        [0,            0,            1],
    ], dtype=np.float64)


def estimate_head_pose(
    landmarks,
    frame_w: int,
    frame_h: int,
) -> dict:
    """Estimate head pose from 2D facial landmarks.

    Args:
        landmarks:  List of (x, y, z) tuples from MediaPipe (478 landmarks,
                    normalised [0-1] coordinates).
        frame_w:    Camera frame width in pixels.
        frame_h:    Camera frame height in pixels.

    Returns:
        dict:
            pitch        (float) — head tilt up/down in degrees
                                   positive = nose pointing DOWN (head drop)
            yaw          (float) — head rotation left/right in degrees
                                   positive = rotated RIGHT
            roll         (float) — head tilt left/right in degrees
                                   positive = right shoulder raised
            valid        (bool)  — True if estimation succeeded
            error        (str)   — error message if valid=False
    """
    try:
        image_2d_pts = _get_2d_points(landmarks, frame_w, frame_h)
        camera_matrix = _build_camera_matrix(frame_w, frame_h)
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        success, rot_vec, _ = _solve_pnp(
            REFERENCE_3D_POINTS,
            image_2d_pts,
            camera_matrix,
            dist_coeffs,
        )

        if not success:
            return {"pitch": 0.0, "yaw": 0.0, "roll": 0.0, "valid": False, "error": "solvePnP failed"}

        rot_mat, _ = _rodrigues(rot_vec)
        pitch, yaw, roll = _rotation_matrix_to_euler(rot_mat)

        return {
            "pitch": round(pitch, 2),
            "yaw":   round(yaw, 2),
            "roll":  round(roll, 2),
            "valid": True,
            "error": None,
        }

    except Exception as exc:
        logger.debug(f"Head pose estimation error: {exc}")
        return {"pitch": 0.0, "yaw": 0.0, "roll": 0.0, "valid": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Thin wrappers so we can mock/test without importing cv2 globally
# ---------------------------------------------------------------------------

def _solve_pnp(obj_pts, img_pts, cam_mat, dist):
    """Wrapper around cv2.solvePnP."""
    import cv2
    return cv2.solvePnP(
        obj_pts,
        img_pts,
        cam_mat,
        dist,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )


def _rodrigues(rvec):
    """Wrapper around cv2.Rodrigues."""
    import cv2
    return cv2.Rodrigues(rvec)


def _rotation_matrix_to_euler(R: np.ndarray):
    """Convert a 3×3 rotation matrix to Euler angles (pitch, yaw, roll) in degrees.

    Convention: ZYX / Tait-Bryan (aerospace)
        pitch  = rotation around X (tilt up/down)
        yaw    = rotation around Y (look left/right)
        roll   = rotation around Z (tilt left/right)
    """
    sy = np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6

    if not singular:
        roll  = np.degrees(np.arctan2(R[2, 1], R[2, 2]))
        pitch = np.degrees(np.arctan2(-R[2, 0], sy))
        yaw   = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
    else:
        roll  = np.degrees(np.arctan2(-R[1, 2], R[1, 1]))
        pitch = np.degrees(np.arctan2(-R[2, 0], sy))
        yaw   = 0.0

    return pitch, yaw, roll


# ---------------------------------------------------------------------------
# Head Pose Temporal Tracker
# ---------------------------------------------------------------------------

class HeadPoseTracker:
    """Tracks head pose over time with dead-zones, temporal smoothing,
    neutral baseline calibration, and hysteresis.

    Pipeline:
      HEAD POSE -> MOVING AVERAGE SMOOTHING -> BASELINE SUBTRACTION (current - neutral)
      -> DEAD-ZONE FILTERING -> HYSTERESIS CHECK -> TEMPORAL SUSTAINED DURATION
      -> DECISION ("NORMAL" or "DISTRACTED")

    Handles:
    - Small head/face movements within deadzone treated as NORMAL.
    - Quick mirror glances (0.5s - 1.2s) treated as NORMAL.
    - Sustained head deviation beyond enter_threshold for >= deviation_min_duration
      transitions to DISTRACTED.
    - Hysteresis: requires staying below exit_threshold (enter > exit) for exit_duration
      before returning to NORMAL.
    """

    def __init__(
        self,
        # Dead-zones (tolerance around neutral pose)
        yaw_deadzone: float = 12.0,
        pitch_deadzone: float = 10.0,
        roll_deadzone: float = 10.0,

        # Hysteresis thresholds (degrees)
        enter_yaw_threshold: float = 30.0,
        exit_yaw_threshold: float = 18.0,
        enter_pitch_threshold: float = 22.0,
        exit_pitch_threshold: float = 14.0,
        enter_roll_threshold: float = 22.0,
        exit_roll_threshold: float = 14.0,

        # Temporal durations (seconds)
        deviation_min_duration: float = 2.0,
        exit_duration: float = 0.8,

        # Smoothing & Calibration
        smoothing_window_frames: int = 8,
        calibration_frames: int = 30,
        **kwargs,
    ):
        # Support legacy argument names if passed
        self.yaw_deadzone = float(kwargs.get("HEAD_POSE_YAW_DEADZONE", yaw_deadzone))
        self.pitch_deadzone = float(kwargs.get("HEAD_POSE_PITCH_DEADZONE", pitch_deadzone))
        self.roll_deadzone = float(kwargs.get("HEAD_POSE_ROLL_DEADZONE", roll_deadzone))

        self.enter_yaw = float(kwargs.get("yaw_threshold", enter_yaw_threshold))
        self.exit_yaw = float(exit_yaw_threshold)
        self.enter_pitch = float(kwargs.get("pitch_threshold", enter_pitch_threshold))
        self.exit_pitch = float(exit_pitch_threshold)
        self.enter_roll = float(kwargs.get("roll_threshold", enter_roll_threshold))
        self.exit_roll = float(exit_roll_threshold)

        self.deviation_duration = float(kwargs.get("deviation_duration", deviation_min_duration))
        self.exit_duration = float(exit_duration)

        self.smoothing_frames = max(1, int(smoothing_window_frames))
        self.calibration_target = max(5, int(calibration_frames))

        # Smoothing window buffers
        self._pitch_buf: list[float] = []
        self._yaw_buf: list[float] = []
        self._roll_buf: list[float] = []

        # Neutral baseline pose
        self._calib_count: int = 0
        self._neutral_pitch: float = 0.0
        self._neutral_yaw: float = 0.0
        self._neutral_roll: float = 0.0
        self._is_calibrated: bool = False

        # State machine
        self._deviation_start: float | None = None
        self._exit_start: float | None = None
        self._is_distracted: bool = False
        self._is_deviated: bool = False

    def update(
        self,
        pitch: float,
        yaw: float,
        roll: float,
        valid: bool,
    ) -> dict:
        """Process one frame's head pose estimate.

        Args:
            pitch, yaw, roll: Head Euler angles in degrees from solvePnP.
            valid: False if solvePnP or face landmarks failed.

        Returns:
            dict containing:
                head_state           (str)   - "NORMAL" or "DISTRACTED"
                sustained_deviation  (bool)  - True if confirmed DISTRACTED
                head_deviated        (bool)  - True if currently exceeding deadzone/threshold
                deviation_duration   (float) - Continuous seconds beyond enter threshold
                head_pose_valid      (bool)  - Reliable estimation flag
                pitch, yaw, roll     (float) - Smoothed deviations relative to neutral
        """
        if not valid:
            return {
                "head_deviated": self._is_deviated,
                "sustained_deviation": self._is_distracted,
                "deviation_duration": 0.0,
                "head_pose_valid": False,
                "head_state": "DISTRACTED" if self._is_distracted else "NORMAL",
                "pitch": 0.0,
                "yaw": 0.0,
                "roll": 0.0,
            }

        now = time.monotonic()

        # 1. Temporal Smoothing (moving average buffer)
        self._pitch_buf.append(pitch)
        self._yaw_buf.append(yaw)
        self._roll_buf.append(roll)
        if len(self._pitch_buf) > self.smoothing_frames:
            self._pitch_buf.pop(0)
            self._yaw_buf.pop(0)
            self._roll_buf.pop(0)

        smooth_pitch = sum(self._pitch_buf) / len(self._pitch_buf)
        smooth_yaw = sum(self._yaw_buf) / len(self._yaw_buf)
        smooth_roll = sum(self._roll_buf) / len(self._roll_buf)

        # 2. Neutral Driving Pose Calibration / Baseline
        if not self._is_calibrated:
            self._calib_count += 1
            alpha = 1.0 / self._calib_count
            self._neutral_pitch = (1.0 - alpha) * self._neutral_pitch + alpha * smooth_pitch
            self._neutral_yaw = (1.0 - alpha) * self._neutral_yaw + alpha * smooth_yaw
            self._neutral_roll = (1.0 - alpha) * self._neutral_roll + alpha * smooth_roll

            if self._calib_count >= self.calibration_target:
                self._is_calibrated = True
                logger.info(
                    f"Head Pose Baseline Calibrated: Pitch={self._neutral_pitch:.1f}°, "
                    f"Yaw={self._neutral_yaw:.1f}°, Roll={self._neutral_roll:.1f}°"
                )
        elif not self._is_distracted:
            # Slow running adaptive update (0.5% weight) to absorb gradual seat posture shifts
            self._neutral_pitch = 0.995 * self._neutral_pitch + 0.005 * smooth_pitch
            self._neutral_yaw = 0.995 * self._neutral_yaw + 0.005 * smooth_yaw
            self._neutral_roll = 0.995 * self._neutral_roll + 0.005 * smooth_roll

        # 3. Angle Deviation relative to neutral baseline
        delta_pitch = smooth_pitch - self._neutral_pitch
        delta_yaw = smooth_yaw - self._neutral_yaw
        delta_roll = smooth_roll - self._neutral_roll

        # 4. Dead-Zone Filtering
        eff_pitch = 0.0 if abs(delta_pitch) <= self.pitch_deadzone else delta_pitch
        eff_yaw = 0.0 if abs(delta_yaw) <= self.yaw_deadzone else delta_yaw
        eff_roll = 0.0 if abs(delta_roll) <= self.roll_deadzone else delta_roll

        # 5. Hysteresis & Temporal Duration State Machine
        if not self._is_distracted:
            # Check enter threshold
            exceeded_enter = (
                abs(eff_yaw) > self.enter_yaw
                or abs(eff_pitch) > self.enter_pitch
                or abs(eff_roll) > self.enter_roll
            )

            if exceeded_enter:
                if self._deviation_start is None:
                    self._deviation_start = now
                elapsed = now - self._deviation_start

                if elapsed >= self.deviation_duration:
                    self._is_distracted = True
                    self._exit_start = None
                    logger.warning(
                        f"[HeadPose] Sustained head distraction confirmed ({elapsed:.1f}s) — "
                        f"Y={eff_yaw:.1f}° P={eff_pitch:.1f}° R={eff_roll:.1f}°"
                    )
            else:
                self._deviation_start = None
                elapsed = 0.0

            self._is_deviated = exceeded_enter

        else:
            # Currently in DISTRACTED state — check exit threshold (must be below exit for exit_duration)
            below_exit = (
                abs(eff_yaw) <= self.exit_yaw
                and abs(eff_pitch) <= self.exit_pitch
                and abs(eff_roll) <= self.exit_roll
            )

            if below_exit:
                if self._exit_start is None:
                    self._exit_start = now
                if now - self._exit_start >= self.exit_duration:
                    self._is_distracted = False
                    self._deviation_start = None
                    self._exit_start = None
                    self._is_deviated = False
                    logger.info("[HeadPose] Driver head pose returned to normal range")
            else:
                self._exit_start = None
                self._is_deviated = True

            elapsed = (now - self._deviation_start) if self._deviation_start else 0.0

        # Consistent binary state for UI (never flickers with temporary DEVIATING status)
        head_state = "DISTRACTED" if self._is_distracted else "NORMAL"

        return {
            "head_deviated": self._is_deviated,
            "sustained_deviation": self._is_distracted,
            "deviation_duration": round(elapsed, 2),
            "head_pose_valid": True,
            "head_state": head_state,
            "pitch": round(delta_pitch, 2),
            "yaw": round(delta_yaw, 2),
            "roll": round(delta_roll, 2),
        }

    def reset(self):
        """Reset tracker state on new trip."""
        self._deviation_start = None
        self._exit_start = None
        self._is_distracted = False
        self._is_deviated = False
        self._pitch_buf.clear()
        self._yaw_buf.clear()
        self._roll_buf.clear()
        self._calib_count = 0
        self._is_calibrated = False
