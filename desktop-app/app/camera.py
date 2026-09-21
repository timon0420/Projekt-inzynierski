import time
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from app.hand_position import HandPositionCalculator

class Camera:
    CONNECTIONS = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
    ]

    def __init__(self, qimage_class, cap=None):
        self.QImage = qimage_class
        self.cap = cap
        self.calculator = HandPositionCalculator()
        self.last_landmarks = None
        self.last_detection_at = 0.0
        self.hold_detection_seconds = 0.25
        self._last_timestamp_ms = -1

        if self.cap is not None:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path="hand_landmarker.task"),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.3,
            min_hand_presence_confidence=0.3,
            min_hand_presence_confidence=0.3,
        )
        self.detector = vision.HandLandmarker.create_from_options(options)

    def run_camera(self):
        if self.cap is None:
            return None, None
        ret, frame = self.cap.read()
        if not ret or frame is None:
            return None, None
        return self.process_frame(frame, mirror=True)

    def process_jpeg(self, jpeg: bytes):
        encode = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(encode, cv2.IMREAD_COLOR)
        if frame is None:
            return None, None
        return self.process_frame(frame, mirror=False)

    def process_frame(self, frame, mirror=False):
        if frame is None:
            return None, None

        if mirror:
            frame = cv2.flip(frame, 1)

        frame, tracking_data = self._hand_tracking(frame)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channel = rgb_frame.shape
        qimage = self.QImage(rgb_frame.data, width, height, channel * width, self.QImage.Format.Format_RGB888).copy()

        return qimage, tracking_data

    def _hand_tracking(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = max(int(time.monotonic() * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        results = self.detector.detect_for_video(mp_image, timestamp_ms)

        now = time.monotonic()
        if results.hand_landmarks:
            self.last_landmarks = results.hand_landmarks[0]
            self.last_detection_at = now
        elif now - self.last_detection_at > self.hold_detection_seconds:
            self.last_landmarks = None

        if self.last_landmarks is None:
            return frame, None

        height, width = frame.shape[:2]
        points = []
        for landmark in self.last_landmarks:
            point = (int(landmark.x * width), int(landmark.y * height))
            points.append(point)
            cv2.circle(frame, point, 5, (52, 211, 153), -1)
        for start, end in self.CONNECTIONS:
            cv2.line(frame, points[start], points[end], (16, 185, 129), 2)

        position = self.calculator.calculate_position(self.last_landmarks, width, height)
        angles = self.calculator.calculate_angles(position, width, height)
        return frame, {"position": position, "angles": angles}

    def close(self):
        if self.detector is not None:
            self.detector.close()
            self.detector = None