"""SmartDrive Guardian AI Service — Main Entry Point (Laptop 1).

Phase 3: Drowsiness detection pipeline + WebSocket server.
  Camera → Face Landmarks → EAR/MAR → Temporal → Drowsiness State → WebSocket

Changes in this version
───────────────────────
- Yawn detection now uses YawnDetector (temporal state machine) instead of
  single-frame MAR threshold. This eliminates most false-yawn detections from
  normal talking.
- Every 3rd frame is JPEG-encoded and sent as base64 in the WebSocket payload
  so the dashboard can display the live camera feed without a separate stream.
"""

import cv2
import time
import base64
import logging
import sys
import yaml
import numpy as np
from datetime import datetime, timezone

from src.config.settings import settings
from src.capture.camera_stream import CameraStream
from src.perception.landmark_detector import LandmarkDetector
from src.perception.eye_state import get_eye_state, LEFT_EYE_INDICES, RIGHT_EYE_INDICES
from src.perception.mouth_state import get_mouth_state, calculate_mar, YawnDetector
from src.temporal.temporal_analyzer import TemporalAnalyzer
from src.classifiers.drowsiness_classifier import (
    classify_drowsiness,
    STATE_NORMAL,
    STATE_DROWSY,
    STATE_MICROSLEEP,
)
from src.network.ai_ws_server import AIWebSocketServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("smartdrive.ai")

# ---- Alarm ----
_alarm_active = False
_last_alarm_time = 0.0
ALARM_COOLDOWN = 1.0  # seconds between beeps


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


def load_yawn_config() -> dict:
    """Load yawn detection parameters from thresholds.yaml.

    Returns a dict with keys: mar_threshold, yawn_min_duration, yawn_reset_duration.
    Falls back to safe defaults if the file cannot be read.
    """
    defaults = {
        "mar_threshold": 0.60,
        "yawn_min_duration": 1.0,
        "yawn_reset_duration": 0.3,
    }
    try:
        with open(settings.THRESHOLDS_PATH) as f:
            thresholds = yaml.safe_load(f) or {}
        mouth_cfg = thresholds.get("mouth_state", {})
        return {
            "mar_threshold": float(mouth_cfg.get("mar_threshold", defaults["mar_threshold"])),
            "yawn_min_duration": float(mouth_cfg.get("yawn_min_duration", defaults["yawn_min_duration"])),
            "yawn_reset_duration": float(mouth_cfg.get("yawn_reset_duration", defaults["yawn_reset_duration"])),
        }
    except Exception as e:
        logger.warning(f"Could not load thresholds.yaml: {e}. Using defaults.")
        return defaults


def encode_frame_b64(frame: np.ndarray, width: int = 320, quality: int = 50) -> str:
    """Resize and encode a frame as a base64 JPEG string for WebSocket streaming.

    Args:
        frame:   BGR frame from OpenCV
        width:   target width (aspect ratio preserved)
        quality: JPEG compression quality (0–100)

    Returns:
        str: base64-encoded JPEG string, or "" on failure
    """
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


