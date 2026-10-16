from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Mapping, Sequence

WRIST = 0
INDEX_MCP, MIDDLE_MCP, PINKY_MCP = 5, 9, 17
FINGER_TIPS = (8, 12, 16, 20)  # bez kciuka, którego położenie jest najmniej stabilne

# Kolejność kątów wysyłanych do modelu manipulatora.
ANGLE_NAMES = (
    "base",        # 1 - obrót ramienia w lewo / prawo (poziome położenie dłoni)
    "shoulder",    # 2 - pierwszy przegub góra / dół (wysokość dłoni w kadrze)
    "elbow",       # 3 - drugi przegub góra / dół (odległość dłoni od kamery)
    "wrist",       # 4 - trzeci przegub góra / dół (pochylenie dłoni do przodu / do tyłu)
    "gripper_roll",  # 5 - przechył chwytaka lewo / prawo (przechył dłoni)
    "grip",        # 6 - otwarcie chwytaka (0 = dłoń zamknięta, 180 = dłoń otwarta)
)

@dataclass(frozen=True)
class HandPosition:
    center_pixels: tuple[float, float, float]
    relative_landmarks: tuple[tuple[float, float, float], ...]
    orientation_degrees: tuple[float, float, float]

class HandPositionCalculator:
    PALM_INDICES = (0, 5, 9, 13, 17)
    # Zakresy wejściowe mapowane liniowo na 0-180°. Zamiana kolejności odwraca kierunek.
    DEFAULT_RANGES = {
        "base": (0.15, 0.85),         # x środka dłoni / szerokość kadru
        "shoulder": (0.85, 0.15),     # y środka dłoni / wysokość kadru (wyżej = większy kąt)
        "elbow": (0.06, 0.20),        # rozmiar dłoni / szerokość kadru (bliżej kamery = większy kąt)
        "wrist": (-60.0, 60.0),       # pochylenie dłoni w stopniach
        "gripper_roll": (-90.0, 90.0),  # przechył dłoni w stopniach
        "grip": (1.0, 1.9),           # odległość opuszków od nadgarstka / rozmiar dłoni
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

        orientation = self._calculate_orientation(points)
        return HandPosition(center, relative, orientation)

    def pixels_to_angles(
        self, position: HandPosition, frame_width: int, frame_height: int
    ) -> list[float]:
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Wymiary obrazu muszą być dodatnie.")

        x, y, _ = position.center_pixels
        _, pitch, roll = position.orientation_degrees
        points = position.relative_landmarks

        palm_size = self._palm_size(points, planar=False)
        values = {
            "base": x / frame_width,
            "shoulder": y / frame_height,
            "elbow": self._palm_size(points, planar=True) / frame_width,
            "wrist": pitch,
            "gripper_roll": roll,
            "grip": self._openness(points, palm_size),
        }
        return [round(self._map_to_angle(values[name], *self.ranges[name]), 2) for name in ANGLE_NAMES]

    @staticmethod
    def _palm_size(points: Sequence[tuple[float, float, float]], planar: bool) -> float:
        distance = HandPositionCalculator._distance2d if planar else math.dist
        return (distance(points[WRIST], points[MIDDLE_MCP]) + distance(points[INDEX_MCP], points[PINKY_MCP])) / 2

    @staticmethod
    def _distance2d(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    @staticmethod
    def _openness(points: Sequence[tuple[float, float, float]], palm_size: float) -> float:
        # Zaciśnięta pięść daje ok. 1.0, wyprostowane palce ok. 2.0 - niezależnie od odległości od kamery.
        if palm_size < 1e-9:
            return 0.0
        reach = sum(math.dist(points[tip], points[WRIST]) for tip in FINGER_TIPS) / len(FINGER_TIPS)
        return reach / palm_size

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
            points[WRIST], points[INDEX_MCP], points[MIDDLE_MCP], points[PINKY_MCP]
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
        # Pochylenie: palce w stronę kamery (mniejsze z) dają dodatni kąt, niezależnie od tego, która to dłoń.
        pitch = math.degrees(math.atan2(-forward[2], math.hypot(forward[0], forward[1])))
        # Przechył w płaszczyźnie obrazu: 0° gdy palce wskazują w górę.
        roll = math.degrees(math.atan2(forward[0], -forward[1]))
        return yaw, pitch, roll

    @staticmethod
    def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(sum(value * value for value in vector))
        if length < 1e-9:
            return 0.0, 0.0, 0.0
        return tuple(value / length for value in vector)
