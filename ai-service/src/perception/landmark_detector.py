"""Face landmark detection using MediaPipe FaceLandmarker."""

import logging
import numpy as np
from pathlib import Path

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

logger = logging.getLogger("smartdrive.ai")

# Project-relative path to the model file
_MODEL_PATH = str(
    Path(__file__).resolve().parent.parent.parent / "models" / "face_landmarker.task"
)


class LandmarkDetector:
    """Detects face landmarks using MediaPipe FaceLandmarker.

    Returns 478 normalized landmarks for a single face.
    Does NOT include iris/gaze tracking.
    """

    def __init__(self, model_path=None):
        self.model_path = model_path or _MODEL_PATH
        self.landmarker = None

    def initialize(self) -> bool:
        """Load the FaceLandmarker model. Returns True if successful."""
        model_file = Path(self.model_path)
        if not model_file.exists():
            logger.error(f"Model file not found: {self.model_path}")
            logger.error(
                "Download it from: https://storage.googleapis.com/mediapipe-models/"
                "face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
            )
            return False

        try:
            base_options = mp_python.BaseOptions(
                model_asset_path=self.model_path
            )
            options = mp_vision.FaceLandmarkerOptions(
                base_options=base_options,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self.landmarker = mp_vision.FaceLandmarker.create_from_options(options)
            logger.info("FaceLandmarker initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize FaceLandmarker: {e}")
            return False

    def detect(self, rgb_frame):
        """Detect face landmarks in an RGB frame.

        Args:
            rgb_frame: numpy array in RGB format (H, W, 3)

        Returns:
            landmarks: list of (x, y, z) tuples for 478 landmarks, or None if no face.
        """
        if self.landmarker is None:
            return None

        try:
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB, data=rgb_frame
            )
            result = self.landmarker.detect(mp_image)

            if not result.face_landmarks:
                return None

            # Return the first face's landmarks as a list of (x, y, z)
            face = result.face_landmarks[0]
            landmarks = [(lm.x, lm.y, lm.z) for lm in face]
            return landmarks

        except Exception as e:
            logger.warning(f"Landmark detection error: {e}")
            return None

    def close(self):
        """Release the landmarker resources."""
        if self.landmarker is not None:
            self.landmarker.close()
            self.landmarker = None
            logger.info("FaceLandmarker closed")