def draw_debug_info(frame, eye_data, mouth_data, temporal_data, drowsiness_data, landmarks, fps, client_count=0, yawn_state="MOUTH_NORMAL"):
    """Draw debugging information on the OpenCV frame (local debug window only)."""
    h, w = frame.shape[:2]
    state = drowsiness_data["state"]

    if state == STATE_MICROSLEEP:
        color = (0, 0, 255)
        border_width = 8
    elif state == STATE_DROWSY:
        color = (0, 165, 255)
        border_width = 5
    else:
        color = (0, 200, 0)
        border_width = 2

    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), color, border_width)
    label = f"STATE: {state}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, label, (10, 35), font, 1.0, color, 2)

    ear_text = f"EAR: {eye_data['ear']:.3f}  {'CLOSED' if eye_data['eye_closed'] else 'OPEN'}"
    cv2.putText(frame, ear_text, (10, 70), font, 0.6, (255, 255, 255), 1)

    mar_text = f"MAR: {mouth_data['mar']:.3f}  {yawn_state}"
    cv2.putText(frame, mar_text, (10, 95), font, 0.6, (255, 255, 255), 1)

    dur_text = f"Closed: {temporal_data['closed_duration']:.1f}s  PERCLOS: {temporal_data['perclos']:.1f}%"
    cv2.putText(frame, dur_text, (10, 120), font, 0.6, (255, 255, 255), 1)

    yawn_text = f"Yawns: {temporal_data['yawn_count']}"
    cv2.putText(frame, yawn_text, (10, 145), font, 0.6, (255, 255, 255), 1)

    ws_text = f"WS Clients: {client_count}"
    cv2.putText(frame, ws_text, (10, 170), font, 0.5, (200, 200, 200), 1)

    fps_text = f"FPS: {fps:.0f}"
    cv2.putText(frame, fps_text, (w - 110, 30), font, 0.6, (200, 200, 200), 1)

    alert = drowsiness_data.get("alert_message")
    if alert:
        cv2.rectangle(frame, (0, h - 50), (w, h), color, -1)
        cv2.putText(frame, alert, (10, h - 15), font, 0.6, (255, 255, 255), 2)

    if landmarks:
        for idx in LEFT_EYE_INDICES + RIGHT_EYE_INDICES:
            x = int(landmarks[idx][0] * w)
            y = int(landmarks[idx][1] * h)
            cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)


def build_result(eye_data, mouth_data, temporal_data, drowsiness_data, frame_b64: str = ""):
    """Build the detection result object sent over WebSocket to the backend.

    frame_b64 is a base64 JPEG string included every N frames for dashboard
    live video display. Empty string on frames where we skip encoding.
    """
    result = {
        "type": "drowsiness",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": drowsiness_data["state"],
        "ear": round(float(eye_data.get("ear", 0.0)), 3),
        "eye_closed": bool(eye_data.get("eye_closed", False)),
        "closed_duration": round(float(temporal_data.get("closed_duration", 0.0)), 2),
        "perclos": round(float(temporal_data.get("perclos", 0.0)), 1),
        "mar": round(float(mouth_data.get("mar", 0.0)), 3),
        "yawning": bool(mouth_data.get("yawning", False)),
        "alert_message": drowsiness_data.get("alert_message"),
    }
    if frame_b64:
        result["frame_b64"] = frame_b64
    return result


