import math

import pytest

from app import kinematics as k

L, H0 = 10.0, 6.0
P_LO, P_HI = -30.0, 60.0


def test_height_limits():
    lo, hi = k.height_limits(L, H0, P_LO, P_HI)
    assert lo == pytest.approx(H0 - 5.0)
    assert hi == pytest.approx(H0 + L * math.sin(math.radians(60)))


@pytest.mark.parametrize("pitch", [-30, -10, 0, 15, 45, 60])
def test_height_pitch_roundtrip(pitch):
    z = k.pitch_to_height(pitch, L, H0)
    assert k.height_to_pitch(z, L, H0, P_LO, P_HI) == pytest.approx(pitch, abs=1e-9)


def test_height_out_of_range_is_clamped():
    assert k.height_to_pitch(1000, L, H0, P_LO, P_HI) == pytest.approx(P_HI)
    assert k.height_to_pitch(-1000, L, H0, P_LO, P_HI) == pytest.approx(P_LO)


def test_forward_home_and_yaw():
    x, y, z = k.forward(0, 0, L, H0)
    assert (x, y, z) == pytest.approx((L, 0, H0))
    x, y, z = k.forward(90, 0, L, H0)        # yaw +90 = ke kiri (+y)
    assert (x, y, z) == pytest.approx((0, L, H0), abs=1e-9)
    x, y, z = k.forward(0, 90, L, H0)
    assert (x, y, z) == pytest.approx((0, 0, H0 + L), abs=1e-9)


@pytest.mark.parametrize("yaw,pitch", [(-60, -30), (0, 20), (45, 60), (30, 0)])
def test_forward_on_dome(yaw, pitch):
    x, y, z = k.forward(yaw, pitch, L, H0)
    assert math.sqrt(x * x + y * y + (z - H0) ** 2) == pytest.approx(L)


def test_height_to_pitch_to_fk_consistent():
    z_target = 9.0
    pitch = k.height_to_pitch(z_target, L, H0, P_LO, P_HI)
    assert k.forward(25, pitch, L, H0)[2] == pytest.approx(z_target)
