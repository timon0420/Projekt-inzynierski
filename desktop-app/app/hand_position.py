from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Mapping, Sequence

@dataclass(frozen=True)
class HandPosition:
    center_pixels: tuple[float, float, float]
    relative_landmarks: tuple[tuple[float, float, float], ...]
    orientation_degreees: tuple[float, float, float]

class HandPositionCalculator:
    PALM_INDICES = (0, 5, 9, 13, 17)
    DEFAULT_RANGES = {
        "x": (0.0, 1.0),
        "y": (1.0, 0.0), 
        "z": (-0.25, 0.25),
        "yaw": (-90.0, 90.0),
        "pitch": (-90.0, 90.0),
        "roll": (-180.0, 180.0), 
    }

    def __init__(self, input_ranges: Mapping[str, tuple[float, float]] | None = None):
        self.ranges = self.DEFAULT_RANGES.copy()
        if input_ranges is not None:
            self.ranges.update(input_ranges)

    def calculate_position(self, landmarks: Sequence[object], frame_width: int, frame_height: int) -> HandPosition:
        if len(landmarks) < 21:
            raise ValueError("Expected 21 landmarks for a hand, got {}".format(len(landmarks)))
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Frame width and height must be positive integers.")

        points = tuple((
            float(point.x) * frame_width,
            float(point.y) * frame_height,
            float(point.z) * frame_width
        ) for point in landmarks)

        center = tuple(sum(points[index][axis] for index in self.PALM_INDICES) / len(self.PALM_INDICES) for axis in range(3))

        relative = tuple((x - center[0], y - center[1], z - center[2]) for x, y, z in points)

        orientation = self._calculate_orientation(landmarks)
        return HandPosition(center, relative, orientation)

    def pixels_to_angles(
        self, position: HandPosition, frame_width: int, frame_height: int
    ) -> list[float]:
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Wymiary obrazu muszą być dodatnie.")

        x, y, z_pixels = position.center_pixels
        yaw, pitch, roll = position.orientation_degrees
        values = {
            "x": x / frame_width,
            "y": y / frame_height,
            "z": z_pixels / frame_width,
            "yaw": yaw,
            "pitch": pitch,
            "roll": roll,
        }
        return [round(self._map_to_angle(values[name], *self.input_ranges[name]), 2)
                for name in ("x", "y", "z", "yaw", "pitch", "roll")]

    @staticmethod
    def _map_to_angle(value: float, minimum: float, maximum: float) -> float:
        if math.isclose(minimum, maximum):
            raise ValueError("Zakres kalibracji nie może mieć zerowej długości.")
        ratio = (value - minimum) / (maximum - minimum)
        return max(0.0, min(180.0, ratio * 180.0))

    @staticmethod
    def _calculate_orientation(
        points: Sequence[tuple[float, float, float]]
    ) -> tuple[float, float, float]:
        wrist, index_base, middle_base, pinky_base = (
            points[0], points[5], points[9], points[17]
        )
        across = HandPositionCalculator._normalize(
            tuple(index_base[i] - pinky_base[i] for i in range(3))
        )
        forward = HandPositionCalculator._normalize(
            tuple(middle_base[i] - wrist[i] for i in range(3))
        )
        normal = HandPositionCalculator._normalize((
            across[1] * forward[2] - across[2] * forward[1],
            across[2] * forward[0] - across[0] * forward[2],
            across[0] * forward[1] - across[1] * forward[0],
        ))

        yaw = math.degrees(math.atan2(normal[0], normal[2]))
        pitch = math.degrees(math.atan2(-normal[1], math.hypot(normal[0], normal[2])))
        roll = math.degrees(math.atan2(forward[0], -forward[1]))
        return yaw, pitch, roll

    @staticmethod
    def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(sum(value * value for value in vector))
        if length < 1e-9:
            return 0.0, 0.0, 0.0
        return tuple(value / length for value in vector)