def run_pipeline():
    """Run the drowsiness detection pipeline and WebSocket server."""
    logger.info("=" * 60)
    logger.info("SmartDrive Guardian AI Service — Phase 3")
    logger.info("Drowsiness Detection Pipeline & WebSocket Server")
    logger.info("=" * 60)

    # Load yawn configuration from thresholds.yaml
    yawn_cfg = load_yawn_config()
    logger.info(
        f"Yawn detector config: MAR_THRESHOLD={yawn_cfg['mar_threshold']} | "
        f"MIN_DURATION={yawn_cfg['yawn_min_duration']}s | "
        f"RESET_DURATION={yawn_cfg['yawn_reset_duration']}s"
    )

    # Start WebSocket Server for Backend
    ws_server = AIWebSocketServer(
        host=settings.AI_SERVER_HOST,
        port=settings.AI_SERVER_PORT,
    )
    ws_server.start()

    # Initialize camera
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

    # Initialize face landmark detector
    detector = LandmarkDetector()
    if not detector.initialize():
        logger.error("Cannot initialize face detector. Exiting.")
        camera.release()
        ws_server.stop()
        return

    # Initialize temporal analyzer (eye closure / PERCLOS / yawn counting)
    temporal = TemporalAnalyzer()

    # Initialize temporal yawn detector (state machine — replaces instant MAR check)
    yawn_detector = YawnDetector(
        mar_threshold=yawn_cfg["mar_threshold"],
        min_duration=yawn_cfg["yawn_min_duration"],
        reset_duration=yawn_cfg["yawn_reset_duration"],
    )

    logger.info(f"AI Service ready. Streaming on ws://{settings.AI_SERVER_HOST}:{settings.AI_SERVER_PORT}/ws/ai")
    logger.info("Press 'q' in the camera window to quit.")
    logger.info("-" * 60)

    no_face_eye = {"left_ear": 0.0, "right_ear": 0.0, "ear": 0.0, "eye_closed": False}
    no_face_mouth = {"mar": 0.0, "yawning": False}
    no_face_drowsiness = {"state": STATE_NORMAL, "alert_message": None}

    frame_count = 0
    fps = 0.0
    fps_start = time.time()

    # Stream every 3rd frame as JPEG for dashboard live video (≈10fps at 30fps camera)
    STREAM_EVERY_N_FRAMES = 3

    try:
        while True:
            frame = camera.read_frame()
            if frame is None:
                logger.warning("Failed to read frame")
                continue

            frame_count += 1
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            landmarks = detector.detect(rgb_frame)

            if landmarks is not None:
                # Eye state
                eye_data = get_eye_state(landmarks)

                # MAR calculation
                mouth_data = get_mouth_state(landmarks)  # returns {mar, yawning (legacy)}
                mar_value = mouth_data["mar"]

                # Temporal yawn detection — overrides the instant MAR threshold check
                yawn_result = yawn_detector.update(mar_value)
                mouth_data["yawning"] = yawn_result["yawning"]
                mouth_data["mouth_state"] = yawn_result["mouth_state"]

                # Update temporal analyzer (eye closure + yawn counting)
                temporal.update(
                    eye_closed=eye_data["eye_closed"],
                    yawning=yawn_result["yawning"],
                )
                temporal_data = temporal.get_state()

                # Classify drowsiness (eye-based — yawning is supporting metric only)
                drowsiness_data = classify_drowsiness(
                    eye_closed=eye_data["eye_closed"],
                    closed_duration=temporal_data["closed_duration"],
                    perclos=temporal_data["perclos"],
                    yawning=yawn_result["yawning"],
                )

                trigger_alarm(drowsiness_data["state"])

                # Encode frame for dashboard live video every N frames
                frame_b64 = ""
                if frame_count % STREAM_EVERY_N_FRAMES == 0:
                    frame_b64 = encode_frame_b64(frame, width=320, quality=50)

                result = build_result(eye_data, mouth_data, temporal_data, drowsiness_data, frame_b64)
                ws_server.broadcast_sync(result)

                if drowsiness_data["state"] != STATE_NORMAL:
                    logger.warning(
                        f"State: {drowsiness_data['state']} | "
                        f"EAR: {eye_data['ear']:.3f} | "
                        f"Closed: {temporal_data['closed_duration']:.1f}s | "
                        f"PERCLOS: {temporal_data['perclos']:.1f}% | "
                        f"Yawn: {yawn_result['mouth_state']}"
                    )

            else:
                # No face detected
                eye_data = no_face_eye
                mouth_data = no_face_mouth
                temporal_data = temporal.get_state()
                drowsiness_data = no_face_drowsiness
                trigger_alarm(STATE_NORMAL)

                frame_b64 = ""
                if frame_count % STREAM_EVERY_N_FRAMES == 0:
                    frame_b64 = encode_frame_b64(frame, width=320, quality=50)

                result = build_result(eye_data, mouth_data, temporal_data, drowsiness_data, frame_b64)
                ws_server.broadcast_sync(result)

            # FPS calculation
            elapsed = time.time() - fps_start
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count = 0
                fps_start = time.time()

            yawn_state = mouth_data.get("mouth_state", yawn_detector.MOUTH_NORMAL)
            draw_debug_info(
                frame, eye_data, mouth_data, temporal_data,
                drowsiness_data, landmarks, fps,
                client_count=ws_server.client_count,
                yawn_state=yawn_state,
            )

            if landmarks is None:
                h, w = frame.shape[:2]
                cv2.putText(
                    frame, "NO FACE DETECTED", (w // 2 - 160, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2
                )

            cv2.imshow("SmartDrive Guardian - Drowsiness Detection", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
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


if __name__ == "__main__":
    run_pipeline()
