"""Mapping fitur tangan (x, y, pinch) -> perintah sendi (yaw, pitch, grip). Logika pure."""
from __future__ import annotations

from dataclasses import dataclass

from . import kinematics
from .config import GeometryCfg, MappingCfg


@dataclass
class JointCommand:
    yaw: float      # derajat
    pitch: float    # derajat
    grip: int       # 0 = buka, 1 = tutup


def lin_map(v: float, in_range, out_range) -> float:
    """Map linear dengan clamp. Mendukung rentang terbalik (mis. [0.85, 0.15])."""
    a, b = in_range
    c, d = out_range
    t = (v - a) / (b - a)
    t = min(max(t, 0.0), 1.0)
    return c + t * (d - c)


class GripHysteresis:
    """pinch < close -> tutup (1); pinch > open -> buka (0); di antaranya -> tetap."""

    def __init__(self, pinch_close: float, pinch_open: float, initial: int = 0):
        if not pinch_close < pinch_open:
            raise ValueError("pinch_close harus < pinch_open")
        self.pinch_close = pinch_close
        self.pinch_open = pinch_open
        self.state = initial

    def update(self, pinch: float) -> int:
        if pinch < self.pinch_close:
            self.state = 1
        elif pinch > self.pinch_open:
            self.state = 0
        return self.state


def x_to_yaw(x: float, m: MappingCfg) -> float:
    return lin_map(x, m.x_range, m.yaw_range)


def y_to_pitch(y: float, m: MappingCfg, g: GeometryCfg) -> float:
    p_lo, p_hi = m.pitch_range
    if m.y_mode == "angle":
        return lin_map(y, m.y_range, (p_lo, p_hi))
    # mode "height": y -> tinggi ujung gripper (linear), lalu tinggi -> pitch
    z_lo, z_hi = kinematics.height_limits(g.L, g.H0, p_lo, p_hi)
    z = lin_map(y, m.y_range, (z_lo, z_hi))
    return kinematics.height_to_pitch(z, g.L, g.H0, p_lo, p_hi)


class HandMapper:
    def __init__(self, m: MappingCfg, g: GeometryCfg):
        self.m = m
        self.g = g
        self.grip = GripHysteresis(m.pinch_close, m.pinch_open)

    def map(self, x: float, y: float, pinch: float) -> JointCommand:
        return JointCommand(
            yaw=x_to_yaw(x, self.m),
            pitch=y_to_pitch(y, self.m, self.g),
            grip=self.grip.update(pinch),
        )
