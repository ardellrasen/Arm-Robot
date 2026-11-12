"""Tes jalur MODE ASLI (SerialLink) memakai port serial palsu yang di belakangnya adalah VirtualESP32.
Membuktikan: tunggu READY -> kirim setup (S, G) -> perintah A sampai ke 'ESP32' -> auto-reconnect."""
import threading
import time

from app.config import Config
from app.link import SerialLink, VirtualESP32
from app.servo_map import ServoAngles


class FakeSerial:
    def __init__(self):
        self.dev = VirtualESP32()
        self.out = bytearray(b"READY\n")
        self.lines = []
        self.lock = threading.Lock()
        self.broken = False

    def read(self, n):
        if self.broken:
            raise OSError("kabel dicabut")
        time.sleep(0.005)
        with self.lock:
            data, self.out[:] = bytes(self.out[:n]), self.out[n:]
        return data

    def write(self, data):
        if self.broken:
            raise OSError("kabel dicabut")
        for line in data.decode().splitlines():
            self.lines.append(line)
            with self.lock:
                for r in self.dev.handle_line(line):
                    self.out += (r + "\n").encode()

    def close(self):
        pass


def wait_for(cond, timeout=2.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_serial_link_end_to_end(monkeypatch):
    fakes = []

    def fake_open(self):
        f = FakeSerial()
        fakes.append(f)
        with self._lock:
            self._ser = f
            self._ready = False

    monkeypatch.setattr(SerialLink, "_open", fake_open)
    link = SerialLink(Config(), port="FAKE")
    try:
        assert wait_for(lambda: (link.update(), link.connected)[1])
        link.update()                                   # kirim setup
        assert "S 3" in fakes[0].lines and "G 20 80" in fakes[0].lines
        assert link.send_angles(ServoAngles(120, 60, 1))
        assert fakes[0].lines[-1] == "A 120 60 1"
        assert fakes[0].dev.target == [120, 60, 80]

        # cabut kabel -> link putus -> sambung lagi otomatis
        fakes[0].broken = True
        assert wait_for(lambda: len(fakes) >= 2, timeout=3.0)
        assert wait_for(lambda: (link.update(), link.connected)[1])
        link.update()
        assert link.send_angles(ServoAngles(100, 90, 0))
        assert fakes[-1].lines[-1] == "A 100 90 0"
    finally:
        link.close()
