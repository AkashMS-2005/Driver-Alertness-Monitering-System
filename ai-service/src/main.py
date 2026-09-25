"""SmartDrive Guardian AI Service — Main Entry Point.

Multi-Modal Driver Alertness Monitoring System (DAMS)
Based on: Review paper concepts — EAR, MAR, PERCLOS, 3D Head Pose,
          Temporal Analysis, Multi-Modal Fusion, Unified Risk Score.

Pipeline:
    Camera
        ↓
    Frame Preprocessing
        ↓
    Face Landmark Detection (MediaPipe)
        ↓
    Facial Landmarks
        ├── EAR → Eye State → Eye Closure Duration → PERCLOS
        ├── MAR → Mouth Open Duration → Yawning Event
        └── 3D Head Pose → Pitch / Yaw / Roll → Head Deviation
        ↓
    Temporal Sliding Window (per-channel)
        ↓
    Normalization
        ↓
    Multi-Modal Fusion
        ↓
    Unified Driver Alertness / Risk Score
        ↓
    Alert Level
        ↓
    Driver State (AWAKE / DROWSY / SLEEPING)
        ↓
    WebSocket → FastAPI Backend → Owner Dashboard

Local camera window displays:
    - Face landmark dots (eye region)
    - Driver status
    - Alertness score
    - Drowsiness % (PERCLOS)
    - Active alert message

Internal debug values (EAR, MAR, PERCLOS, head angles, fused risk)
are logged to the terminal but NOT displayed on the camera window.
"""

import asyncio
import logging
import sys
import time
import base64

from datetime import datetime, timezone

import cv2
import numpy as np
import yaml

from src.config.settings import settings
from src.capture.camera_stream import CameraStream

from src.perception.landmark_detector import LandmarkDetector

from src.perception.eye_state import (
    get_eye_state,
    LEFT_EYE_INDICES,
    RIGHT_EYE_INDICES,
)

from src.perception.mouth_state import (
    get_mouth_state,
    YawnDetector,
)

from src.perception.head_pose import (
    estimate_head_pose,
    HeadPoseTracker,
)

from src.temporal.temporal_analyzer import TemporalAnalyzer
from src.temporal.sliding_window import TemporalFeatureBuffer

from src.fusion.multimodal_fusion import MultiModalFusion

from src.classifiers.drowsiness_classifier import (
    STATE_NORMAL,
    STATE_DROWSY,
    STATE_MICROSLEEP,
)

from src.network.ai_ws_server import AIWebSocketServer


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger("smartdrive.ai")


# ============================================================
# CONFIGURATION LOADER
# ============================================================

def load_config() -> dict:
    """Load all parameters from thresholds.yaml."""

    defaults = {
        "ear_threshold": 0.20,
        "drowsy_time": 1.5,
        "microsleep_time": 3.0,
        "perclos_window_seconds": 60,
        "perclos_warning": 30.0,
        "mar_threshold": 0.80,
        "yawn_min_duration": 2.0,
        "yawn_reset_duration": 0.3,
        "pitch_threshold": 20.0,
        "yaw_threshold": 30.0,
        "roll_threshold": 20.0,
        "head_deviation_duration": 2.0,
        "temporal_window_seconds": 2.0,
        "eye_weight": 0.45,
        "yawn_weight": 0.25,
        "head_pose_weight": 0.20,
        "temporal_weight": 0.10,
        "normal_max": 0.25,
        "mild_max": 0.45,
        "moderate_max": 0.65,
    }

    try:
        with open(settings.THRESHOLDS_PATH) as f:
            cfg = yaml.safe_load(f) or {}

        eye_cfg   = cfg.get("eye_state", {})
        dr_cfg    = cfg.get("drowsiness", {})
        mo_cfg    = cfg.get("mouth_state", {})
        hp_cfg    = cfg.get("head_pose", {})
        tm_cfg    = cfg.get("temporal", {})
        fu_cfg    = cfg.get("fusion", {})
        al_cfg    = cfg.get("alert_levels", {})

        return {
            "ear_threshold":         float(eye_cfg.get("ear_threshold", defaults["ear_threshold"])),
            "drowsy_time":           float(dr_cfg.get("drowsy_time", defaults["drowsy_time"])),
            "microsleep_time":       float(dr_cfg.get("microsleep_time", defaults["microsleep_time"])),
            "perclos_window_seconds": float(dr_cfg.get("perclos_window_seconds", defaults["perclos_window_seconds"])),
            "perclos_warning":       float(dr_cfg.get("perclos_warning", defaults["perclos_warning"])),
            "mar_threshold":         float(mo_cfg.get("mar_threshold", defaults["mar_threshold"])),
            "yawn_min_duration":     float(mo_cfg.get("yawn_min_duration", defaults["yawn_min_duration"])),
            "yawn_reset_duration":   float(mo_cfg.get("yawn_reset_duration", defaults["yawn_reset_duration"])),
            "pitch_threshold":       float(hp_cfg.get("pitch_threshold", defaults["pitch_threshold"])),
            "yaw_threshold":         float(hp_cfg.get("yaw_threshold", defaults["yaw_threshold"])),
            "roll_threshold":        float(hp_cfg.get("roll_threshold", defaults["roll_threshold"])),
            "head_deviation_duration": float(hp_cfg.get("deviation_duration", defaults["head_deviation_duration"])),
            "temporal_window_seconds": float(tm_cfg.get("window_seconds", defaults["temporal_window_seconds"])),
            "eye_weight":            float(fu_cfg.get("eye_weight", defaults["eye_weight"])),
            "yawn_weight":           float(fu_cfg.get("yawn_weight", defaults["yawn_weight"])),
            "head_pose_weight":      float(fu_cfg.get("head_pose_weight", defaults["head_pose_weight"])),
            "temporal_weight":       float(fu_cfg.get("temporal_weight", defaults["temporal_weight"])),
            "normal_max":  float((al_cfg.get("normal", {}) or {}).get("max_risk", defaults["normal_max"])),
            "mild_max":    float((al_cfg.get("mild", {}) or {}).get("max_risk", defaults["mild_max"])),
            "moderate_max": float((al_cfg.get("moderate", {}) or {}).get("max_risk", defaults["moderate_max"])),
        }

    except Exception as exc:
        logger.warning(f"Could not load thresholds.yaml: {exc}. Using defaults.")
        return defaults


