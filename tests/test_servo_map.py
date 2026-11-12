import pytest

from app.config import GripServoCfg, JointServoCfg, ServosCfg
from app.mapping import JointCommand
from app.servo_map import (grip_to_servo_deg, home_angles, joint_to_servo, servo_deg_to_grip,
                           servo_to_joint, to_servo)


def test_offset_and_sign():
    s = JointServoCfg(offset=90, sign=1, min=20, max=160)
    assert joint_to_servo(0, s) == 90
    assert joint_to_servo(30, s) == 120
    s_neg = JointServoCfg(offset=90, sign=-1, min=20, max=160)
    assert joint_to_servo(30, s_neg) == 60


def test_servo_limits_clamped():
    s = JointServoCfg(offset=90, sign=1, min=30, max=160)
    assert joint_to_servo(100, s) == 160
    assert joint_to_servo(-100, s) == 30


@pytest.mark.parametrize("sign", [1, -1])
def test_inverse(sign):
    s = JointServoCfg(offset=85, sign=sign, min=0, max=180)
    for j in (-40, 0, 25, 60):
        assert servo_to_joint(joint_to_servo(j, s), s) == pytest.approx(j)


def test_grip():
    g = GripServoCfg(open=20, close=80)
    assert grip_to_servo_deg(0, g) == 20
    assert grip_to_servo_deg(1, g) == 80
    assert servo_deg_to_grip(50, g) == pytest.approx(0.5)
    assert servo_deg_to_grip(200, g) == 1.0


def test_to_servo_and_command():
    s = ServosCfg()
    a = to_servo(JointCommand(yaw=30, pitch=-10, grip=1), s)
    assert a.as_command() == "A 120 80 1"
    assert home_angles(s).as_command() == "A 90 90 0"


def test_calibration_writes_config_and_keeps_comments():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from calibrate_servo import update_config_text
    text = (Path(__file__).resolve().parent.parent / "config" / "config.yaml").read_text(encoding="utf-8")
    new = update_config_text(text, {"base": {"offset": 95, "sign": -1, "min": 25, "max": 150},
                                    "lengan": {"offset": 88, "sign": 1, "min": 35, "max": 155},
                                    "grip": {"open": 15, "close": 75}})
    assert "base:   {offset: 95, sign: -1, min: 25, max: 150}" in new
    assert "grip:   {open: 15, close: 75}" in new
    assert "# servo_deg = offset" in new
