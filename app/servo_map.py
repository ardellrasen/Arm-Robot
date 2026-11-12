"""Sudut sendi -> sudut servo (offset, arah, batas). Logika pure."""
from __future__ import annotations

from dataclasses import dataclass

from .config import GripServoCfg, JointServoCfg, ServosCfg
from .mapping import JointCommand


@dataclass(frozen=True)
class ServoAngles:
    base: int     # derajat servo 0..180
    lengan: int   # derajat servo 0..180
    grip: int     # 0 = buka, 1 = tutup (sesuai protokol serial)

    def as_command(self) -> str:
        return f"A {self.base} {self.lengan} {self.grip}"


def joint_to_servo(joint_deg: float, s: JointServoCfg) -> int:
    """servo_deg = offset + sign * joint_deg, lalu clamp ke [min, max]."""
    raw = s.offset + s.sign * joint_deg
    return int(round(min(max(raw, s.min), s.max)))


def servo_to_joint(servo_deg: float, s: JointServoCfg) -> float:
    """Kebalikan joint_to_servo (dipakai visualisasi dari sudut servo)."""
    return (servo_deg - s.offset) * s.sign


def grip_to_servo_deg(grip: float, g: GripServoCfg) -> float:
    """grip 0..1 -> sudut servo gripper (boleh pecahan untuk animasi)."""
    return g.open + (g.close - g.open) * grip


def servo_deg_to_grip(servo_deg: float, g: GripServoCfg) -> float:
    """Sudut servo gripper -> 0 (buka) .. 1 (tutup)."""
    if g.close == g.open:
        return 0.0
    t = (servo_deg - g.open) / (g.close - g.open)
    return min(max(t, 0.0), 1.0)


def to_servo(cmd: JointCommand, s: ServosCfg) -> ServoAngles:
    return ServoAngles(
        base=joint_to_servo(cmd.yaw, s.base),
        lengan=joint_to_servo(cmd.pitch, s.lengan),
        grip=1 if cmd.grip else 0,
    )


def home_angles(s: ServosCfg) -> ServoAngles:
    """Pose home = sendi di 0 derajat, gripper buka."""
    return to_servo(JointCommand(0.0, 0.0, 0), s)
