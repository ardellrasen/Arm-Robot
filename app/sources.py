"""Sumber input: webcam, file video, atau "tangan virtual" mouse (tanpa kamera sama sekali)."""
from __future__ import annotations

import time

import cv2
import numpy as np

from .tracker import HandFeatures, HandTracker


class CameraSource:
    """Webcam / file video + MediaPipe."""

    def __init__(self, cfg, video: str | None = None):
        self.video = video
        if video:
            self.cap = cv2.VideoCapture(video)
            self.mirror = False
            self.name = f"VIDEO: {video}"
        else:
            backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") and _is_windows() else cv2.CAP_ANY
            self.cap = cv2.VideoCapture(cfg.camera.index, backend)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.camera.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.camera.height)
            self.mirror = cfg.camera.mirror
            self.name = f"KAMERA {cfg.camera.index}"
        if not self.cap.isOpened():
            raise RuntimeError(f"Tidak bisa membuka {'video ' + video if video else 'kamera'}. "
                               "Coba --mouse untuk simulasi tanpa kamera.")
        self.tracker = HandTracker(cfg.tracking.min_detection_confidence,
                                   cfg.tracking.min_tracking_confidence)
        self._fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._last_t = time.monotonic()

    def read(self):
        ok, frame = self.cap.read()
        if not ok and self.video:            # video habis -> ulang dari awal
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        if not ok:
            return None, HandFeatures(visible=False)
        if self.mirror:
            frame = cv2.flip(frame, 1)
        if self.video:                       # putar video sesuai fps aslinya
            wait = 1.0 / self._fps - (time.monotonic() - self._last_t)
            if wait > 0:
                time.sleep(wait)
            self._last_t = time.monotonic()
        return frame, self.tracker.process(frame)

    def on_mouse(self, *args) -> None:
        pass

    def close(self) -> None:
        self.tracker.close()
        self.cap.release()


class MouseSource:
    """Tangan virtual: posisi mouse di area kamera = posisi tangan, tahan klik kiri = cubit.
    Mouse keluar dari area kamera = tangan hilang."""

    W, H = 1280, 720
    name = "TANGAN VIRTUAL (mouse)"

    def __init__(self, demo: bool = False):
        self.x, self.y = 0.5, 0.5
        self.inside = False
        self.pressed = False
        self.demo = demo                    # demo = tangan virtual bergerak sendiri
        self._t0 = time.monotonic()
        if demo:
            self.name = "DEMO OTOMATIS (tangan virtual)"
        self._bg = self._make_background()

    def _make_background(self):
        img = np.full((self.H, self.W, 3), (48, 40, 36), np.uint8)
        for gx in range(0, self.W, 80):
            cv2.line(img, (gx, 0), (gx, self.H), (62, 54, 50), 1)
        for gy in range(0, self.H, 80):
            cv2.line(img, (0, gy), (self.W, gy), (62, 54, 50), 1)
        cv2.putText(img, "Mode tangan virtual: gerakkan mouse, tahan klik kiri = cubit",
                    (30, self.H - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (170, 160, 150), 2, cv2.LINE_AA)
        return img

    def on_mouse(self, nx: float, ny: float, inside: bool, pressed: bool) -> None:
        self.x, self.y, self.inside, self.pressed = nx, ny, inside, pressed

    def read(self):
        time.sleep(1 / 60)                  # ~60 fps, seperti kamera
        frame = self._bg.copy()
        if self.demo:
            t = time.monotonic() - self._t0
            cycle = t % 16.0
            if cycle > 14.0:                # 2 detik "tangan hilang" tiap 16 detik
                return frame, HandFeatures(visible=False)
            self.x = 0.5 + 0.38 * np.sin(t * 0.7)
            self.y = 0.5 + 0.38 * np.sin(t * 1.1 + 1.0)
            self.pressed = (t % 4.0) > 2.5
            self.inside = True
        if not self.inside:
            return frame, HandFeatures(visible=False)
        pinch = 0.15 if self.pressed else 0.80
        return frame, HandFeatures(x=float(self.x), y=float(self.y), pinch=pinch, visible=True)

    def close(self) -> None:
        pass


def _is_windows() -> bool:
    import sys
    return sys.platform.startswith("win")
