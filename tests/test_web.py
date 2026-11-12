"""Tes server UI web (digital twin) dan Controller tanpa browser."""
import json
import socket
import urllib.error
import urllib.request

import numpy as np
import pytest

from app.config import Config
from app.controller import Controller
from app.link import MockLink
from app.main import web_static_config
from app.state import State
from app.tracker import HandFeatures
from app.web_server import WebHub


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def hub():
    h = WebHub(web_static_config(Config(), "SIMULASI"), "127.0.0.1", free_port())
    h.start()
    yield h
    h.stop()


def get(hub, path):
    return urllib.request.urlopen(f"http://127.0.0.1:{hub.port}{path}", timeout=3)


def test_config_and_index(hub):
    cfg = json.loads(get(hub, "/api/config").read())
    assert cfg["geometry"]["L"] == 10.0 and cfg["mode"] == "SIMULASI"
    html = get(hub, "/").read().decode()
    assert "Digital Twin" in html and "importmap" in html
    assert get(hub, "/vendor/three/build/three.module.min.js").status == 200


def test_static_path_traversal_blocked(hub):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(hub, "/../config.py")
    assert e.value.code == 404


def test_commands(hub):
    def post(body):
        req = urllib.request.Request(f"http://127.0.0.1:{hub.port}/api/cmd", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(req, timeout=3)
    assert post({"cmd": "estop"}).status == 200
    with pytest.raises(urllib.error.HTTPError):
        post({"cmd": "rm -rf"})
    assert hub.pop_commands() == [{"cmd": "estop"}]


def test_sse_stream(hub):
    resp = get(hub, "/events")
    assert resp.headers["Content-Type"] == "text/event-stream"
    hub.publish({"state": "LIVE", "x": 1}, None)
    for _ in range(10):                       # lewati "retry:", baris kosong, data awal
        line = resp.readline().decode()
        if line.startswith("data: ") and "state" in line:
            break
    assert json.loads(line[6:])["state"] == "LIVE"
    resp.close()


def test_mjpeg_stream(hub):
    resp = get(hub, "/stream.mjpg")
    assert "multipart/x-mixed-replace" in resp.headers["Content-Type"]
    hub.publish({}, np.zeros((720, 1280, 3), np.uint8))
    assert resp.readline() == b"--frame\r\n"
    assert resp.readline() == b"Content-Type: image/jpeg\r\n"
    resp.close()


def test_controller_telemetry_follows_hand():
    cfg = Config()
    ctrl = Controller(cfg, MockLink(cfg))
    import time
    t0, t = time.monotonic(), None     # jam yang sama dengan VirtualESP32
    for i in range(60):   # tangan di kiri atas, sambil mencubit
        t = ctrl.step(HandFeatures(x=0.2, y=0.2, pinch=0.1, visible=True), now=t0 + i * 0.033)
    assert t.state == State.LIVE
    assert t.target_joint.yaw > 40 and t.target_joint.pitch > 40 and t.target_joint.grip == 1
    d = t.to_dict(30.0, "SIMULASI", "tes")
    assert d["state"] == "LIVE" and d["jt"]["grip"] == 1
    assert d["ja"]["yaw"] > 0          # posisi nyata (rate-limited) bergerak ke target
    json.dumps(d)                      # harus bisa dikirim lewat SSE
