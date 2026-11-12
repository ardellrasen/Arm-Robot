"""Entry point:  python -m app.main [--mode sim|real] [--mouse | --demo | --video FILE] [--ui web|opencv]

Contoh:
  python -m app.main --mode sim             # simulasi, webcam, UI digital twin 3D
  python -m app.main --mode sim --mouse     # simulasi, tanpa kamera (mouse = tangan)
  python -m app.main --mode sim --demo      # simulasi, tangan virtual bergerak sendiri
  python -m app.main --mode real --port COM5   # robot asli lewat USB serial
  python -m app.main --ui opencv            # UI jendela OpenCV lama (cadangan)
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2

from . import kinematics
from .config import Config, ConfigError, load_config
from .controller import Controller, Telemetry
from .link import MockLink, make_link
from .sources import CameraSource, MouseSource


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Robot Arm ITB Insight - hand tracking")
    p.add_argument("--config", help="path config.yaml (default: config/config.yaml)")
    p.add_argument("--mode", choices=["sim", "real"],
                   help="sim = simulasi tanpa ESP32, real = ESP32 via serial (default dari config serial.mock)")
    p.add_argument("--mock", action="store_true", help="alias untuk --mode sim")
    p.add_argument("--port", help="port serial, mis. COM5 atau /dev/ttyUSB0 (override config)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--video", help="pakai file video, bukan webcam")
    src.add_argument("--mouse", action="store_true", help="tangan virtual dengan mouse (tanpa kamera)")
    src.add_argument("--demo", action="store_true", help="tangan virtual bergerak otomatis")
    p.add_argument("--ui", choices=["web", "opencv"], help="tampilan (default dari config ui.backend)")
    p.add_argument("--windowed", action="store_true", help="paksa mode jendela")
    p.add_argument("--fullscreen", action="store_true", help="paksa fullscreen")
    p.add_argument("--no-browser", action="store_true", help="(web) jangan buka browser otomatis")
    p.add_argument("--web-port", type=int, help="(web) port server lokal")
    p.add_argument("--verbose", action="store_true", help="cetak perintah serial ke terminal")
    p.add_argument("--frames", type=int, default=0, help="(tes) keluar setelah N frame")
    p.add_argument("--snapshot", help="(tes, opencv) simpan tampilan terakhir ke PNG saat keluar")
    p.add_argument("--no-window", action="store_true", help="(tes, opencv) jalan tanpa jendela")
    return p.parse_args(argv)


def web_static_config(cfg: Config, mode_label: str) -> dict:
    g, m, s = cfg.geometry, cfg.mapping, cfg.servos
    z_lo, z_hi = kinematics.height_limits(g.L, g.H0, *m.pitch_range)
    return {
        "mode": mode_label,
        "geometry": {"L": g.L, "H0": g.H0, "z_range": [z_lo, z_hi]},
        "mapping": {"x_range": m.x_range, "y_range": m.y_range, "yaw_range": m.yaw_range,
                    "pitch_range": m.pitch_range, "pinch_close": m.pinch_close,
                    "pinch_open": m.pinch_open, "y_mode": m.y_mode},
        "servos": {"base": vars(s.base), "lengan": vars(s.lengan), "grip": vars(s.grip)},
        "idle_timeout_s": cfg.ui.idle_timeout_s,
        "speed_deg_per_tick": cfg.serial.speed_deg_per_tick,
    }


def run_web(args, cfg, source, link, ctrl, mode_label, fullscreen) -> None:
    from .web_server import WebHub, open_app_window
    port = args.web_port or cfg.ui.web_port
    hub = WebHub(web_static_config(cfg, mode_label), cfg.ui.web_host, port)
    try:
        hub.start()
    except OSError as e:
        raise SystemExit(f"[WEB] Port {port} tidak bisa dipakai ({e}). "
                         "Mungkin aplikasi masih berjalan? Atau pakai --web-port 8766") from e
    print(f"[WEB] UI digital twin: {hub.url}   (Ctrl+C untuk keluar)")
    if cfg.ui.open_browser and not args.no_browser:
        open_app_window(hub.url, fullscreen)

    fps, last_t, n = 0.0, time.monotonic(), 0
    try:
        while True:
            frame, feats = source.read()
            now = time.monotonic()
            dt, last_t = now - last_t, now
            if dt > 0:
                fps = 1 / dt if fps == 0 else 0.9 * fps + 0.1 / dt
            quit_req = False
            for c in hub.pop_commands():
                cmd = c.get("cmd")
                if cmd == "estop":
                    ctrl.toggle_estop()
                elif cmd == "calib":
                    ctrl.toggle_calib()
                elif cmd == "unplug" and isinstance(link, MockLink):
                    link.toggle_unplug()
                elif cmd == "mouse" and isinstance(source, MouseSource) and not source.demo:
                    try:
                        source.on_mouse(float(c["x"]), float(c["y"]), bool(c["inside"]), bool(c["pressed"]))
                    except (KeyError, TypeError, ValueError):
                        pass
                elif cmd == "quit":
                    quit_req = True
            tele = ctrl.step(feats, now)
            hub.publish(tele.to_dict(fps, mode_label, source.name), frame)
            n += 1
            if quit_req or (args.frames and n >= args.frames):
                break
    finally:
        hub.stop()


def run_opencv(args, cfg, source, link, ctrl, mode_label, fullscreen) -> None:
    from .ui import UI, ViewInfo
    ui = UI(cfg, fullscreen)
    if isinstance(source, MouseSource) and not source.demo:
        ui.mouse_listener = source.on_mouse
    if not args.no_window:
        ui.open_window()
    fps, last_t, n, canvas = 0.0, time.monotonic(), 0, None
    try:
        while True:
            frame, feats = source.read()
            now = time.monotonic()
            dt, last_t = now - last_t, now
            if dt > 0:
                fps = 1 / dt if fps == 0 else 0.9 * fps + 0.1 / dt
            if ui.pop_estop_click():
                ctrl.toggle_estop()
            t: Telemetry = ctrl.step(feats, now)
            info = ViewInfo(
                state=t.state, mode_label=mode_label, link_status=t.link_status, link_ok=t.link_ok,
                source_name=source.name, fps=fps,
                target_servo=(t.target.base, t.target.lengan, t.target.grip),
                actual_servo=t.actual_servo,
                target_joint=(t.target_joint.yaw, t.target_joint.pitch, t.target_joint.grip),
                actual_joint=t.actual_joint, filtered_xy=t.filtered_xy, calib=t.calib, log=t.log)
            canvas = ui.render(frame, feats, info)
            n += 1
            if args.frames and n >= args.frames:
                break
            if args.no_window:
                continue
            key = ui.show(canvas)
            if key in (ord("q"), 27) or ui.window_closed():
                break
            if key == ord(" "):
                ctrl.toggle_estop()
            elif key == ord("c"):
                ctrl.toggle_calib()
            elif key == ord("f"):
                ui.toggle_fullscreen()
            elif key == ord("u") and isinstance(link, MockLink):
                link.toggle_unplug()
    finally:
        if args.snapshot and canvas is not None:
            cv2.imwrite(args.snapshot, canvas)
        cv2.destroyAllWindows()


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        return 2

    mock = cfg.serial.mock
    if args.mode:
        mock = args.mode == "sim"
    if args.mock:
        mock = True
    fullscreen = cfg.ui.fullscreen
    if args.windowed:
        fullscreen = False
    if args.fullscreen:
        fullscreen = True
    backend = args.ui or cfg.ui.backend

    if args.mouse or args.demo:
        source = MouseSource(demo=args.demo)
    else:
        try:
            source = CameraSource(cfg, args.video)
        except RuntimeError as e:
            print(f"[KAMERA] {e}")
            return 3

    link = make_link(cfg, mock, args.port, verbose=args.verbose)
    mode_label = "SIMULASI" if mock else "ASLI"
    print(f"[INFO] Mode {mode_label} | input: {source.name} | UI: {backend} | {link.status_text}")
    ctrl = Controller(cfg, link)
    try:
        runner = run_web if backend == "web" else run_opencv
        runner(args, cfg, source, link, ctrl, mode_label, fullscreen)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            link.home()
            time.sleep(0.05)
        except Exception:
            pass
        link.close()
        source.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
