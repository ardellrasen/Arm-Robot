import pytest

from app import kinematics
from app.config import ConfigError, Config, config_from_dict
from app.mapping import GripHysteresis, HandMapper, lin_map, x_to_yaw, y_to_pitch


def cfg(**mapping):
    return config_from_dict({"mapping": mapping}) if mapping else Config()


def test_lin_map_reversed_and_clamped():
    assert lin_map(0.5, (0.15, 0.85), (60, -60)) == pytest.approx(0)
    assert lin_map(0.15, (0.15, 0.85), (60, -60)) == pytest.approx(60)
    assert lin_map(0.0, (0.15, 0.85), (60, -60)) == pytest.approx(60)     # clamp
    assert lin_map(1.0, (0.15, 0.85), (60, -60)) == pytest.approx(-60)    # clamp


def test_x_to_yaw_left_is_positive():
    c = cfg()
    assert x_to_yaw(0.2, c.mapping) > 0
    assert x_to_yaw(0.8, c.mapping) < 0
    assert x_to_yaw(-5, c.mapping) == pytest.approx(60)


def test_y_height_mode_linear_in_height():
    c = cfg()
    m, g = c.mapping, c.geometry
    z_lo, z_hi = kinematics.height_limits(g.L, g.H0, *m.pitch_range)
    # bawah frame (y=0.85) -> pitch minimum, atas (y=0.15) -> pitch maksimum
    assert y_to_pitch(0.85, m, g) == pytest.approx(m.pitch_range[0])
    assert y_to_pitch(0.15, m, g) == pytest.approx(m.pitch_range[1])
    assert y_to_pitch(2.0, m, g) == pytest.approx(m.pitch_range[0])        # clamp
    # tengah frame -> tinggi tengah (linear di tinggi, bukan di sudut)
    p_mid = y_to_pitch(0.5, m, g)
    assert kinematics.pitch_to_height(p_mid, g.L, g.H0) == pytest.approx((z_lo + z_hi) / 2)


def test_y_angle_mode():
    c = cfg(y_mode="angle")
    assert y_to_pitch(0.5, c.mapping, c.geometry) == pytest.approx(15.0)


def test_grip_hysteresis():
    h = GripHysteresis(0.35, 0.50)
    assert h.update(0.8) == 0
    assert h.update(0.40) == 0      # di zona tengah -> tetap buka
    assert h.update(0.30) == 1      # tutup
    assert h.update(0.45) == 1      # zona tengah -> tetap tutup (tidak berkedip)
    assert h.update(0.49) == 1
    assert h.update(0.55) == 0      # buka
    assert h.update(0.40) == 0


def test_hand_mapper():
    c = cfg()
    hm = HandMapper(c.mapping, c.geometry)
    cmd = hm.map(0.5, 0.15, 0.1)
    assert cmd.yaw == pytest.approx(0)
    assert cmd.pitch == pytest.approx(60)
    assert cmd.grip == 1


def test_config_rejects_bad_hysteresis():
    with pytest.raises(ConfigError):
        config_from_dict({"mapping": {"pinch_close": 0.6, "pinch_open": 0.5}})


def test_config_rejects_unknown_key():
    with pytest.raises(ConfigError):
        config_from_dict({"mapping": {"typo_key": 1}})


def test_default_config_file_loads():
    from app.config import load_config
    c = load_config()
    assert c.geometry.L > 0
