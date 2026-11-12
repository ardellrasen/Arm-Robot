"""Komunikasi laptop <-> ESP32.

- `VirtualESP32` : tiruan firmware di Python (protokol, rate limiter 50 Hz, watchdog, clamp).
                   Logikanya HARUS sama dengan firmware/src/main.cpp.
- `MockLink`     : MODE SIMULASI. Perintah dikirim ke VirtualESP32, tanpa hardware.
- `SerialLink`   : MODE ASLI. pyserial, non-blocking, auto-reconnect. Menyimpan VirtualESP32
                   sebagai "bayangan" untuk memperkirakan posisi servo sebenarnya di UI.

Kedua link punya antarmuka yang sama, jadi sisa aplikasi tidak peduli mode mana yang dipakai.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from .config import Config
from .servo_map import ServoAngles

TICK_S = 0.020  # 50 Hz, sama dengan firmware


@dataclass
class FirmwareParams:
    """Konstanta firmware (salinan dari bagian atas firmware/src/main.cpp)."""
    min_deg: tuple = (20, 30, 0)        # base, lengan, gripper
    max_deg: tuple = (160, 160, 180)
    home: tuple = (90, 90)              # base, lengan
    grip_open: int = 20
    grip_close: int = 80
    max_step: int = 3                   # derajat per tick
    home_step: int = 1                  # derajat per tick saat pulang ke home
    hold_timeout_ms: int = 1000
    home_timeout_ms: int = 10000


def _parse_int(tok: str) -> int:
    v = int(tok)  # ValueError kalau bukan bilangan bulat
    return v


class VirtualESP32:
    """Tiruan perilaku firmware. Waktu dimajukan lewat advance(now)."""

    def __init__(self, params: FirmwareParams | None = None, now: float | None = None):
        self.p = params or FirmwareParams()
        self.reset(now)

    # --- siklus hidup -------------------------------------------------------
    def reset(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        p = self.p
        self.grip_open, self.grip_close = p.grip_open, p.grip_close
        self.max_step = p.max_step
        self.current = [float(p.home[0]), float(p.home[1]), float(self.grip_open)]
        self.target = list(self.current)
        self.step = self.max_step
        self.last_a_time = now
        self.watchdog_state = "home"     # "active" | "hold" | "home"
        self._next_tick = now
        return ["READY"]

    def _clamp(self, i: int, v: float) -> float:
        return float(min(max(v, self.p.min_deg[i]), self.p.max_deg[i]))

    def _go_home(self) -> None:
        self.target = [self._clamp(0, self.p.home[0]), self._clamp(1, self.p.home[1]),
                       self._clamp(2, self.grip_open)]
        self.step = self.p.home_step

    # --- protokol -----------------------------------------------------------
    def handle_line(self, line: str, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        parts = line.strip().split()
        if not parts:
            return []
        cmd, args = parts[0].upper(), parts[1:]
        try:
            if cmd == "A" and len(args) == 3:
                b, l, g = (_parse_int(a) for a in args)
                if g not in (0, 1):
                    return ["ERR grip harus 0 atau 1"]
                self.target = [self._clamp(0, b), self._clamp(1, l),
                               self._clamp(2, self.grip_close if g else self.grip_open)]
                self.step = self.max_step
                self.last_a_time = now
                self.watchdog_state = "active"
                return []
            if cmd == "H" and not args:
                self._go_home()
                self.watchdog_state = "home"
                return ["OK"]
            if cmd == "S" and len(args) == 1:
                v = _parse_int(args[0])
                if not 1 <= v <= 30:
                    return ["ERR S harus 1..30"]
                self.max_step = v
                if self.watchdog_state == "active":
                    self.step = v
                return ["OK"]
            if cmd == "G" and len(args) == 2:
                o, c = (_parse_int(a) for a in args)
                if not (0 <= o <= 180 and 0 <= c <= 180):
                    return ["ERR G harus 0..180"]
                was_closed = abs(self.target[2] - self.grip_close) < abs(self.target[2] - self.grip_open)
                self.grip_open, self.grip_close = o, c
                self.target[2] = self._clamp(2, c if was_closed else o)
                return ["OK"]
            if cmd == "P" and not args:
                return ["OK"]
        except ValueError:
            return ["ERR angka tidak valid"]
        return [f"ERR perintah tidak dikenal: {line.strip()[:20]}"]

    # --- loop 50 Hz ---------------------------------------------------------
    def _tick(self, now: float) -> None:
        idle_ms = (now - self.last_a_time) * 1000.0
        if self.watchdog_state == "active" and idle_ms > self.p.hold_timeout_ms:
            self.watchdog_state = "hold"
            self.target = list(self.current)          # tahan posisi terakhir
        if self.watchdog_state == "hold" and idle_ms > self.p.home_timeout_ms:
            self.watchdog_state = "home"
            self._go_home()                           # pulang pelan ke home
        for i in range(3):
            d = self.target[i] - self.current[i]
            if abs(d) <= self.step:
                self.current[i] = self.target[i]
            else:
                self.current[i] += self.step if d > 0 else -self.step

    def advance(self, now: float) -> None:
        # batasi agar tidak "mengejar" terlalu banyak tick setelah jeda panjang
        if now - self._next_tick > 2.0:
            self._next_tick = now - 2.0
        while self._next_tick <= now:
            self._tick(self._next_tick)
            self._next_tick += TICK_S

    def position(self) -> tuple[float, float, float]:
        """(base_deg, lengan_deg, gripper_deg) saat ini."""
        return tuple(self.current)  # type: ignore[return-value]


# =============================================================================
class LinkBase:
    mode_name = "?"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.shadow = VirtualESP32(FirmwareParams())
        self.keepalive_s = cfg.serial.keepalive_ms / 1000.0
        self.last_sent: ServoAngles | None = None
        self.last_sent_t = 0.0
        self.log: deque[str] = deque(maxlen=10)   # riwayat perintah/balasan untuk UI
        self.replies: deque[str] = deque(maxlen=50)
        self._needs_setup = True

    # --- API publik ---------------------------------------------------------
    @property
    def connected(self) -> bool:
        raise NotImplementedError

    @property
    def status_text(self) -> str:
        raise NotImplementedError

    def send_angles(self, a: ServoAngles, now: float | None = None) -> bool:
        """Kirim `A ...` hanya kalau berubah atau sudah lewat keep-alive."""
        now = time.monotonic() if now is None else now
        if a == self.last_sent and now - self.last_sent_t < self.keepalive_s:
            return False
        if self._send(a.as_command(), now):
            self.last_sent, self.last_sent_t = a, now
            return True
        return False

    def home(self) -> None:
        self.last_sent = None
        self._send("H")

    def set_speed(self, deg_per_tick: int) -> None:
        self._send(f"S {int(deg_per_tick)}")

    def set_grip_angles(self, open_deg: float, close_deg: float) -> None:
        self._send(f"G {int(round(open_deg))} {int(round(close_deg))}")

    def ping(self) -> None:
        self._send("P")

    def update(self, now: float | None = None) -> None:
        """Panggil tiap frame: majukan simulasi, baca balasan, kirim setup setelah READY."""
        now = time.monotonic() if now is None else now
        self._update_io(now)
        self.shadow.advance(now)
        if self._needs_setup and self.connected:
            self._needs_setup = False
            self.set_speed(self.cfg.serial.speed_deg_per_tick)
            g = self.cfg.servos.grip
            self.set_grip_angles(g.open, g.close)

    def estimated_position(self) -> tuple[float, float, float]:
        """Perkiraan sudut servo (base, lengan, gripper_deg) sebenarnya saat ini."""
        return self.shadow.position()

    def close(self) -> None:
        pass

    # --- internal -----------------------------------------------------------
    def _send(self, line: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self._write_line(line, now):
            return False
        self.shadow.handle_line(line, now)
        if not line.startswith("A"):
            self.log.append(f"> {line}")
        return True

    def _on_reply(self, line: str, now: float) -> None:
        self.replies.append(line)
        self.log.append(f"< {line}")
        if line == "READY":
            # ESP32 (re)boot: posisi kembali ke home, kirim ulang setup
            self.shadow.reset(now)
            self.last_sent = None
            self._needs_setup = True

    def _write_line(self, line: str, now: float) -> bool:
        raise NotImplementedError

    def _update_io(self, now: float) -> None:
        raise NotImplementedError


# =============================================================================
class MockLink(LinkBase):
    """MODE SIMULASI: tidak ada hardware, ESP32 ditiru oleh VirtualESP32."""
    mode_name = "SIMULASI"

    def __init__(self, cfg: Config, verbose: bool = False):
        super().__init__(cfg)
        self.verbose = verbose
        self.device = self.shadow           # di simulasi, bayangan = perangkatnya sendiri
        self._pending: deque[str] = deque()
        self._plugged = True
        self._pending.extend(self.device.reset())

    @property
    def connected(self) -> bool:
        return self._plugged

    @property
    def status_text(self) -> str:
        return "SIMULASI (tanpa ESP32)" if self._plugged else "SIMULASI: kabel 'dicabut'"

    def toggle_unplug(self) -> None:
        """Untuk menguji auto-reconnect di simulasi."""
        self._plugged = not self._plugged
        if self._plugged:
            self._pending.extend(self.device.reset())

    def _write_line(self, line: str, now: float) -> bool:
        return self._plugged

    def _send(self, line: str, now: float | None = None) -> bool:
        # Di simulasi, "perangkat" = shadow; balasannya diantrikan seperti datang dari serial.
        now = time.monotonic() if now is None else now
        if not self._plugged:
            return False
        if self.verbose:
            print(f"[SIM] > {line}")
        self.device.advance(now)
        self._pending.extend(self.device.handle_line(line, now))
        if not line.startswith("A"):
            self.log.append(f"> {line}")
        return True

    def _update_io(self, now: float) -> None:
        while self._pending:
            r = self._pending.popleft()
            if self.verbose:
                print(f"[SIM] < {r}")
            if r == "READY":
                # device sudah di-reset oleh reset(); jangan reset lagi di sini
                self.replies.append(r)
                self.log.append("< READY")
                self.last_sent = None
                self._needs_setup = True
            else:
                self._on_reply(r, now)


# =============================================================================
class SerialLink(LinkBase):
    """MODE ASLI: USB serial ke ESP32, dengan thread baca + auto-reconnect."""
    mode_name = "ASLI"

    def __init__(self, cfg: Config, port: str | None = None):
        super().__init__(cfg)
        import serial  # pyserial, di-import di sini agar mode simulasi tidak bergantung padanya
        self._serial_mod = serial
        self.port = port or cfg.serial.port
        self.baud = cfg.serial.baud
        self._ser = None
        self._lock = threading.Lock()
        self._inbox: deque[str] = deque()
        self._ready = False
        self._last_error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="SerialLink", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ready

    @property
    def status_text(self) -> str:
        if self._ser is None:
            extra = f" ({self._last_error})" if self._last_error else ""
            return f"MENCARI ESP32 di {self.port}...{extra}"
        if not self._ready:
            return f"{self.port}: menunggu READY"
        return f"TERHUBUNG {self.port}"

    def _open(self) -> None:
        s = self._serial_mod.Serial()
        s.port, s.baudrate = self.port, self.baud
        s.timeout, s.write_timeout = 0.05, 0.05
        s.open()
        with self._lock:
            self._ser = s
            self._ready = False
        self._last_error = ""
        # Fallback: kalau firmware sudah jalan (tidak reset saat port dibuka), READY tidak datang.
        # Kirim ping; balasan OK juga dianggap tanda siap.
        threading.Timer(2.5, self._ping_if_not_ready).start()

    def _ping_if_not_ready(self) -> None:
        if self._ser is not None and not self._ready:
            self._raw_write("P")

    def _drop(self, err: Exception | str) -> None:
        with self._lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:
                    pass
            self._ser = None
            self._ready = False
        self._last_error = str(err)[:40]
        self.last_sent = None

    def _run(self) -> None:
        buf = b""
        while not self._stop.is_set():
            if self._ser is None:
                try:
                    self._open()
                    buf = b""
                except Exception as e:
                    self._last_error = type(e).__name__
                    self._stop.wait(1.0)
                    continue
            try:
                chunk = self._ser.read(256)
            except Exception as e:
                self._drop(e)
                continue
            if chunk:
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.decode("ascii", errors="replace").strip()
                    if line:
                        self._inbox.append(line)

    def _raw_write(self, line: str) -> bool:
        with self._lock:
            ser = self._ser
            if ser is None:
                return False
            try:
                ser.write((line + "\n").encode("ascii"))
                return True
            except Exception as e:
                err = e
        self._drop(err)
        return False

    def _write_line(self, line: str, now: float) -> bool:
        if not self._ready:
            return False
        return self._raw_write(line)

    def _update_io(self, now: float) -> None:
        while self._inbox:
            line = self._inbox.popleft()
            if not self._ready and line in ("READY", "OK"):
                self._ready = True
                if line == "OK":
                    # firmware sudah berjalan sebelum port dibuka (tidak reboot)
                    self.log.append("< OK (siap)")
                    self.shadow.reset(now)
                    self.last_sent = None
                    self._needs_setup = True
                    continue
            self._on_reply(line, now)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._drop("ditutup")


def make_link(cfg: Config, mock: bool, port: str | None = None, verbose: bool = False) -> LinkBase:
    return MockLink(cfg, verbose=verbose) if mock else SerialLink(cfg, port)