# ============================================================
# ALARM
# ============================================================

_alarm_active = False
_last_alarm_time = 0.0
ALARM_COOLDOWN = 1.0


def trigger_alarm(state: str):
    """Trigger an audible alarm for DROWSY/MICROSLEEP states."""
    global _alarm_active, _last_alarm_time
    now = time.time()
    if state in (STATE_DROWSY, STATE_MICROSLEEP):
        _alarm_active = True
        if now - _last_alarm_time >= ALARM_COOLDOWN:
            _last_alarm_time = now
            try:
                import winsound
                freq = 2500 if state == STATE_MICROSLEEP else 1800
                winsound.Beep(freq, 200)
            except ImportError:
                print("\a", end="", flush=True)
    else:
        _alarm_active = False


# ============================================================
# DRIVER STATUS HELPERS
# ============================================================

def get_display_status(state: str) -> str:
    """Convert internal AI state to user-facing status string."""
    if state == STATE_MICROSLEEP:
        return "SLEEPING"
    if state == STATE_DROWSY:
        return "DROWSY"
    return "AWAKE"


def get_status_color(state: str):
    """Return OpenCV BGR color for driver status."""
    if state == STATE_MICROSLEEP:
        return (0, 0, 255)     # Red
    if state == STATE_DROWSY:
        return (0, 165, 255)   # Orange
    return (0, 200, 0)         # Green


# ============================================================
# FRAME ENCODING
# ============================================================

def encode_frame_b64(
    frame: np.ndarray,
    width: int = 320,
    quality: int = 50,
) -> str:
    """Resize and encode frame as base64 JPEG."""
    try:
        h, w = frame.shape[:2]
        target_h = int(h * width / w)
        small = cv2.resize(frame, (width, target_h), interpolation=cv2.INTER_LINEAR)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            return base64.b64encode(buf).decode("utf-8")
    except Exception:
        pass
    return ""


# ============================================================
# CAMERA DISPLAY
# ============================================================

