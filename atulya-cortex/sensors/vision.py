"""
vision.py

A full-fledged 'Vision Engine' that models human-like vision concepts:
- "Eyes": individual camera interfaces
- "VisualCortex": the system orchestrating multiple Eyes
- Handles multiple camera inputs, with robust error handling
- Human-centric nomenclature: "open_eyelids", "blink", etc.
"""

import logging
from typing import List, Dict, Optional

try:
    import cv2  # Requires OpenCV
except ImportError as e:
    raise ImportError(
        "OpenCV not found. Please install it via 'pip install opencv-python' or 'pip install opencv-contrib-python'."
    ) from e


class VisionError(Exception):
    """Custom exception for vision-related errors."""
    pass


class Eye:
    """
    Represents a single 'Eye,' i.e., a camera source.

    Attributes:
        eye_name (str): A friendly name for the eye.
        camera_index (int): The index or path for this camera (0, 1, ..., or a video file).
        capture (cv2.VideoCapture): OpenCV capture object.
    """

    def __init__(self, eye_name: str, camera_index: int):
        self.eye_name = eye_name
        self.camera_index = camera_index
        self.capture: Optional[cv2.VideoCapture] = None

    def open_eyelid(self) -> None:
        """
        Opens the eye (camera). Raises VisionError if the camera cannot be opened.
        """
        try:
            self.capture = cv2.VideoCapture(self.camera_index)
            if not self.capture.isOpened():
                raise VisionError(f"Failed to open camera index {self.camera_index} for {self.eye_name}")
            logging.info(f"{self.eye_name} eyelid opened successfully on camera index {self.camera_index}.")
        except Exception as e:
            logging.error(f"{self.eye_name} -> Unexpected error opening camera: {e}")
            raise VisionError(f"{self.eye_name} -> Unexpected error: {e}") from e

    def blink(self):
        """
        Closes the eyelid (release the camera).
        """
        if self.capture and self.capture.isOpened():
            self.capture.release()
            logging.info(f"{self.eye_name} eyelid closed.")
        self.capture = None

    def see(self):
        """
        Reads a single frame from the Eye (camera). Raises VisionError on failure.
        Returns the captured frame (numpy array).
        """
        if not self.capture or not self.capture.isOpened():
            raise VisionError(f"{self.eye_name} -> Camera is not opened. Call open_eyelid() first.")
        ret, frame = self.capture.read()
        if not ret or frame is None:
            raise VisionError(f"{self.eye_name} -> Failed to capture frame.")
        return frame

    def __del__(self):
        """
        Ensures the camera is released upon object deletion.
        """
        self.blink()


class VisualCortex:
    """
    The 'Visual Cortex' orchestrates multiple Eyes (cameras).
    Can open them, gather frames, and handle errors gracefully.
    """

    def __init__(self, eyes_config: List[int] = None):
        """
        Initializes multiple Eyes. 
        :param eyes_config: A list of camera indices (e.g., [0, 1]) or paths for video streams.
        """
        if eyes_config is None:
            eyes_config = [0]  # Default to a single camera at index 0

        self.eyes = [
            Eye(eye_name=f"Eye_{idx}", camera_index=idx) for idx in eyes_config
        ]

    def awaken_eyes(self) -> None:
        """
        Attempts to open all eyes (cameras) in the system.
        Raises VisionError if any eye fails to open.
        """
        for eye in self.eyes:
            try:
                eye.open_eyelid()
            except VisionError as ve:
                logging.error(f"Failed to awaken {eye.eye_name}: {ve}")
                raise

    def rest_eyes(self) -> None:
        """
        Closes all eyes (releases cameras).
        """
        for eye in self.eyes:
            eye.blink()

    def gather_visuals(self) -> Dict[str, object]:
        """
        Returns a dictionary of frames from each Eye, keyed by eye_name.
        :return: { "Eye_0": frame, "Eye_1": frame, ... }
        """
        visuals = {}
        for eye in self.eyes:
            try:
                frame = eye.see()
                visuals[eye.eye_name] = frame
            except VisionError as e:
                logging.warning(f"{eye.eye_name} -> Could not capture frame: {e}")
        return visuals

    def __del__(self):
        """
        Make sure cameras are released on object deletion.
        """
        self.rest_eyes()


def main_demo():
    """
    Demonstrates how to use the VisualCortex with multiple cameras.
    - Tries to open cameras at indices 0 and 1 (adjust for your system)
    - Captures frames from each, then displays them in OpenCV windows
    - Press any key in an OpenCV window to exit
    """
    # Set up logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Example: Indices for two cameras (0 and 1). Adjust based on your hardware.
    cortex = VisualCortex(eyes_config=[0, 1])
    try:
        cortex.awaken_eyes()
        while True:
            frames = cortex.gather_visuals()
            for eye_name, frame in frames.items():
                # Display each camera's frame in a separate window
                cv2.imshow(eye_name, frame)

            # Wait briefly; exit if any key is pressed
            if cv2.waitKey(1) & 0xFF != 255:  # 255 is "no key pressed" in some environments
                break

    except VisionError as e:
        logging.error(f"Vision error occurred: {e}")
    finally:
        cortex.rest_eyes()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main_demo()
