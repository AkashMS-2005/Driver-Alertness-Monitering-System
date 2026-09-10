"""SmartDrive Guardian AI Service — Main Entry Point (Laptop 1).

Phase 2: Drowsiness detection pipeline.
  Camera → Face Landmarks → EAR/MAR → Temporal → Drowsiness State

Runs the camera and AI pipeline with an OpenCV debug window.
The WebSocket server (Phase 3) is not yet implemented.
"""

import cv2
import time
import logging
import sys
import numpy as np
from datetime import datetime, timezone

from src.config.settings import settings
from src.capture.camera_stream import CameraStream
from src.perception.landmark_detector import LandmarkDetector
from src.perception.eye_state import get_eye_state, LEFT_EYE_INDICES, RIGHT_EYE_INDICES
from src.perception.mouth_state import get_mouth_state
from src.temporal.temporal_analyzer import TemporalAnalyzer
from src.classifiers.drowsiness_classifier import (
    classify_drowsiness,
    STATE_NORMAL,
    STATE_DROWSY,
    STATE_MICROSLEEP,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("smartdrive.ai")

# ---- Alarm ----
# Use system beep for the alarm (cross-platform, no external file needed)
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
                # Windows beep
                import winsound
                freq = 2500 if state == STATE_MICROSLEEP else 1800
                winsound.Beep(freq, 200)
            except ImportError:
                # Linux/Mac — print bell character
                print("\a", end="", flush=True)
    else:
        _alarm_active = False


def draw_debug_info(frame, eye_data, mouth_data, temporal_data, drowsiness_data, landmarks, fps):
    """Draw debugging information on the OpenCV frame.

    Shows EAR, MAR, state, PERCLOS, durations — but only in the debug window.
    None of this is sent to the frontend.
    """
    h, w = frame.shape[:2]
    state = drowsiness_data["state"]

    # Background color based on state
    if state == STATE_MICROSLEEP:
        color = (0, 0, 255)       # Red
        border_width = 8
    elif state == STATE_DROWSY:
        color = (0, 165, 255)     # Orange
        border_width = 5
    else:
        color = (0, 200, 0)       # Green
        border_width = 2

    # Draw border
    cv2.rectangle(frame, (0, 0), (w - 1, h - 1), color, border_width)

    # State label
    label = f"STATE: {state}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, label, (10, 35), font, 1.0, color, 2)

    # EAR info
    ear_text = f"EAR: {eye_data['ear']:.3f}  {'CLOSED' if eye_data['eye_closed'] else 'OPEN'}"
    cv2.putText(frame, ear_text, (10, 70), font, 0.6, (255, 255, 255), 1)

    # MAR info
    mar_text = f"MAR: {mouth_data['mar']:.3f}  {'YAWNING' if mouth_data['yawning'] else ''}"
    cv2.putText(frame, mar_text, (10, 95), font, 0.6, (255, 255, 255), 1)

    # Temporal info
    dur_text = f"Closed: {temporal_data['closed_duration']:.1f}s  PERCLOS: {temporal_data['perclos']:.1f}%"
    cv2.putText(frame, dur_text, (10, 120), font, 0.6, (255, 255, 255), 1)

    # Yawn count
    yawn_text = f"Yawns: {temporal_data['yawn_count']}"
    cv2.putText(frame, yawn_text, (10, 145), font, 0.6, (255, 255, 255), 1)

    # FPS
    fps_text = f"FPS: {fps:.0f}"
    cv2.putText(frame, fps_text, (w - 110, 30), font, 0.6, (200, 200, 200), 1)

    # Alert message
    alert = drowsiness_data.get("alert_message")
    if alert:
        # Draw alert banner at bottom
        cv2.rectangle(frame, (0, h - 50), (w, h), color, -1)
        cv2.putText(frame, alert, (10, h - 15), font, 0.6, (255, 255, 255), 2)

    # Draw eye landmarks
    if landmarks:
        for idx in LEFT_EYE_INDICES + RIGHT_EYE_INDICES:
            x = int(landmarks[idx][0] * w)
            y = int(landmarks[idx][1] * h)
            cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)


