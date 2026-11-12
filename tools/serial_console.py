"""Console manual untuk ESP32.

  python tools/serial_console.py --port COM5     # robot asli
  python tools/serial_console.py --mock          # simulasi (VirtualESP32)

Ketik perintah protokol, mis.:  A 90 90 0   A 120 60 1   H   P   S 2   G 20 80
Perintah lokal: 'pos' (simulasi: tampilkan posisi servo), 'quit'.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config  # noqa: E402
from app.link import VirtualESP32  # noqa: E402


class SimDevice:
    def __init__(self):
        self.dev = VirtualESP32()
        print("< READY   (simulasi)")
        self._stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self._stop:
            self.dev.advance(time.monotonic())
            time.sleep(0.01)

    def send(self, line: str):
        for r in self.dev.handle_line(line, time.monotonic()):
            print(f"< {r}")

    def extra(self, line: str) -> bool:
        if line == "pos":
            b, l, g = self.dev.position()
            print(f"  posisi servo: base={b:.0f} lengan={l:.0f} grip={g:.0f}  "
                  f"(watchdog: {self.dev.watchdog_state})")
            return True
        return False

    def close(self):
        self._stop = True


class RealDevice:
    def __init__(self, port: str, baud: int):
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.1)
        print(f"Terhubung ke {port} @ {baud}. Menunggu READY (ESP32 biasanya reset saat port dibuka)...")
        self._stop = False
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        buf = b""
        while not self._stop:
            try:
                buf += self.ser.read(256)
            except Exception as e:
                print(f"[ERROR] {e}")
                return
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                s = raw.decode("ascii", errors="replace").strip()
                if s:
                    print(f"< {s}")

    def send(self, line: str):
        self.ser.write((line + "\n").encode("ascii"))

    def extra(self, line: str) -> bool:
        return False

    def close(self):
        self._stop = True
        self.ser.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--config")
    a = p.parse_args()
    cfg = load_config(a.config)
    dev = SimDevice() if a.mock else RealDevice(a.port or cfg.serial.port, cfg.serial.baud)
    print("Ketik perintah (quit untuk keluar). Ingat: tanpa perintah A selama 1 s robot menahan "
          "posisi, 10 s pulang ke home.")
    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                break
            if not dev.extra(line.lower()):
                dev.send(line)
                time.sleep(0.05)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        dev.close()


if __name__ == "__main__":
    main()
