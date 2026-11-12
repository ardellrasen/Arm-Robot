"""Kinematika lengan 2 sendi (yaw base + pitch lengan). Semua fungsi pure, sudut dalam derajat.

Konvensi:
- yaw  = 0 -> lengan menghadap depan (+x), yaw positif = putar ke kiri (CCW dilihat dari atas).
- pitch = 0 -> lengan horizontal, pitch positif = lengan naik.
- Ujung gripper berada di permukaan "kubah" berjari-jari L berpusat di sumbu servo lengan (tinggi H0).
"""
from __future__ import annotations

import math


def height_limits(L: float, H0: float, pitch_min: float, pitch_max: float) -> tuple[float, float]:
    """Rentang tinggi ujung gripper (cm) yang bisa dicapai dalam batas pitch."""
    return (H0 + L * math.sin(math.radians(pitch_min)),
            H0 + L * math.sin(math.radians(pitch_max)))


def clamp_height(z: float, L: float, H0: float, pitch_min: float, pitch_max: float) -> float:
    z_lo, z_hi = height_limits(L, H0, pitch_min, pitch_max)
    return min(max(z, z_lo), z_hi)


def height_to_pitch(z: float, L: float, H0: float, pitch_min: float, pitch_max: float) -> float:
    """pitch = asin((z - H0) / L), dengan z di-clamp agar asin selalu valid."""
    z = clamp_height(z, L, H0, pitch_min, pitch_max)
    ratio = max(-1.0, min(1.0, (z - H0) / L))
    return math.degrees(math.asin(ratio))


def pitch_to_height(pitch: float, L: float, H0: float) -> float:
    return H0 + L * math.sin(math.radians(pitch))


def forward(yaw: float, pitch: float, L: float, H0: float) -> tuple[float, float, float]:
    """FK: posisi ujung gripper (x, y, z) dalam cm. Origin = titik di meja tepat di bawah base."""
    y_r, p_r = math.radians(yaw), math.radians(pitch)
    reach = L * math.cos(p_r)
    return (reach * math.cos(y_r), reach * math.sin(y_r), H0 + L * math.sin(p_r))
