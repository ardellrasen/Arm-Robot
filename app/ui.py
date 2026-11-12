"""Tampilan OpenCV: preview kamera + landmark, area interaksi, state, status ESP32, visual robot."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import Config
from .state import State

WIN = "Robot Arm ITB Insight"
W, H = 1280, 720
CAM_W, CAM_H = 960, 540
PANEL_X = CAM_W

FONT = cv2.FONT_HERSHEY_SIMPLEX
AA = cv2.LINE_AA

# Warna (BGR)
C_BG = (30, 26, 24)
C_PANEL = (44, 38, 35)
C_GRID = (70, 62, 58)
C_TEXT = (235, 235, 235)
C_DIM = (150, 145, 140)
C_ACCENT = (255, 190, 60)     # biru muda
C_GHOST = (120, 110, 100)
C_ARM = (80, 200, 255)        # oranye
C_GRIP = (120, 230, 120)
C_RED = (60, 60, 230)
C_GREEN = (90, 200, 90)
C_YELLOW = (60, 210, 240)

STATE_COLORS = {State.IDLE: (170, 140, 60), State.LIVE: C_GREEN, State.ESTOP: C_RED}
STATE_TEXT = {
    State.IDLE: "Angkat tanganmu di area kotak",
    State.LIVE: "Gerakkan tangan, cubit jempol + telunjuk untuk menjepit!",
    State.ESTOP: "BERHENTI DARURAT - tekan Space / tombol untuk lanjut",
}

HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
                    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
                    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


@dataclass
class ViewInfo:
    state: State
    mode_label: str             # "SIMULASI" / "ASLI"
    link_status: str
    link_ok: bool
    source_name: str
    fps: float
    target_servo: tuple         # (base, lengan, grip01) yang dikirim
    actual_servo: tuple         # (base, lengan, grip_deg) perkiraan posisi sekarang
    target_joint: tuple         # (yaw, pitch, grip01)
    actual_joint: tuple         # (yaw, pitch, grip 0..1)
    filtered_xy: tuple | None = None
    calib: bool = False
    log: list = field(default_factory=list)


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    def contains(self, px, py) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


def _text(img, s, org, scale=0.6, color=C_TEXT, thick=1):
    cv2.putText(img, s, org, FONT, scale, color, thick, AA)


def _text_center(img, s, cx, y, scale, color, thick=2):
    (tw, _), _ = cv2.getTextSize(s, FONT, scale, thick)
    _text(img, s, (int(cx - tw / 2), y), scale, color, thick)


class UI:
    def __init__(self, cfg: Config, fullscreen: bool):
        self.cfg = cfg
        self.fullscreen = fullscreen
        self.estop_btn = Rect(PANEL_X + 20, H - 120, 280, 100)
        self.cam_rect = Rect(0, 0, CAM_W, CAM_H)
        self.estop_clicked = False
        self.mouse_listener = None    # callback(nx, ny, inside, pressed) untuk tangan virtual
        self._pressed = False
        self._window_ready = False

    # --- jendela ------------------------------------------------------------
    def open_window(self) -> None:
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WIN, W, H)
        cv2.setMouseCallback(WIN, self._on_mouse)
        self._apply_fullscreen()
        self._window_ready = True

    def _apply_fullscreen(self) -> None:
        cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN if self.fullscreen else cv2.WINDOW_NORMAL)

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        if self._window_ready:
            self._apply_fullscreen()
            if not self.fullscreen:
                cv2.resizeWindow(WIN, W, H)

    def window_closed(self) -> bool:
        try:
            return cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1
        except cv2.error:
            return True

    def show(self, canvas) -> int:
        cv2.imshow(WIN, canvas)
        return cv2.waitKey(1) & 0xFF

    def _on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self._pressed = True
            if self.estop_btn.contains(x, y):
                self.estop_clicked = True
        elif event == cv2.EVENT_LBUTTONUP:
            self._pressed = False
        if self.mouse_listener:
            inside = self.cam_rect.contains(x, y)
            self.mouse_listener(x / CAM_W, y / CAM_H, inside, self._pressed and inside)

    def pop_estop_click(self) -> bool:
        c, self.estop_clicked = self.estop_clicked, False
        return c

    # --- gambar -------------------------------------------------------------
    def render(self, frame, feats, info: ViewInfo):
        canvas = np.full((H, W, 3), C_BG, np.uint8)
        self._draw_camera(canvas, frame, feats, info)
        self._draw_bottom(canvas, info)
        self._draw_panel(canvas, info)
        return canvas

    def _draw_camera(self, canvas, frame, feats, info):
        if frame is not None:
            cam = cv2.resize(frame, (CAM_W, CAM_H))
        else:
            cam = np.zeros((CAM_H, CAM_W, 3), np.uint8)
            _text_center(cam, "Kamera tidak tersedia", CAM_W // 2, CAM_H // 2, 1.0, C_DIM)
        canvas[0:CAM_H, 0:CAM_W] = cam

        # kotak area interaksi (dari mapping.x_range / y_range)
        m = self.cfg.mapping
        x0, x1 = sorted(m.x_range)
        y0, y1 = sorted(m.y_range)
        color = STATE_COLORS[info.state]
        p0 = (int(x0 * CAM_W), int(y0 * CAM_H))
        p1 = (int(x1 * CAM_W), int(y1 * CAM_H))
        cv2.rectangle(canvas, p0, p1, color, 2, AA)
        _text(canvas, "AREA INTERAKSI", (p0[0] + 6, p0[1] + 22), 0.55, color, 1)

        if feats.visible:
            pts = [(int(px * CAM_W), int(py * CAM_H)) for px, py in feats.landmarks]
            if len(pts) == 21:
                for a, b in HAND_CONNECTIONS:
                    cv2.line(canvas, pts[a], pts[b], (230, 230, 230), 2, AA)
                for i, p in enumerate(pts):
                    cv2.circle(canvas, p, 6 if i in (4, 8, 9) else 3,
                               C_ACCENT if i in (4, 8) else C_ARM, -1, AA)
                closed = info.target_joint[2] == 1
                cv2.line(canvas, pts[4], pts[8], C_GRIP if closed else C_DIM, 2, AA)
            else:
                # tangan virtual (mouse/demo): gambar kursor
                c = (int(feats.x * CAM_W), int(feats.y * CAM_H))
                closed = info.target_joint[2] == 1
                cv2.circle(canvas, c, 26, C_GRIP if closed else C_ARM, 3, AA)
                gap = 6 if closed else 18
                cv2.line(canvas, (c[0] - gap, c[1] - 34), (c[0] - gap, c[1] - 12), C_TEXT, 3, AA)
                cv2.line(canvas, (c[0] + gap, c[1] - 34), (c[0] + gap, c[1] - 12), C_TEXT, 3, AA)
                cv2.circle(canvas, c, 4, C_TEXT, -1, AA)
            if info.filtered_xy is not None:
                fxp = (int(info.filtered_xy[0] * CAM_W), int(info.filtered_xy[1] * CAM_H))
                cv2.drawMarker(canvas, fxp, C_YELLOW, cv2.MARKER_CROSS, 22, 2, AA)

        # info pojok kamera
        _text(canvas, f"{info.source_name}   FPS {info.fps:4.1f}", (12, 26), 0.6, C_TEXT, 2)
        if info.calib:
            self._draw_calib(canvas, feats, info)

    def _draw_calib(self, canvas, feats, info):
        m = self.cfg.mapping
        box = (10, 40, 400, 170)
        overlay = canvas.copy()
        cv2.rectangle(overlay, box[:2], (box[0] + box[2], box[1] + box[3]), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, canvas, 0.4, 0, canvas)
        y = box[1] + 26
        _text(canvas, "MODE KALIBRASI (tekan c untuk tutup)", (20, y), 0.55, C_YELLOW, 1)
        if feats.visible:
            lines = [f"x mentah = {feats.x:.3f}   y mentah = {feats.y:.3f}",
                     f"pinch = {feats.pinch:.3f}  (tutup<{m.pinch_close}  buka>{m.pinch_open})",
                     f"yaw = {info.target_joint[0]:+.1f} deg   pitch = {info.target_joint[1]:+.1f} deg",
                     f"servo A {info.target_servo[0]} {info.target_servo[1]} {info.target_servo[2]}"]
        else:
            lines = ["tangan tidak terdeteksi"]
        for s in lines:
            y += 26
            _text(canvas, s, (20, y), 0.55, C_TEXT, 1)
        if feats.visible:   # bar pinch
            bx, by, bw = 20, box[1] + box[3] - 18, 370
            cv2.rectangle(canvas, (bx, by), (bx + bw, by + 10), C_GRID, -1)
            val = min(feats.pinch, 1.0)
            cv2.rectangle(canvas, (bx, by), (bx + int(bw * val), by + 10), C_ACCENT, -1)
            for th, col in ((m.pinch_close, C_GRIP), (m.pinch_open, C_RED)):
                tx = bx + int(bw * min(th, 1.0))
                cv2.line(canvas, (tx, by - 4), (tx, by + 14), col, 2)

    def _draw_bottom(self, canvas, info):
        color = STATE_COLORS[info.state]
        cv2.rectangle(canvas, (0, CAM_H), (CAM_W, H), C_PANEL, -1)
        cv2.rectangle(canvas, (0, CAM_H), (14, H), color, -1)
        _text(canvas, info.state.value, (36, CAM_H + 78), 2.2, color, 5)
        _text(canvas, STATE_TEXT[info.state], (36, CAM_H + 130), 0.85, C_TEXT, 2)
        _text(canvas, "Space: E-STOP   c: kalibrasi   f: fullscreen   q: keluar"
              + ("   u: cabut/colok kabel (sim)" if info.mode_label == "SIMULASI" else ""),
              (36, H - 14), 0.5, C_DIM, 1)

    def _draw_panel(self, canvas, info):
        x0 = PANEL_X
        cv2.rectangle(canvas, (x0, 0), (W, H), C_PANEL, -1)
        cv2.line(canvas, (x0, 0), (x0, H), C_GRID, 2)
        mode_col = C_YELLOW if info.mode_label == "SIMULASI" else C_GREEN
        _text(canvas, f"MODE {info.mode_label}", (x0 + 16, 30), 0.75, mode_col, 2)

        top = Rect(x0 + 10, 44, 300, 200)
        side = Rect(x0 + 10, 254, 300, 190)
        self._draw_top_view(canvas, top, info)
        self._draw_side_view(canvas, side, info)

        # status
        y = 470
        dot = C_GREEN if info.link_ok else C_RED
        cv2.circle(canvas, (x0 + 24, y - 6), 7, dot, -1, AA)
        _text(canvas, info.link_status[:34], (x0 + 38, y), 0.5, C_TEXT, 1)
        b, l, g = info.actual_servo
        tb, tl, tg = info.target_servo
        _text(canvas, f"servo  base  lengan  grip", (x0 + 16, y + 26), 0.48, C_DIM, 1)
        _text(canvas, f"target {tb:5d} {tl:6d}   {'TUTUP' if tg else 'BUKA'}", (x0 + 16, y + 48), 0.48, C_TEXT, 1)
        _text(canvas, f"posisi {b:5.0f} {l:6.0f}   {g:4.0f}deg", (x0 + 16, y + 70), 0.48, C_ARM, 1)
        for i, s in enumerate(info.log[-2:]):
            _text(canvas, s[:36], (x0 + 16, y + 92 + 18 * i), 0.42, C_DIM, 1)

        # tombol E-STOP
        r = self.estop_btn
        active = info.state == State.ESTOP
        cv2.rectangle(canvas, (r.x, r.y), (r.x + r.w, r.y + r.h), C_RED, -1 if not active else 4, AA)
        _text_center(canvas, "LANJUT" if active else "E-STOP", r.x + r.w // 2, r.y + 64,
                     1.5, C_TEXT if not active else C_RED, 4)

    # --- visual robot -------------------------------------------------------
    def _draw_top_view(self, canvas, r: Rect, info):
        cv2.rectangle(canvas, (r.x, r.y), (r.x + r.w, r.y + r.h), C_BG, -1)
        _text(canvas, "Tampak atas (base)", (r.x + 8, r.y + 20), 0.5, C_DIM, 1)
        L = self.cfg.geometry.L
        cx, cy = r.x + r.w // 2, r.y + r.h - 22
        scale = (r.h - 50) / L
        rad = int(L * scale)
        # rentang yaw yang diizinkan
        yaw_lo, yaw_hi = sorted(self.cfg.mapping.yaw_range)
        cv2.ellipse(canvas, (cx, cy), (rad, rad), 0, -90 - yaw_hi, -90 - yaw_lo, C_GRID, 1, AA)
        for a in (yaw_lo, yaw_hi):
            ex = int(cx - math.sin(math.radians(a)) * rad)
            ey = int(cy - math.cos(math.radians(a)) * rad)
            cv2.line(canvas, (cx, cy), (ex, ey), C_GRID, 1, AA)

        def tip(yaw, pitch):
            reach = L * math.cos(math.radians(pitch)) * scale
            return (int(cx - math.sin(math.radians(yaw)) * reach),
                    int(cy - math.cos(math.radians(yaw)) * reach))

        ty, tp, _ = info.target_joint
        cv2.line(canvas, (cx, cy), tip(ty, tp), C_GHOST, 2, AA)
        ay, ap, ag = info.actual_joint
        t = tip(ay, ap)
        cv2.line(canvas, (cx, cy), t, C_ARM, 8, AA)
        cv2.circle(canvas, (cx, cy), 16, (110, 100, 95), -1, AA)
        cv2.circle(canvas, t, 7, C_GRIP if ag > 0.5 else C_TEXT, -1, AA)
        _text(canvas, f"yaw {ay:+5.1f}", (r.x + r.w - 92, r.y + 20), 0.5, C_ARM, 1)

    def _draw_side_view(self, canvas, r: Rect, info):
        cv2.rectangle(canvas, (r.x, r.y), (r.x + r.w, r.y + r.h), C_BG, -1)
        _text(canvas, "Tampak samping (lengan)", (r.x + 8, r.y + 20), 0.5, C_DIM, 1)
        g = self.cfg.geometry
        L, H0 = g.L, g.H0
        scale = min((r.w - 70) / (L * 1.15), (r.h - 40) / (H0 + L * 1.05))
        table_y = r.y + r.h - 12
        bx = r.x + 50
        ax, ay_ = bx, int(table_y - H0 * scale)
        cv2.line(canvas, (r.x + 6, table_y), (r.x + r.w - 6, table_y), C_DIM, 2)     # meja
        cv2.rectangle(canvas, (bx - 14, ay_), (bx + 14, table_y), (110, 100, 95), -1)  # base
        rad = int(L * scale)
        p_lo, p_hi = self.cfg.mapping.pitch_range
        cv2.ellipse(canvas, (ax, ay_), (rad, rad), 0, -p_hi, -p_lo, C_GRID, 1, AA)    # kubah

        def tip(pitch):
            return (int(ax + math.cos(math.radians(pitch)) * rad),
                    int(ay_ - math.sin(math.radians(pitch)) * rad))

        _, tp, _ = info.target_joint
        cv2.line(canvas, (ax, ay_), tip(tp), C_GHOST, 2, AA)
        _, ap, ag = info.actual_joint
        t = tip(ap)
        cv2.line(canvas, (ax, ay_), t, C_ARM, 8, AA)
        cv2.circle(canvas, (ax, ay_), 8, C_TEXT, -1, AA)
        # gripper: dua rahang, bukaan sesuai ag (0 buka .. 1 tutup)
        ang = math.radians(ap)
        ux, uy = math.cos(ang), -math.sin(ang)       # arah lengan (layar)
        nx, ny = -uy, ux                             # normal
        open_px = 4 + (1 - ag) * 12
        col = C_GRIP if ag > 0.5 else C_TEXT
        for sgn in (1, -1):
            p0 = (int(t[0] + nx * open_px * sgn), int(t[1] + ny * open_px * sgn))
            p1 = (int(p0[0] + ux * 16), int(p0[1] + uy * 16))
            cv2.line(canvas, p0, p1, col, 4, AA)
        z = H0 + L * math.sin(ang)
        _text(canvas, f"pitch {ap:+5.1f}  z {z:4.1f}cm", (r.x + 8, r.y + 42), 0.48, C_ARM, 1)
