"""Logika kontrol per frame (tidak tergantung UI): filter -> mapping -> state machine -> link.

Dipakai oleh UI web (digital twin) maupun UI OpenCV lama.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import kinematics, servo_map
from .config import Config
from .filters import make_filter
from .link import LinkBase
from .mapping import HandMapper, JointCommand
from .servo_map import ServoAngles
from .state import State, StateMachine
from .tracker import HandFeatures


@dataclass
class Telemetry:
    t: float
    state: State
    hand: HandFeatures
    filtered_xy: tuple | None
    target: ServoAngles
    actual_servo: tuple            # (base_deg, lengan_deg, grip_deg) perkiraan posisi nyata
    target_joint: JointCommand
    actual_joint: tuple            # (yaw, pitch, grip 0..1)
    tip: tuple                     # FK ujung gripper (x, y, z) cm, posisi nyata
    link_ok: bool
    link_status: str
    calib: bool
    log: list = field(default_factory=list)

    def to_dict(self, fps: float, mode_label: str, source_name: str) -> dict:
        h = self.hand
        tj = self.target_joint
        return {
            "t": round(self.t, 3),
            "state": self.state.name,
            "mode": mode_label,
            "source": source_name,
            "fps": round(fps, 1),
            "link": {"ok": self.link_ok, "text": self.link_status},
            "hand": {
                "visible": h.visible,
                "x": round(h.x, 4), "y": round(h.y, 4), "pinch": round(h.pinch, 3),
                "lm": [[round(a, 4), round(b, 4)] for a, b in h.landmarks] if h.visible else [],
                "f": [round(v, 4) for v in self.filtered_xy] if self.filtered_xy else None,
            },
            "target": {"base": self.target.base, "lengan": self.target.lengan, "grip": self.target.grip},
            "actual": {"base": round(self.actual_servo[0], 1), "lengan": round(self.actual_servo[1], 1),
                       "grip": round(self.actual_servo[2], 1)},
            "jt": {"yaw": round(tj.yaw, 2), "pitch": round(tj.pitch, 2), "grip": tj.grip},
            "ja": {"yaw": round(self.actual_joint[0], 2), "pitch": round(self.actual_joint[1], 2),
                   "grip": round(self.actual_joint[2], 3)},
            "tip": [round(v, 2) for v in self.tip],
            "calib": self.calib,
            "log": self.log[-8:],
        }


class Controller:
    def __init__(self, cfg: Config, link: LinkBase):
        self.cfg = cfg
        self.link = link
        self.fx, self.fy = make_filter(cfg.filter), make_filter(cfg.filter)
        self.mapper = HandMapper(cfg.mapping, cfg.geometry)
        self.sm = StateMachine(cfg.ui.idle_timeout_s)
        self.home = servo_map.home_angles(cfg.servos)
        self.target: ServoAngles = self.home
        self.joint_cmd = JointCommand(0.0, 0.0, 0)
        self.filtered_xy = None
        self.calib = False

    def toggle_estop(self) -> None:
        self.sm.toggle_estop()

    def toggle_calib(self) -> None:
        self.calib = not self.calib

    def _grip_from_deg(self, deg: float) -> int:
        return 1 if servo_map.servo_deg_to_grip(deg, self.cfg.servos.grip) > 0.5 else 0

    def step(self, feats: HandFeatures, now: float | None = None) -> Telemetry:
        now = time.monotonic() if now is None else now
        cfg, link = self.cfg, self.link
        link.update(now)
        state = self.sm.update(feats.visible, now)
        entered = self.sm.pop_changed()

        if state == State.LIVE:
            if feats.visible:
                x, y = self.fx(feats.x, now), self.fy(feats.y, now)
                self.filtered_xy = (x, y)
                self.joint_cmd = self.mapper.map(x, y, feats.pinch)
                self.target = servo_map.to_servo(self.joint_cmd, cfg.servos)
            # tangan hilang sebentar -> tetap kirim target terakhir (tahan posisi)
            link.send_angles(self.target, now)
        elif state == State.IDLE:
            if entered:
                link.home()                      # firmware pulang pelan ke home
                self.fx.reset(); self.fy.reset()
                self.mapper.grip.state = 0
                self.target, self.joint_cmd, self.filtered_xy = self.home, JointCommand(0.0, 0.0, 0), None
        elif state == State.ESTOP:
            if entered:
                b, l, g = link.estimated_position()
                self.target = ServoAngles(int(round(b)), int(round(l)), self._grip_from_deg(g))
                self.joint_cmd = JointCommand(
                    servo_map.servo_to_joint(self.target.base, cfg.servos.base),
                    servo_map.servo_to_joint(self.target.lengan, cfg.servos.lengan),
                    self.target.grip)
            link.send_angles(self.target, now)   # keep-alive agar robot diam di posisi ini

        b, l, g = link.estimated_position()
        yaw = servo_map.servo_to_joint(b, cfg.servos.base)
        pitch = servo_map.servo_to_joint(l, cfg.servos.lengan)
        grip = servo_map.servo_deg_to_grip(g, cfg.servos.grip)
        return Telemetry(
            t=now, state=state, hand=feats,
            filtered_xy=self.filtered_xy if feats.visible else None,
            target=self.target, actual_servo=(b, l, g),
            target_joint=self.joint_cmd, actual_joint=(yaw, pitch, grip),
            tip=kinematics.forward(yaw, pitch, cfg.geometry.L, cfg.geometry.H0),
            link_ok=link.connected, link_status=link.status_text,
            calib=self.calib, log=list(link.log),
        )