def draw_info(
    frame,
    state: str,
    drowsiness_pct: float,
    alertness_score: int,
    alert_message: str | None,
    landmarks=None,
):
    """Draw clean status overlay on the local camera window.

    DISPLAYED:
        - Green landmark dots (eye region)
        - Driver status
        - Alertness score (0–100)
        - Drowsiness percentage (PERCLOS)
        - Alert message (bottom banner)

    NOT displayed:
        - EAR, MAR, PERCLOS raw, head angles, fused risk, FPS, etc.
    """
    h, w = frame.shape[:2]
    status_color = get_status_color(state)
    status_text = get_display_status(state)

    # ── Status border ──────────────────────────────────────────────────
    border_w = 8 if state == STATE_MICROSLEEP else (5 if state == STATE_DROWSY else 3)
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), status_color, border_w)

    # ── Landmark dots (eye region) ─────────────────────────────────────
    if landmarks is not None:
        for idx in LEFT_EYE_INDICES + RIGHT_EYE_INDICES:
            try:
                x = int(landmarks[idx][0] * w)
                y = int(landmarks[idx][1] * h)
                cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)
            except (IndexError, TypeError, ValueError):
                continue

    # ── Driver status text ─────────────────────────────────────────────
    cv2.putText(
        frame,
        f"DRIVER: {status_text}",
        (20, 45),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0,
        status_color, 3, cv2.LINE_AA,
    )

    # ── Alertness score ────────────────────────────────────────────────
    cv2.putText(
        frame,
        f"ALERTNESS: {alertness_score}/100",
        (20, 85),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8,
        (255, 255, 255), 2, cv2.LINE_AA,
    )

    # ── Drowsiness % ──────────────────────────────────────────────────
    cv2.putText(
        frame,
        f"DROWSINESS: {drowsiness_pct:.0f}%",
        (20, 120),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8,
        (220, 220, 220), 2, cv2.LINE_AA,
    )

    # ── Alert banner ───────────────────────────────────────────────────
    if alert_message:
        alert_h = 60
        cv2.rectangle(frame, (0, h - alert_h), (w, h), status_color, -1)
        cv2.putText(
            frame,
            str(alert_message),
            (20, h - 18),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
            (255, 255, 255), 2, cv2.LINE_AA,
        )


# ============================================================
# BUILD WEBSOCKET RESULT
# ============================================================

