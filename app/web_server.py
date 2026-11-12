"""Server web lokal untuk UI digital twin (hanya library standar Python).

  GET  /              -> app/web/index.html (+ file statis lain di app/web/)
  GET  /api/config    -> geometri & rentang dari config.yaml (untuk membangun model 3D)
  GET  /events        -> Server-Sent Events, telemetri JSON ~30 Hz
  GET  /stream.mjpg   -> video kamera (MJPEG)
  POST /api/cmd       -> {"cmd": "estop" | "calib" | "unplug" | "quit" | "mouse", ...}

Default hanya mendengarkan di 127.0.0.1 (tidak bisa diakses dari jaringan).
"""
from __future__ import annotations

import json
import mimetypes
import threading
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

WEB_DIR = Path(__file__).resolve().parent / "web"

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("font/woff2", ".woff2")

ALLOWED_CMDS = {"estop", "calib", "unplug", "quit", "mouse"}


class WebHub:
    def __init__(self, static_config: dict, host: str = "127.0.0.1", port: int = 8765,
                 jpeg_width: int = 960, jpeg_quality: int = 75):
        self.static_config = static_config
        self.host, self.port = host, port
        self.jpeg_width = jpeg_width
        self.jpeg_quality = jpeg_quality
        self.cond = threading.Condition()
        self.telemetry = b"{}"
        self.tele_seq = 0
        self.jpeg: bytes | None = None
        self.jpeg_seq = 0
        self.mjpeg_clients = 0
        self.commands: deque[dict] = deque(maxlen=200)
        self.running = False
        self._server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://{'localhost' if self.host in ('127.0.0.1', '0.0.0.0') else self.host}:{self.port}/"

    # --- dipanggil dari loop utama -----------------------------------------
    def publish(self, telemetry: dict, frame) -> None:
        jpg = None
        if frame is not None and self.mjpeg_clients > 0:
            h, w = frame.shape[:2]
            if w > self.jpeg_width:
                frame = cv2.resize(frame, (self.jpeg_width, int(h * self.jpeg_width / w)),
                                   interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
            if ok:
                jpg = buf.tobytes()
        data = json.dumps(telemetry, separators=(",", ":")).encode()
        with self.cond:
            self.telemetry = data
            self.tele_seq += 1
            if jpg is not None:
                self.jpeg = jpg
                self.jpeg_seq += 1
            self.cond.notify_all()

    def pop_commands(self) -> list[dict]:
        out = []
        while self.commands:
            out.append(self.commands.popleft())
        return out

    # --- server ------------------------------------------------------------
    def start(self) -> None:
        hub = self

        class Handler(_Handler):
            pass
        Handler.hub = hub
        self._server = _ExclusiveServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self.running = True
        threading.Thread(target=self._server.serve_forever, name="WebHub", daemon=True).start()

    def stop(self) -> None:
        self.running = False
        with self.cond:
            self.cond.notify_all()
        if self._server:
            self._server.shutdown()
            self._server.server_close()


class _ExclusiveServer(ThreadingHTTPServer):
    """Tolak port yang sudah dipakai. Di Windows, SO_REUSEADDR (default http.server) membuat
    instance kedua aplikasi ikut 'berhasil' bind ke port yang sama tanpa error."""
    daemon_threads = True

    def server_bind(self):
        import socket
        import sys
        if sys.platform.startswith("win"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(BaseHTTPRequestHandler):
    hub: WebHub
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # jangan banjiri terminal
        pass

    # --- GET ---------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/events":
            return self._sse()
        if path == "/stream.mjpg":
            return self._mjpeg()
        if path == "/api/config":
            return self._json(self.hub.static_config)
        if path == "/":
            path = "/index.html"
        return self._static(path)

    def _json(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str):
        target = (WEB_DIR / path.lstrip("/")).resolve()
        if WEB_DIR not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _sse(self):
        hub = self.hub
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        seq = -1
        try:
            self.wfile.write(b"retry: 1000\n\n")
            while hub.running:
                with hub.cond:
                    hub.cond.wait_for(lambda: hub.tele_seq != seq or not hub.running, timeout=1.0)
                    data, seq_new = hub.telemetry, hub.tele_seq
                if seq_new == seq:
                    self.wfile.write(b": ping\n\n")   # jaga koneksi tetap hidup
                else:
                    seq = seq_new
                    self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _mjpeg(self):
        hub = self.hub
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with hub.cond:
            hub.mjpeg_clients += 1
        seq = -1
        try:
            while hub.running:
                with hub.cond:
                    hub.cond.wait_for(lambda: hub.jpeg_seq != seq or not hub.running, timeout=1.0)
                    jpg, seq_new = hub.jpeg, hub.jpeg_seq
                if jpg is None or seq_new == seq:
                    continue
                seq = seq_new
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with hub.cond:
                hub.mjpeg_clients -= 1

    # --- POST --------------------------------------------------------------
    def do_POST(self):
        if self.path != "/api/cmd":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 4096)
            msg = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(msg, dict) or msg.get("cmd") not in ALLOWED_CMDS:
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return self._json({"ok": False}, HTTPStatus.BAD_REQUEST)
        self.hub.commands.append(msg)
        return self._json({"ok": True})


def open_app_window(url: str, fullscreen: bool) -> None:
    """Buka UI di Edge/Chrome mode aplikasi (tanpa address bar). Fallback: browser default."""
    import os
    import shutil
    import subprocess
    import sys
    import webbrowser

    candidates = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                               Path(base) / "Google/Chrome/Application/chrome.exe"]
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            p = shutil.which(name)
            if p:
                candidates.append(Path(p))
    exe = next((c for c in candidates if c.exists()), None)
    if exe is None:
        webbrowser.open(url)
        return
    profile = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RobotArmITB" / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [str(exe), f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--disable-features=Translate",
            "--window-size=1600,900"]
    if fullscreen:
        args.append("--start-fullscreen")
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