def build_result(eye_data, mouth_data, temporal_data, drowsiness_data):
    """Build the current detection result object.

    This is what will be sent over WebSocket in Phase 3.
    """
    return {
        "type": "drowsiness",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": drowsiness_data["state"],
        "ear": eye_data["ear"],
        "eye_closed": eye_data["eye_closed"],
        "closed_duration": temporal_data["closed_duration"],
        "perclos": temporal_data["perclos"],
        "mar": mouth_data["mar"],
        "yawning": mouth_data["yawning"],
        "alert_message": drowsiness_data.get("alert_message"),
    }


def run_pipeline():
    """Run the drowsiness detection pipeline."""
    logger.info("=" * 60)
    logger.info("SmartDrive Guardian AI Service — Phase 2")
    logger.info("Drowsiness Detection Pipeline")
    logger.info("=" * 60)

    # Initialize camera
    camera = CameraStream(
        camera_index=settings.CAMERA_INDEX,
        width=settings.CAMERA_WIDTH,
        height=settings.CAMERA_HEIGHT,
        fps=settings.CAMERA_FPS,
    )
    if not camera.open():
        logger.error("Cannot open camera. Exiting.")
        return

    # Initialize face landmark detector
    detector = LandmarkDetector()
    if not detector.initialize():
        logger.error("Cannot initialize face detector. Exiting.")
        camera.release()
        return

    # Initialize temporal analyzer
    temporal = TemporalAnalyzer()

    logger.info("Pipeline ready. Press 'q' to quit.")
    logger.info("-" * 60)

    # Default state when no face is detected
    no_face_eye = {"left_ear": 0, "right_ear": 0, "ear": 0, "eye_closed": False}
    no_face_mouth = {"mar": 0, "yawning": False}
    no_face_drowsiness = {"state": STATE_NORMAL, "alert_message": None}

    frame_count = 0
    fps = 0.0
    fps_start = time.time()

    try:
        while True:
            frame = camera.read_frame()
            if frame is None:
                logger.warning("Failed to read frame")
                continue

            # Convert BGR → RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Detect face landmarks
            landmarks = detector.detect(rgb_frame)

            if landmarks is not None:
                # Face detected — run the full pipeline
                eye_data = get_eye_state(landmarks)
                mouth_data = get_mouth_state(landmarks)

                # Update temporal state
                temporal.update(
                    eye_closed=eye_data["eye_closed"],
                    yawning=mouth_data["yawning"],
                )
                temporal_data = temporal.get_state()

                # Classify drowsiness
                drowsiness_data = classify_drowsiness(
                    eye_closed=eye_data["eye_closed"],
                    closed_duration=temporal_data["closed_duration"],
                    perclos=temporal_data["perclos"],
                    yawning=mouth_data["yawning"],
                )

                # Trigger alarm if needed
                trigger_alarm(drowsiness_data["state"])

                # Build result for Phase 3
                result = build_result(eye_data, mouth_data, temporal_data, drowsiness_data)

                # Log state changes
                if drowsiness_data["state"] != STATE_NORMAL:
                    logger.warning(
                        f"State: {drowsiness_data['state']} | "
                        f"EAR: {eye_data['ear']:.3f} | "
                        f"Closed: {temporal_data['closed_duration']:.1f}s | "
                        f"PERCLOS: {temporal_data['perclos']:.1f}%"
                    )

            else:
                # No face detected
                eye_data = no_face_eye
                mouth_data = no_face_mouth
                temporal_data = temporal.get_state()
                drowsiness_data = no_face_drowsiness
                trigger_alarm(STATE_NORMAL)

            # Calculate FPS
            frame_count += 1
            elapsed = time.time() - fps_start
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                frame_count = 0
                fps_start = time.time()

            # Draw debug info on the frame
            draw_debug_info(
                frame, eye_data, mouth_data, temporal_data,
                drowsiness_data, landmarks, fps
            )

            # Show "NO FACE" overlay if applicable
            if landmarks is None:
                h, w = frame.shape[:2]
                cv2.putText(
                    frame, "NO FACE DETECTED", (w // 2 - 160, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2
                )

            # Display the frame
            cv2.imshow("SmartDrive Guardian - Drowsiness Detection", frame)

            # Check for quit key
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                logger.info("Quit key pressed")
                break

    except KeyboardInterrupt:
        logger.info("Interrupted by user")

    finally:
        # Cleanup
        detector.close()
        camera.release()
        logger.info("Pipeline stopped.")


if __name__ == "__main__":
    run_pipeline()