def build_result(
    state: str,
    driver_status: str,
    drowsiness_pct: float,
    alertness_score: int,
    alert_message: str | None,
    alert_label: str,
    fused_risk: float,
    perclos: float,
    yawning: bool,
    head_state: str,
    microsleep_event: bool,
    frame_b64: str = "",
) -> dict:
    """Build the detection result payload sent to the backend via WebSocket.

    The owner dashboard receives:
        - state, driver_status, drowsiness_percentage
        - alertness_score (0–100)
        - alert_message
        - microsleep_event (bool: True on the frame a new microsleep starts)
        - head_state, yawning (for backend context, not displayed on dashboard)
        - frame_b64 (live camera stream)

    Internal debug values (EAR, MAR, fused_risk, etc.) are available
    in the terminal log but NOT in this payload.
    """
    result = {
        "type": "drowsiness",

        "timestamp": datetime.now(timezone.utc).isoformat(),

        # Internal AI state
        "state": state,

        # User-friendly status
        "driver_status": driver_status,

        # Drowsiness percentage (from PERCLOS — the primary rolling window metric)
        "drowsiness_percentage": round(drowsiness_pct, 1),

        # For backend compatibility (legacy field)
        "perclos": round(perclos, 1),

        # New: unified alertness score
        "alertness_score": alertness_score,

        # Alert level label
        "alert_label": alert_label,

        # Fused risk (0.0–1.0) — backend uses this but dashboard should not display raw
        "fused_risk": round(fused_risk, 3),

        # Alert message
        "alert_message": alert_message,

        # Yawning state (for backend context)
        "yawning": yawning,

        # Head pose state (for backend context)
        "head_state": head_state,

        # Microsleep event: True ONLY on the first frame of a new microsleep event
        "microsleep_event": microsleep_event,
    }

    if frame_b64:
        result["frame_b64"] = frame_b64

    return result


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline():
    """Run the full multi-modal detection pipeline + WebSocket server."""

    logger.info("=" * 60)
    logger.info("SmartDrive Guardian AI Service — Multi-Modal DAMS")
    logger.info("=" * 60)

    # ────────────────────────────────────────────────────────────────
    # LOAD CONFIGURATION
    # ────────────────────────────────────────────────────────────────

    cfg = load_config()

    logger.info(
        f"Config: EAR_TH={cfg['ear_threshold']} | "
        f"DROWSY={cfg['drowsy_time']}s | MICRO={cfg['microsleep_time']}s | "
        f"YAWN_DUR={cfg['yawn_min_duration']}s | "
        f"HEAD_DEV={cfg['head_deviation_duration']}s | "
        f"WIN={cfg['temporal_window_seconds']}s"
    )
    logger.info(
        f"Fusion weights: EYE={cfg['eye_weight']} | "
        f"YAWN={cfg['yawn_weight']} | "
        f"HEAD={cfg['head_pose_weight']} | "
        f"TEMP={cfg['temporal_weight']}"
    )

    # ────────────────────────────────────────────────────────────────
    # WEBSOCKET SERVER
    # ────────────────────────────────────────────────────────────────

    ws_server = AIWebSocketServer(
        host=settings.AI_SERVER_HOST,
        port=settings.AI_SERVER_PORT,
    )
    ws_server.start()

    # ────────────────────────────────────────────────────────────────
    # CAMERA
    # ────────────────────────────────────────────────────────────────

    camera = CameraStream(
        camera_index=settings.CAMERA_INDEX,
        width=settings.CAMERA_WIDTH,
        height=settings.CAMERA_HEIGHT,
        fps=settings.CAMERA_FPS,
    )

    if not camera.open():
        logger.error("Cannot open camera. Exiting.")
        ws_server.stop()
        return

    # ────────────────────────────────────────────────────────────────
    # FACE LANDMARK DETECTOR
    # ────────────────────────────────────────────────────────────────

    detector = LandmarkDetector()
    if not detector.initialize():
        logger.error("Cannot initialize face detector. Exiting.")
        camera.release()
        ws_server.stop()
        return

    # ────────────────────────────────────────────────────────────────
    # PERCEPTION MODULES
    # ────────────────────────────────────────────────────────────────

    # Temporal analyzer (handles eye closure duration + PERCLOS 60-second window)
    temporal = TemporalAnalyzer()

    # Yawn detector (temporal state machine — prevents false yawns from talking)
    yawn_detector = YawnDetector(
        mar_threshold=cfg["mar_threshold"],
        min_duration=cfg["yawn_min_duration"],
        reset_duration=cfg["yawn_reset_duration"],
    )

    # Head pose tracker (temporal distraction detection)
    head_tracker = HeadPoseTracker(
        pitch_threshold=cfg["pitch_threshold"],
        yaw_threshold=cfg["yaw_threshold"],
        roll_threshold=cfg["roll_threshold"],
        deviation_duration=cfg["head_deviation_duration"],
    )

    # ────────────────────────────────────────────────────────────────
    # TEMPORAL FEATURE BUFFER (sliding windows for all channels)
    # ────────────────────────────────────────────────────────────────

    feature_buffer = TemporalFeatureBuffer(
        window_seconds=cfg["temporal_window_seconds"],
    )

    # ────────────────────────────────────────────────────────────────
    # MULTI-MODAL FUSION ENGINE
    # ────────────────────────────────────────────────────────────────

    fusion = MultiModalFusion(
        eye_weight=cfg["eye_weight"],
        yawn_weight=cfg["yawn_weight"],
        head_weight=cfg["head_pose_weight"],
        temporal_weight=cfg["temporal_weight"],
        normal_max=cfg["normal_max"],
        mild_max=cfg["mild_max"],
        moderate_max=cfg["moderate_max"],
        ear_threshold=cfg["ear_threshold"],
        perclos_warning=cfg["perclos_warning"],
        drowsy_time=cfg["drowsy_time"],
        microsleep_time=cfg["microsleep_time"],
        mar_threshold=cfg["mar_threshold"],
        yawn_min_duration=cfg["yawn_min_duration"],
        head_deviation_duration=cfg["head_deviation_duration"],
    )

    logger.info(
        "AI Service ready. "
        f"Streaming on ws://{settings.AI_SERVER_HOST}:{settings.AI_SERVER_PORT}/ws/ai"
    )
    logger.info("Press 'q' in camera window to quit.")
    logger.info("-" * 60)

    # ────────────────────────────────────────────────────────────────
    # MICROSLEEP EVENT TRACKING
    # (separate from backend — AI counts for logging clarity)
    # The backend EmergencyEngine also counts independently from WebSocket.
    # ────────────────────────────────────────────────────────────────
    _prev_state = STATE_NORMAL
    _in_microsleep = False          # True while currently in a microsleep episode
    _microsleep_event_count = 0     # For logging only

    # ────────────────────────────────────────────────────────────────
    # FRAME LOOP STATE
    # ────────────────────────────────────────────────────────────────

    frame_count = 0
    fps = 0.0
    fps_start = time.time()

    # Stream every 3rd frame → approx. 10 FPS to dashboard
    STREAM_EVERY_N_FRAMES = 3

    # Default "no face" values
    no_face_result = build_result(
        state=STATE_NORMAL,
        driver_status="AWAKE",
        drowsiness_pct=0.0,
        alertness_score=100,
        alert_message=None,
        alert_label="NORMAL",
        fused_risk=0.0,
        perclos=0.0,
        yawning=False,
        head_state="UNKNOWN",
        microsleep_event=False,
    )

    try:
        while True:

            # ────────────────────────────────────────────────────────
            # READ FRAME
            # ────────────────────────────────────────────────────────

            frame = camera.read_frame()
            if frame is None:
                logger.warning("Failed to read frame")
                continue

            frame_count += 1
            h_frame, w_frame = frame.shape[:2]

            # ────────────────────────────────────────────────────────
            # BGR → RGB
            # ────────────────────────────────────────────────────────

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # ────────────────────────────────────────────────────────
            # FACE LANDMARK DETECTION
            # ────────────────────────────────────────────────────────

            landmarks = detector.detect(rgb_frame)

            # ── FACE NOT DETECTED ─────────────────────────────────────
            if landmarks is None:
                # Do not update temporal state when face is absent
                # (prevents false "eye open" readings resetting closure timer)
                temporal_data = temporal.get_state()

                frame_b64 = ""
                if frame_count % STREAM_EVERY_N_FRAMES == 0:
                    frame_b64 = encode_frame_b64(frame, width=320, quality=50)

                result = {**no_face_result, "frame_b64": frame_b64}
                ws_server.broadcast_sync(result)

                cv2.putText(
                    frame,
                    "NO FACE DETECTED",
                    (w_frame // 2 - 160, h_frame // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                    (0, 0, 255), 2, cv2.LINE_AA,
                )
                cv2.imshow("SmartDrive Guardian — Multi-Modal DAMS", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            # ═══════════════════════════════════════════════════════════
            # FACE DETECTED — RUN FULL PIPELINE
            # ═══════════════════════════════════════════════════════════

            # ── 1. EYE STATE (EAR) ─────────────────────────────────────
            eye_data = get_eye_state(landmarks)
            ear = eye_data["ear"]
            eye_closed = eye_data["eye_closed"]
            eye_valid = True   # Landmarks present → eyes visible

            # ── 2. TEMPORAL EYE CLOSURE + PERCLOS ──────────────────────
            temporal.update(eye_closed=eye_closed, yawning=False)  # yawn counted below
            temporal_data = temporal.get_state()
            closed_duration = temporal_data["closed_duration"]
            perclos = temporal_data["perclos"]

            # ── 3. MOUTH STATE (MAR + temporal yawn detector) ───────────
            mouth_data = get_mouth_state(landmarks)
            mar = mouth_data["mar"]
            mouth_valid = True

            yawn_result = yawn_detector.update(mar)
            yawning = yawn_result["yawning"]
            yawn_open_duration = yawn_result["open_duration"]
            mouth_state_str = yawn_result["mouth_state"]

            # Update yawn count in temporal analyzer
            temporal.update(eye_closed=eye_closed, yawning=yawning)

            # ── 4. 3D HEAD POSE ─────────────────────────────────────────
            head_pose = estimate_head_pose(landmarks, w_frame, h_frame)
            pitch = head_pose["pitch"]
            yaw_angle = head_pose["yaw"]
            roll = head_pose["roll"]
            head_pose_valid = head_pose["valid"]

            # Head pose temporal tracker
            head_track_result = head_tracker.update(
                pitch=pitch,
                yaw=yaw_angle,
                roll=roll,
                valid=head_pose_valid,
            )
            head_state = head_track_result["head_state"]
            sustained_deviation = head_track_result["sustained_deviation"]
            deviation_duration = head_track_result["deviation_duration"]

            # ── 5. TEMPORAL FEATURE BUFFER (sliding windows) ───────────
            feature_buffer.update(
                ear=ear,
                eye_closed=eye_closed,
                mar=mar,
                yawning=yawning,
                pitch=pitch,
                yaw=yaw_angle,
                roll=roll,
                head_deviated=head_track_result["head_deviated"],
            )

            # ── 6. MULTI-MODAL FUSION ───────────────────────────────────
            fusion_result = fusion.update(
                ear=ear,
                eye_closed=eye_closed,
                closed_duration=closed_duration,
                perclos=perclos,
                eye_valid=eye_valid,
                mar=mar,
                yawning=yawning,
                yawn_open_duration=yawn_open_duration,
                mouth_valid=mouth_valid,
                pitch=pitch,
                yaw=yaw_angle,
                roll=roll,
                head_state=head_state,
                head_pose_valid=head_pose_valid,
                sustained_deviation=sustained_deviation,
                deviation_duration=deviation_duration,
            )

            recommended_state = fusion_result["recommended_state"]
            alertness_score   = fusion_result["alertness_score"]
            alert_level       = fusion_result["alert_level"]
            alert_label       = fusion_result["alert_label"]
            fused_risk        = fusion_result["fused_risk"]
            alert_message     = fusion_result["alert_message"]

            # ── 7. FINAL STATE DECISION ─────────────────────────────────
            # Primary: temporal eye closure (most reliable impairment signal)
            # Secondary: fusion recommendation (multi-modal context)
            state = recommended_state

            # ── 8. MICROSLEEP EVENT TRACKING ───────────────────────────
            # Track state transitions INTO microsleep (not every MICROSLEEP frame)
            microsleep_event_this_frame = False

            if state == STATE_MICROSLEEP and not _in_microsleep:
                # New microsleep event starts
                _in_microsleep = True
                _microsleep_event_count += 1
                microsleep_event_this_frame = True
                logger.warning(
                    f"[AI] MICROSLEEP EVENT #{_microsleep_event_count} DETECTED — "
                    f"closed={closed_duration:.1f}s perclos={perclos:.1f}% "
                    f"fused_risk={fused_risk:.3f}"
                )

            elif state != STATE_MICROSLEEP and _in_microsleep:
                # Driver recovered from microsleep
                _in_microsleep = False
                logger.info(
                    f"[AI] Driver recovered from MICROSLEEP (event #{_microsleep_event_count})"
                )

            # ── 9. ALARM ───────────────────────────────────────────────
            trigger_alarm(state)

            # ── 10. DROWSINESS % for display ───────────────────────────
            # The displayed drowsiness percentage is derived from PERCLOS.
            # This is consistent: PERCLOS directly measures how often eyes are closed.
            drowsiness_pct = max(0.0, min(100.0, perclos))

            # ── 11. TERMINAL LOGGING ────────────────────────────────────
            if state != STATE_NORMAL or fused_risk > 0.15:
                logger.warning(
                    f"[AI] State={state} | "
                    f"Alertness={alertness_score}/100 | "
                    f"Drowsiness={drowsiness_pct:.1f}% | "
                    f"PERCLOS={perclos:.1f}% | "
                    f"Closed={closed_duration:.1f}s | "
                    f"Yawn={yawning} ({mouth_state_str}) | "
                    f"HeadPose={head_state} "
                    f"(P={pitch:.1f}° Y={yaw_angle:.1f}° R={roll:.1f}°) | "
                    f"FusedRisk={fused_risk:.3f} | "
                    f"AlertLevel={alert_label}"
                )

            # ── 12. FRAME FOR DASHBOARD ─────────────────────────────────
            frame_b64 = ""
            if frame_count % STREAM_EVERY_N_FRAMES == 0:
                frame_b64 = encode_frame_b64(frame, width=320, quality=50)

            # ── 13. BUILD AND SEND RESULT ───────────────────────────────
            result = build_result(
                state=state,
                driver_status=get_display_status(state),
                drowsiness_pct=drowsiness_pct,
                alertness_score=alertness_score,
                alert_message=alert_message,
                alert_label=alert_label,
                fused_risk=fused_risk,
                perclos=perclos,
                yawning=yawning,
                head_state=head_state,
                microsleep_event=microsleep_event_this_frame,
                frame_b64=frame_b64,
            )

            ws_server.broadcast_sync(result)

            # ── 14. CAMERA OVERLAY ─────────────────────────────────────
            draw_info(
                frame=frame,
                state=state,
                drowsiness_pct=drowsiness_pct,
                alertness_score=alertness_score,
                alert_message=alert_message,
                landmarks=landmarks,
            )

            # ── 15. SHOW CAMERA WINDOW ─────────────────────────────────
            cv2.imshow("SmartDrive Guardian — Multi-Modal DAMS", frame)

            # ── 16. FPS TRACKING ───────────────────────────────────────
            elapsed = time.time() - fps_start
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count = 0
                fps_start = time.time()

            # ── 17. QUIT ───────────────────────────────────────────────
            if cv2.waitKey(1) & 0xFF == ord("q"):
                logger.info("Quit key pressed")
                break

    except KeyboardInterrupt:
        logger.info("Interrupted by user")

    finally:
        ws_server.stop()
        detector.close()
        camera.release()
        cv2.destroyAllWindows()
        logger.info("Pipeline stopped.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    run_pipeline()