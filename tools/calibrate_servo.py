"""Tool kalibrasi servo interaktif -> menulis offset/sign/min/max dan sudut gripper ke config.yaml.

  python tools/calibrate_servo.py --port COM5     # robot asli
  python tools/calibrate_servo.py --mock          # latihan di simulasi

Perintah:
  b | l | g        pilih servo: base / lengan / gripper
  +N  -N  =N       geser sudut servo terpilih N derajat / set ke N  (mis. +5, -1, =120)
  center           (base) sudut sekarang = lengan menghadap DEPAN -> offset
                   (lengan) sudut sekarang = lengan HORIZONTAL -> offset
  min | max        sudut sekarang = batas aman minimum / maksimum servo terpilih
  sign 1 | sign -1 arah: base -> menambah sudut memutar ke KIRI (dilihat dari atas) = 1
                         lengan -> menambah sudut MENGANGKAT lengan = 1
  test             gerakkan sendi terpilih +20 derajat (pakai kalibrasi sekarang) lalu kembali
  open | close     (gripper) sudut sekarang = posisi buka / tutup
  show             tampilkan nilai kalibrasi
  save             tulis ke config.yaml (komentar di file tetap dipertahankan)
  quit             keluar (tanpa menyimpan)
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DEFAULT_CONFIG_PATH, load_config  # noqa: E402
from app.link import make_link  # noqa: E402
from app.servo_map import ServoAngles  # noqa: E402


def update_config_text(text: str, cal: dict) -> str:
    """Ganti baris servos.base / servos.lengan / servos.grip di teks YAML, pertahankan komentar."""
    def fmt_joint(d):
        return f"{{offset: {d['offset']:g}, sign: {d['sign']}, min: {d['min']:g}, max: {d['max']:g}}}"

    repl = {
        "base": fmt_joint(cal["base"]),
        "lengan": fmt_joint(cal["lengan"]),
        "grip": f"{{open: {cal['grip']['open']:g}, close: {cal['grip']['close']:g}}}",
    }
    for key, val in repl.items():
        pattern = re.compile(rf"^(\s+{key}:\s*)\{{[^}}]*\}}", re.MULTILINE)
        text, n = pattern.subn(lambda m: m.group(1) + val, text, count=1)
        if n == 0:
            raise RuntimeError(f"Baris 'servos.{key}' tidak ditemukan di config.yaml")
    return text


class Calibrator:
    def __init__(self, cfg, link):
        s = cfg.servos
        self.cfg = cfg
        self.link = link
        self.cal = {
            "base": {"offset": s.base.offset, "sign": s.base.sign, "min": s.base.min, "max": s.base.max},
            "lengan": {"offset": s.lengan.offset, "sign": s.lengan.sign, "min": s.lengan.min, "max": s.lengan.max},
            "grip": {"open": s.grip.open, "close": s.grip.close},
        }
        self.angles = {"base": int(s.base.offset), "lengan": int(s.lengan.offset), "grip": int(s.grip.open)}
        self.sel = "base"
        self._lock = threading.Lock()
        self._stop = False
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _keepalive(self):
        # kirim posisi terus (watchdog firmware) + majukan simulasi
        last_grip = None
        while not self._stop:
            with self._lock:
                a = dict(self.angles)
            self.link.update()
            if a["grip"] != last_grip and self.link.connected:
                # gripper diatur langsung: buka = tutup = sudut yang sedang dicoba
                self.link.set_grip_angles(a["grip"], a["grip"])
                last_grip = a["grip"]
            if not self.link.connected:
                last_grip = None
            self.link.send_angles(ServoAngles(a["base"], a["lengan"], 0))
            time.sleep(0.05)

    def set_angle(self, v: int):
        with self._lock:
            self.angles[self.sel] = max(0, min(180, int(v)))

    def show(self):
        c = self.cal
        print(f"  dipilih: {self.sel}   sudut servo sekarang: {self.angles}")
        print(f"  base  : {c['base']}")
        print(f"  lengan: {c['lengan']}")
        print(f"  grip  : {c['grip']}")
        print(f"  status: {self.link.status_text}")
        if self.link.mode_name == "SIMULASI":
            b, l, g = self.link.estimated_position()
            print(f"  (simulasi) posisi servo: base={b:.0f} lengan={l:.0f} grip={g:.0f}")

    def command(self, line: str) -> bool:
        parts = line.split()
        cmd = parts[0].lower()
        if cmd in ("b", "l", "g"):
            self.sel = {"b": "base", "l": "lengan", "g": "grip"}[cmd]
        elif re.fullmatch(r"[+\-=]\d+", cmd):
            n = int(cmd[1:])
            cur = self.angles[self.sel]
            self.set_angle(n if cmd[0] == "=" else cur + (n if cmd[0] == "+" else -n))
        elif cmd == "center" and self.sel != "grip":
            self.cal[self.sel]["offset"] = self.angles[self.sel]
        elif cmd in ("min", "max") and self.sel != "grip":
            self.cal[self.sel][cmd] = self.angles[self.sel]
        elif cmd == "sign" and len(parts) == 2 and parts[1] in ("1", "-1") and self.sel != "grip":
            self.cal[self.sel]["sign"] = int(parts[1])
        elif cmd == "test" and self.sel != "grip":
            c = self.cal[self.sel]
            back = self.angles[self.sel]
            print("  bergerak ke +20 derajat sendi (base: ke kiri, lengan: naik)...")
            self.set_angle(c["offset"] + c["sign"] * 20)
            time.sleep(1.5)
            self.set_angle(back)
        elif cmd in ("open", "close") and self.sel == "grip":
            self.cal["grip"][cmd] = self.angles["grip"]
        elif cmd == "show":
            pass
        elif cmd == "save":
            self.save()
            return True
        elif cmd in ("quit", "exit", "q"):
            return False
        else:
            print("  perintah tidak dikenal / tidak berlaku untuk servo ini. Lihat bantuan di atas.")
            return True
        self.show()
        return True

    def save(self, path: Path = DEFAULT_CONFIG_PATH):
        for k in ("base", "lengan"):
            c = self.cal[k]
            if not c["min"] < c["max"]:
                print(f"  [GAGAL] {k}: min harus < max")
                return
        text = path.read_text(encoding="utf-8")
        path.write_text(update_config_text(text, self.cal), encoding="utf-8")
        load_config(path)   # validasi
        print(f"  Tersimpan ke {path}")

    def close(self):
        self._stop = True
        time.sleep(0.1)
        self.link.home()
        time.sleep(0.05)
        self.link.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port")
    p.add_argument("--mock", action="store_true")
    a = p.parse_args()
    cfg = load_config()
    link = make_link(cfg, a.mock, a.port)
    print(__doc__)
    print("Menunggu koneksi...")
    t0 = time.monotonic()
    while not link.connected and time.monotonic() - t0 < 8:
        link.update()
        time.sleep(0.1)
    print(f"Status: {link.status_text}")
    print("PERINGATAN: geser sedikit-sedikit (+2 / -2) di dekat batas mekanik!")
    cal = Calibrator(cfg, link)
    cal.show()
    try:
        while True:
            line = input(f"[{cal.sel}]> ").strip()
            if line and not cal.command(line):
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        cal.close()


if __name__ == "__main__":
    main()
