"""Camera capture module — opens webcam via OpenCV and provides frames."""

import cv2
import logging
import time

logger = logging.getLogger("smartdrive.ai")


class CameraStream:
    """Captures frames from the default webcam using OpenCV."""

    def __init__(self, camera_index=0, width=640, height=480, fps=30):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.cap = None
        self._is_open = False

    def open(self) -> bool:
        """Open the webcam. Returns True if successful."""
        logger.info(f"Opening camera (index={self.camera_index})...")
        self.cap = cv2.VideoCapture(self.camera_index)

        if not self.cap.isOpened():
            logger.error("Failed to open camera!")
            return False

        # Set resolution and FPS
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

        # Read actual values
        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = int(self.cap.get(cv2.CAP_PROP_FPS))

        self._is_open = True
        logger.info(f"Camera opened: {actual_w}x{actual_h} @ {actual_fps}fps")
        return True

    def read_frame(self):
        """Read a single frame from the webcam.

        Returns:
            frame (numpy array or None): BGR frame, or None if read failed.
        """
        if self.cap is None or not self.cap.isOpened():
            return None

        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def release(self):
        """Release the camera and close any OpenCV windows."""
        if self.cap is not None:
            self.cap.release()
            self._is_open = False
            logger.info("Camera released")
        cv2.destroyAllWindows()

    @property
    def is_open(self) -> bool:
        """Check if the camera is currently open."""
        return self._is_open and self.cap is not None and self.cap.isOpened()
