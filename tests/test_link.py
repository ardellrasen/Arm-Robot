"""Tes VirtualESP32 (tiruan firmware) dan MockLink - memastikan mode simulasi berperilaku seperti robot asli."""
import re
from pathlib import Path

import pytest

from app.config import Config
from app.link import FirmwareParams, MockLink, VirtualESP32
from app.servo_map import ServoAngles
from app.state import State, StateMachine


def test_boot_and_ping():
    d = VirtualESP32(now=0)
    assert d.reset(0) == ["READY"]
    assert d.handle_line("P", 0) == ["OK"]
    assert d.position() == (90, 90, 20)


def test_rate_limit_3_deg_per_tick():
    d = VirtualESP32(now=0)
    assert d.handle_line("A 120 90 0", 0) == []
    d.advance(0.0)          # 1 tick
    assert d.position()[0] == 93
    d.advance(0.2)          # total 11 tick -> 90 + 33 = 123 -> dibatasi target 120
    assert d.position()[0] == 120


def test_clamp_in_firmware():
    d = VirtualESP32(now=0)
    d.handle_line("A 0 180 1", 0)
    assert d.target == [20, 160, 80]


def test_bad_lines_return_err():
    d = VirtualESP32(now=0)
    for bad in ("A 1 2", "A x 2 3", "A 90 90 5", "Z", "S 0", "G 10 999"):
        r = d.handle_line(bad, 0)
        assert len(r) == 1 and r[0].startswith("ERR"), bad


def test_speed_command():
    d = VirtualESP32(now=0)
    assert d.handle_line("S 10", 0) == ["OK"]
    d.handle_line("A 150 90 0", 0)
    d.advance(0.0)
    assert d.position()[0] == 100


def test_watchdog_hold_then_home():
    d = VirtualESP32(now=0)
    d.handle_line("A 150 90 0", 0)
    d.advance(0.2)                     # sedang bergerak
    pos_mid = d.position()[0]
    assert 90 < pos_mid < 150
    d.advance(1.1)                     # > 1 s tanpa A -> tahan posisi
    assert d.watchdog_state == "hold"
    held = d.position()[0]
    d.advance(5.0)
    assert d.position()[0] == held     # tidak bergerak
    d.advance(10.5)                    # > 10 s -> pulang pelan
    assert d.watchdog_state == "home"
    d.advance(30.0)
    assert d.position() == (90, 90, 20)


def test_home_command_is_slow():
    d = VirtualESP32(now=0)
    d.handle_line("A 150 90 0", 0)
    d.advance(1.0)
    assert d.position()[0] == 150
    d.handle_line("H", 1.0)
    d.advance(1.1)                     # ~5 tick @ 1 derajat (bukan 3)
    assert 144 <= d.position()[0] <= 146


def test_grip_angles_command():
    d = VirtualESP32(now=0)
    d.handle_line("A 90 90 1", 0)
    assert d.handle_line("G 30 100", 0) == ["OK"]
    assert d.target[2] == 100          # tetap tertutup, pakai sudut baru


def test_mocklink_keepalive_and_change_only():
    link = MockLink(Config())
    link.update(0.0)
    a = ServoAngles(100, 90, 0)
    assert link.send_angles(a, 1.0) is True
    assert link.send_angles(a, 1.05) is False      # sama & < 200 ms -> tidak dikirim
    assert link.send_angles(a, 1.25) is True       # keep-alive
    assert link.send_angles(ServoAngles(101, 90, 0), 1.26) is True   # berubah -> kirim


def test_firmware_constants_match_python():
    """Konstanta di firmware/src/main.cpp harus sama dengan FirmwareParams (simulasi)."""
    src = (Path(__file__).resolve().parent.parent / "firmware" / "src" / "main.cpp").read_text()
    p = FirmwareParams()

    def num(name):
        return int(re.search(rf"{name}\s*=\s*(\d+)", src).group(1))

    def arr(name):
        return tuple(int(v) for v in re.search(rf"{name}\[3\]\s*=\s*\{{([^}}]*)\}}", src).group(1).split(","))

    assert arr("MIN_DEG") == p.min_deg
    assert arr("MAX_DEG") == p.max_deg
    assert (num("HOME_BASE"), num("HOME_LENGAN")) == p.home
    assert (num("gripOpenDeg"), num("gripCloseDeg")) == (p.grip_open, p.grip_close)
    assert num("DEFAULT_MAX_STEP") == p.max_step
    assert num("HOME_STEP") == p.home_step
    assert num("HOLD_TIMEOUT_MS") == p.hold_timeout_ms
    assert num("HOME_TIMEOUT_MS") == p.home_timeout_ms


def test_state_machine():
    sm = StateMachine(idle_timeout_s=3)
    assert sm.update(False, 0) == State.IDLE
    assert sm.update(True, 1) == State.LIVE
    assert sm.update(False, 2) == State.LIVE       # hilang sebentar -> tetap LIVE
    assert sm.update(False, 4.5) == State.IDLE
    sm.update(True, 5)
    sm.toggle_estop()
    assert sm.update(True, 6) == State.ESTOP       # tangan tidak bisa membatalkan E-STOP
    sm.toggle_estop()
    assert sm.state == State.IDLE
