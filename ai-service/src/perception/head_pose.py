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
    """Tracks head pose over time and detects sustained distraction.

    Handles:
    - Short head movements (mirror glances, adjustments) → no alert
    - Sustained head deviation beyond thresholds → distraction signal
    - Sustained downward pitch (head drop) → fatigue signal

    All thresholds are configurable via thresholds.yaml.
    """

    def __init__(
        self,
        pitch_threshold: float = 20.0,
        yaw_threshold: float = 30.0,
        roll_threshold: float = 20.0,
        deviation_duration: float = 2.0,
    ):
        self.pitch_threshold = pitch_threshold
        self.yaw_threshold = yaw_threshold
        self.roll_threshold = roll_threshold
        self.deviation_duration = deviation_duration

        # Timing
        self._deviation_start: float | None = None
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
            pitch, yaw, roll:  Head Euler angles in degrees.
            valid:  False if head pose estimation failed this frame.

        Returns:
            dict:
                head_deviated        (bool)  — currently outside normal range
                sustained_deviation  (bool)  — deviated for ≥ deviation_duration
                deviation_duration   (float) — seconds of continuous deviation
                head_pose_valid      (bool)  — whether this reading is reliable
                head_state           (str)   — "NORMAL", "DEVIATING", "DISTRACTED"
        """
        if not valid:
            # Invalid reading — do not reset timer, do not advance distraction
            return {
                "head_deviated": self._is_deviated,
                "sustained_deviation": False,
                "deviation_duration": 0.0,
                "head_pose_valid": False,
                "head_state": "UNKNOWN",
            }

        now = time.monotonic()

        deviated = (
            abs(pitch) > self.pitch_threshold
            or abs(yaw) > self.yaw_threshold
            or abs(roll) > self.roll_threshold
        )

        if deviated:
            if self._deviation_start is None:
                self._deviation_start = now
            elapsed = now - self._deviation_start
        else:
            self._deviation_start = None
            elapsed = 0.0

        self._is_deviated = deviated
        sustained = deviated and elapsed >= self.deviation_duration

        if sustained:
            head_state = "DISTRACTED"
        elif deviated:
            head_state = "DEVIATING"
        else:
            head_state = "NORMAL"

        return {
            "head_deviated": deviated,
            "sustained_deviation": sustained,
            "deviation_duration": round(elapsed, 2),
            "head_pose_valid": True,
            "head_state": head_state,
        }

    def reset(self):
        """Reset tracker state (call on new session)."""
        self._deviation_start = None
        self._is_deviated = False
