"""MediaPipe Hands -> fitur tangan (x, y, pinch)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2


@dataclass
class HandFeatures:
    x: float = 0.5          # landmark 9 (pangkal jari tengah), 0..1
    y: float = 0.5
    pinch: float = 1.0      # jarak lm4-lm8 / jarak lm0-lm9
    visible: bool = False
    landmarks: list = field(default_factory=list)   # [(x, y), ...] 21 titik ternormalisasi (untuk gambar)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def features_from_landmarks(pts: list[tuple[float, float]], aspect: float = 16 / 9) -> HandFeatures:
    """pts: 21 titik (x, y) ternormalisasi. aspect = lebar/tinggi frame (jarak dihitung di ruang piksel)."""
    sx = [(p[0] * aspect, p[1]) for p in pts]
    size = max(_dist(sx[0], sx[9]), 1e-6)
    pinch = _dist(sx[4], sx[8]) / size
    return HandFeatures(x=pts[9][0], y=pts[9][1], pinch=pinch, visible=True, landmarks=list(pts))


class HandTracker:
    def __init__(self, min_detection_confidence: float, min_tracking_confidence: float):
        import mediapipe as mp   # import di sini supaya mode mouse tidak butuh mediapipe
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,   # deteksi sampai 2, lalu pilih yang terbesar (paling dekat)
            model_complexity=0,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def process(self, frame_bgr) -> HandFeatures:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        res = self._hands.process(rgb)
        if not res.multi_hand_landmarks:
            return HandFeatures(visible=False)
        best, best_size = None, -1.0
        for hand in res.multi_hand_landmarks:
            pts = [(lm.x, lm.y) for lm in hand.landmark]
            f = features_from_landmarks(pts, w / h)
            size = _dist((pts[0][0] * w, pts[0][1] * h), (pts[9][0] * w, pts[9][1] * h))
            if size > best_size:
                best, best_size = f, size
        return best

    def close(self) -> None:
        self._hands.close()
