"""SmartDrive Guardian AI Service — Main Entry Point.

Phase 3: Drowsiness detection pipeline + WebSocket server.

Pipeline:
    Camera
        ↓
    Face Landmarks
        ↓
    EAR / MAR
        ↓
    Temporal Analysis
        ↓
    Drowsiness State
        ↓
    WebSocket
        ↓
    Backend / Dashboard

The local OpenCV camera window displays only:
    - Face landmark dots
    - Driver status
    - Drowsiness percentage
    - Drowsiness progress bar
    - Active alert

Technical debugging values such as EAR, MAR, closed duration,
PERCLOS text, yawns, FPS and WebSocket client count are not
displayed on the camera.
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

from src.temporal.temporal_analyzer import TemporalAnalyzer

from src.classifiers.drowsiness_classifier import (
    classify_drowsiness,
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

                freq = (
                    2500
                    if state == STATE_MICROSLEEP
                    else 1800
                )

                winsound.Beep(freq, 200)

            except ImportError:
                print("\a", end="", flush=True)

    else:
        _alarm_active = False


# ============================================================
# YAWN CONFIGURATION
# ============================================================

def load_yawn_config() -> dict:
    """Load yawn detection parameters from thresholds.yaml."""

    defaults = {
        "mar_threshold": 0.60,
        "yawn_min_duration": 1.0,
        "yawn_reset_duration": 0.3,
    }

    try:

        with open(settings.THRESHOLDS_PATH) as f:
            thresholds = yaml.safe_load(f) or {}

        mouth_cfg = thresholds.get(
            "mouth_state",
            {},
        )

        return {
            "mar_threshold": float(
                mouth_cfg.get(
                    "mar_threshold",
                    defaults["mar_threshold"],
                )
            ),

            "yawn_min_duration": float(
                mouth_cfg.get(
                    "yawn_min_duration",
                    defaults["yawn_min_duration"],
                )
            ),

            "yawn_reset_duration": float(
                mouth_cfg.get(
                    "yawn_reset_duration",
                    defaults["yawn_reset_duration"],
                )
            ),
        }

    except Exception as e:

        logger.warning(
            f"Could not load thresholds.yaml: {e}. "
            "Using defaults."
        )

        return defaults


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

        target_h = int(
            h * width / w
        )

        small = cv2.resize(
            frame,
            (width, target_h),
            interpolation=cv2.INTER_LINEAR,
        )

        ok, buf = cv2.imencode(
            ".jpg",
            small,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                quality,
            ],
        )

        if ok:

            return base64.b64encode(
                buf
            ).decode("utf-8")

    except Exception:
        pass

    return ""


# ============================================================
# DRIVER STATUS
# ============================================================

def get_display_status(state: str) -> str:
    """Convert internal AI state to user-friendly status."""

    if state == STATE_MICROSLEEP:
        return "SLEEPING"

    if state == STATE_DROWSY:
        return "DROWSY"

    return "AWAKE"


def get_status_color(state: str):
    """Return OpenCV BGR color for driver status."""

    if state == STATE_MICROSLEEP:

        # Red
        return (0, 0, 255)

    if state == STATE_DROWSY:

        # Orange
        return (0, 165, 255)

    # Green
    return (0, 200, 0)


# ============================================================
# CAMERA DISPLAY
# ============================================================

def draw_debug_info(
    frame,
    eye_data,
    mouth_data,
    temporal_data,
    drowsiness_data,
    landmarks=None,
    fps=0,
    client_count=0,
    yawn_state="MOUTH_NORMAL",
):
    """
    Draw only the required information on the local camera.

    DISPLAYED:
        - Face landmark dots
        - Driver status
        - Drowsiness percentage
        - Progress bar
        - Alert

    HIDDEN:
        - EAR
        - MAR
        - Closed duration
        - PERCLOS raw text
        - Yawn count
        - FPS
        - WebSocket clients
        - Other technical/debug values
    """

    h, w = frame.shape[:2]

    state = drowsiness_data.get(
        "state",
        STATE_NORMAL,
    )

    status_color = get_status_color(
        state
    )

    status_text = get_display_status(
        state
    )

    # ========================================================
    # DROWSINESS PERCENTAGE
    # ========================================================

    try:

        drowsiness_percentage = float(
            temporal_data.get(
                "perclos",
                0.0,
            )
        )

    except (TypeError, ValueError):

        drowsiness_percentage = 0.0

    drowsiness_percentage = max(
        0.0,
        min(
            100.0,
            drowsiness_percentage,
        ),
    )

    # ========================================================
    # STATUS BORDER
    # ========================================================

    if state == STATE_MICROSLEEP:

        border_width = 8

    elif state == STATE_DROWSY:

        border_width = 5

    else:

        border_width = 3

    cv2.rectangle(
        frame,
        (0, 0),
        (w - 1, h - 1),
        status_color,
        border_width,
    )

    # ========================================================
    # FACE LANDMARK DOTS
    # ========================================================
    #
    # Keep the eye landmark points visible.
    #
    # These are the same landmark indices used by the
    # existing eye-state detection.
    #
    # ========================================================

    if landmarks is not None:

        for idx in (
            LEFT_EYE_INDICES
            + RIGHT_EYE_INDICES
        ):

            try:

                x = int(
                    landmarks[idx][0] * w
                )

                y = int(
                    landmarks[idx][1] * h
                )

                cv2.circle(
                    frame,
                    (x, y),
                    2,
                    (0, 255, 0),
                    -1,
                )

            except (
                IndexError,
                TypeError,
                ValueError,
            ):

                continue

    # ========================================================
    # DRIVER STATUS
    # ========================================================

    status_label = (
        f"DRIVER STATUS: {status_text}"
    )

    cv2.putText(
        frame,
        status_label,
        (20, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        status_color,
        3,
        cv2.LINE_AA,
    )

    # ========================================================
    # DROWSINESS PERCENTAGE
    # ========================================================

    drowsiness_label = (
        f"DROWSINESS: "
        f"{drowsiness_percentage:.0f}%"
    )

    cv2.putText(
        frame,
        drowsiness_label,
        (20, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    # ========================================================
    # DROWSINESS PROGRESS BAR
    # ========================================================

    # bar_x = 20
    # bar_y = 110

    # bar_width = min(
    #     400,
    #     w - 40,
    # )

    # bar_height = 18

    # # Background
    # cv2.rectangle(
    #     frame,
    #     (
    #         bar_x,
    #         bar_y,
    #     ),
    #     (
    #         bar_x + bar_width,
    #         bar_y + bar_height,
    #     ),
    #     (50, 50, 50),
    #     -1,
    # )

    # filled_width = int(
    #     bar_width
    #     * (
    #         drowsiness_percentage
    #         / 100.0
    #     )
    # )

    # if filled_width > 0:

    #     cv2.rectangle(
    #         frame,
    #         (
    #             bar_x,
    #             bar_y,
    #         ),
    #         (
    #             bar_x + filled_width,
    #             bar_y + bar_height,
    #         ),
    #         status_color,
    #         -1,
    #     )

    # ========================================================
    # ALERT MESSAGE
    # ========================================================

    alert = drowsiness_data.get(
        "alert_message"
    )

    if alert:

        alert_height = 65

        alert_y1 = (
            h - alert_height
        )

        # Alert background
        cv2.rectangle(
            frame,
            (0, alert_y1),
            (w, h),
            status_color,
            -1,
        )

        # Alert text
        cv2.putText(
            frame,
            str(alert),
            (20, h - 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )


# ============================================================
# WEBSOCKET RESULT
# ============================================================

def build_result(
    eye_data,
    mouth_data,
    temporal_data,
    drowsiness_data,
    frame_b64: str = "",
):
    """
    Build the detection result sent to the backend.

    The existing AI calculations are preserved.

    The dashboard receives:
        - state
        - driver_status
        - drowsiness_percentage
        - alert_message
        - live frame
    """

    try:

        drowsiness_percentage = float(
            temporal_data.get(
                "perclos",
                0.0,
            )
        )

    except (TypeError, ValueError):

        drowsiness_percentage = 0.0

    drowsiness_percentage = max(
        0.0,
        min(
            100.0,
            drowsiness_percentage,
        ),
    )

    result = {
        "type": "drowsiness",

        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),

        # Internal state
        "state": drowsiness_data[
            "state"
        ],

        # User-friendly status
        "driver_status": get_display_status(
            drowsiness_data[
                "state"
            ]
        ),

        # Drowsiness percentage
        "drowsiness_percentage": round(
            drowsiness_percentage,
            1,
        ),

        # Keep PERCLOS for backend compatibility.
        # It is not displayed in the camera window.
        "perclos": round(
            drowsiness_percentage,
            1,
        ),

        # Alert
        "alert_message": drowsiness_data.get(
            "alert_message"
        ),
    }

    # ========================================================
    # LIVE CAMERA FRAME
    # ========================================================

    if frame_b64:

        result["frame_b64"] = (
            frame_b64
        )

    return result


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline():
    """Run drowsiness detection and WebSocket server."""

    logger.info("=" * 60)

    logger.info(
        "SmartDrive Guardian AI Service — Phase 3"
    )

    logger.info(
        "Drowsiness Detection Pipeline & WebSocket Server"
    )

    logger.info("=" * 60)

    # ========================================================
    # YAWN CONFIGURATION
    # ========================================================

    yawn_cfg = load_yawn_config()

    logger.info(
        f"Yawn detector config: "
        f"MAR_THRESHOLD="
        f"{yawn_cfg['mar_threshold']} | "
        f"MIN_DURATION="
        f"{yawn_cfg['yawn_min_duration']}s | "
        f"RESET_DURATION="
        f"{yawn_cfg['yawn_reset_duration']}s"
    )

    # ========================================================
    # WEBSOCKET SERVER
    # ========================================================

    ws_server = AIWebSocketServer(
        host=settings.AI_SERVER_HOST,
        port=settings.AI_SERVER_PORT,
    )

    ws_server.start()

    # ========================================================
    # CAMERA
    # ========================================================

    camera = CameraStream(
        camera_index=settings.CAMERA_INDEX,
        width=settings.CAMERA_WIDTH,
        height=settings.CAMERA_HEIGHT,
        fps=settings.CAMERA_FPS,
    )

    if not camera.open():

        logger.error(
            "Cannot open camera. Exiting."
        )

        ws_server.stop()

        return

    # ========================================================
    # FACE LANDMARK DETECTOR
    # ========================================================

    detector = LandmarkDetector()

    if not detector.initialize():

        logger.error(
            "Cannot initialize face detector. Exiting."
        )

        camera.release()

        ws_server.stop()

        return

    # ========================================================
    # TEMPORAL ANALYZER
    # ========================================================

    temporal = TemporalAnalyzer()

    # ========================================================
    # YAWN DETECTOR
    # ========================================================

    yawn_detector = YawnDetector(
        mar_threshold=yawn_cfg[
            "mar_threshold"
        ],
        min_duration=yawn_cfg[
            "yawn_min_duration"
        ],
        reset_duration=yawn_cfg[
            "yawn_reset_duration"
        ],
    )

    logger.info(
        "AI Service ready. "
        f"Streaming on "
        f"ws://{settings.AI_SERVER_HOST}:"
        f"{settings.AI_SERVER_PORT}/ws/ai"
    )

    logger.info(
        "Press 'q' in the camera window to quit."
    )

    logger.info("-" * 60)

    # ========================================================
    # DEFAULT STATES
    # ========================================================

    no_face_eye = {
        "left_ear": 0.0,
        "right_ear": 0.0,
        "ear": 0.0,
        "eye_closed": False,
    }

    no_face_mouth = {
        "mar": 0.0,
        "yawning": False,
    }

    no_face_drowsiness = {
        "state": STATE_NORMAL,
        "alert_message": None,
    }

    # ========================================================
    # FPS / FRAME COUNT
    # ========================================================

    frame_count = 0

    fps = 0.0

    fps_start = time.time()

    # ========================================================
    # LIVE DASHBOARD STREAM
    # ========================================================

    # Approximately 10 FPS when camera runs at 30 FPS.
    STREAM_EVERY_N_FRAMES = 3

    # ========================================================
    # MAIN LOOP
    # ========================================================

    try:

        while True:

            # ------------------------------------------------
            # READ FRAME
            # ------------------------------------------------

            frame = camera.read_frame()

            if frame is None:

                logger.warning(
                    "Failed to read frame"
                )

                continue

            frame_count += 1

            # ------------------------------------------------
            # BGR → RGB
            # ------------------------------------------------

            rgb_frame = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB,
            )

            # ------------------------------------------------
            # FACE LANDMARKS
            # ------------------------------------------------

            landmarks = detector.detect(
                rgb_frame
            )

            # =================================================
            # FACE DETECTED
            # =================================================

            if landmarks is not None:

                # ---------------------------------------------
                # EYE STATE
                # ---------------------------------------------

                eye_data = get_eye_state(
                    landmarks
                )

                # ---------------------------------------------
                # MOUTH STATE
                # ---------------------------------------------

                mouth_data = get_mouth_state(
                    landmarks
                )

                mar_value = mouth_data[
                    "mar"
                ]

                # ---------------------------------------------
                # TEMPORAL YAWN DETECTOR
                # ---------------------------------------------

                yawn_result = (
                    yawn_detector.update(
                        mar_value
                    )
                )

                mouth_data[
                    "yawning"
                ] = yawn_result[
                    "yawning"
                ]

                mouth_data[
                    "mouth_state"
                ] = yawn_result[
                    "mouth_state"
                ]

                # ---------------------------------------------
                # TEMPORAL ANALYZER
                # ---------------------------------------------

                temporal.update(
                    eye_closed=eye_data[
                        "eye_closed"
                    ],
                    yawning=yawn_result[
                        "yawning"
                    ],
                )

                temporal_data = (
                    temporal.get_state()
                )

                # ---------------------------------------------
                # DROWSINESS CLASSIFIER
                # ---------------------------------------------

                drowsiness_data = (
                    classify_drowsiness(
                        eye_closed=eye_data[
                            "eye_closed"
                        ],
                        closed_duration=(
                            temporal_data[
                                "closed_duration"
                            ]
                        ),
                        perclos=(
                            temporal_data[
                                "perclos"
                            ]
                        ),
                        yawning=yawn_result[
                            "yawning"
                        ],
                    )
                )

                # ---------------------------------------------
                # ALARM
                # ---------------------------------------------

                trigger_alarm(
                    drowsiness_data[
                        "state"
                    ]
                )

                # ---------------------------------------------
                # FRAME FOR WEBSITE
                # ---------------------------------------------

                frame_b64 = ""

                if (
                    frame_count
                    % STREAM_EVERY_N_FRAMES
                    == 0
                ):

                    frame_b64 = (
                        encode_frame_b64(
                            frame,
                            width=320,
                            quality=50,
                        )
                    )

                # ---------------------------------------------
                # BUILD RESULT
                # ---------------------------------------------

                result = build_result(
                    eye_data,
                    mouth_data,
                    temporal_data,
                    drowsiness_data,
                    frame_b64,
                )

                # ---------------------------------------------
                # SEND TO BACKEND
                # ---------------------------------------------

                ws_server.broadcast_sync(
                    result
                )

                # ---------------------------------------------
                # TERMINAL LOGGING
                #
                # Technical information can still be logged
                # in the terminal for development/debugging.
                #
                # It is NOT displayed on the camera.
                # ---------------------------------------------

                if (
                    drowsiness_data[
                        "state"
                    ]
                    != STATE_NORMAL
                ):

                    logger.warning(
                        f"State: "
                        f"{drowsiness_data['state']} | "
                        f"Closed: "
                        f"{temporal_data['closed_duration']:.1f}s | "
                        f"Drowsiness: "
                        f"{temporal_data['perclos']:.1f}%"
                    )

            # =================================================
            # NO FACE
            # =================================================

            else:

                eye_data = no_face_eye

                mouth_data = no_face_mouth

                temporal_data = (
                    temporal.get_state()
                )

                drowsiness_data = (
                    no_face_drowsiness
                )

                trigger_alarm(
                    STATE_NORMAL
                )

                frame_b64 = ""

                if (
                    frame_count
                    % STREAM_EVERY_N_FRAMES
                    == 0
                ):

                    frame_b64 = (
                        encode_frame_b64(
                            frame,
                            width=320,
                            quality=50,
                        )
                    )

                result = build_result(
                    eye_data,
                    mouth_data,
                    temporal_data,
                    drowsiness_data,
                    frame_b64,
                )

                ws_server.broadcast_sync(
                    result
                )

            # =================================================
            # INTERNAL FPS CALCULATION
            # =================================================

            elapsed = (
                time.time()
                - fps_start
            )

            if elapsed >= 1.0:

                fps = (
                    frame_count
                    / elapsed
                )

                frame_count = 0

                fps_start = time.time()

            # =================================================
            # CAMERA OVERLAY
            # =================================================

            yawn_state = mouth_data.get(
                "mouth_state",
                yawn_detector.MOUTH_NORMAL,
            )

            draw_debug_info(
                frame,
                eye_data,
                mouth_data,
                temporal_data,
                drowsiness_data,

                # IMPORTANT:
                # Pass the actual landmarks so the
                # green eye landmark dots remain visible.
                landmarks=landmarks,

                # These remain available internally but
                # are NOT displayed.
                fps=fps,
                client_count=(
                    ws_server.client_count
                ),
                yawn_state=yawn_state,
            )

            # =================================================
            # NO FACE MESSAGE
            # =================================================

            if landmarks is None:

                h, w = frame.shape[:2]

                cv2.putText(
                    frame,
                    "NO FACE DETECTED",
                    (
                        w // 2 - 160,
                        h // 2,
                    ),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )

            # =================================================
            # DISPLAY CAMERA
            # =================================================

            cv2.imshow(
                "SmartDrive Guardian - Drowsiness Detection",
                frame,
            )

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):

                logger.info(
                    "Quit key pressed"
                )

                break

    except KeyboardInterrupt:

        logger.info(
            "Interrupted by user"
        )

    finally:

        ws_server.stop()

        detector.close()

        camera.release()

        cv2.destroyAllWindows()

        logger.info(
            "Pipeline stopped."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    run_pipeline()