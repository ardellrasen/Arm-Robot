"""Memuat dan memvalidasi config/config.yaml menjadi dataclass bertipe."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"


class ConfigError(ValueError):
    """Config tidak valid."""


@dataclass
class SerialCfg:
    port: str = "COM5"
    baud: int = 115200
    mock: bool = True
    speed_deg_per_tick: int = 3
    keepalive_ms: int = 200


@dataclass
class CameraCfg:
    index: int = 0
    width: int = 1280
    height: int = 720
    mirror: bool = True


@dataclass
class GeometryCfg:
    L: float = 10.0
    H0: float = 6.0


@dataclass
class TrackingCfg:
    min_detection_confidence: float = 0.7
    min_tracking_confidence: float = 0.6


@dataclass
class FilterCfg:
    type: str = "one_euro"
    min_cutoff: float = 1.0
    beta: float = 0.02
    ema_alpha: float = 0.3


@dataclass
class MappingCfg:
    x_range: list = field(default_factory=lambda: [0.15, 0.85])
    yaw_range: list = field(default_factory=lambda: [60.0, -60.0])
    y_mode: str = "height"
    y_range: list = field(default_factory=lambda: [0.85, 0.15])
    pitch_range: list = field(default_factory=lambda: [-30.0, 60.0])
    pinch_close: float = 0.35
    pinch_open: float = 0.50


@dataclass
class JointServoCfg:
    offset: float = 90.0
    sign: int = 1
    min: float = 0.0
    max: float = 180.0


@dataclass
class GripServoCfg:
    open: float = 20.0
    close: float = 80.0


@dataclass
class ServosCfg:
    base: JointServoCfg = field(default_factory=JointServoCfg)
    lengan: JointServoCfg = field(default_factory=JointServoCfg)
    grip: GripServoCfg = field(default_factory=GripServoCfg)


@dataclass
class UiCfg:
    backend: str = "web"            # web (digital twin 3D) | opencv (jendela lama)
    fullscreen: bool = False
    idle_timeout_s: float = 3.0
    web_host: str = "127.0.0.1"
    web_port: int = 8765
    open_browser: bool = True


@dataclass
class RecordingCfg:
    enabled: bool = False
    max_seconds: float = 30.0
    lead_in_seconds: float = 1.0


@dataclass
class Config:
    serial: SerialCfg = field(default_factory=SerialCfg)
    camera: CameraCfg = field(default_factory=CameraCfg)
    geometry: GeometryCfg = field(default_factory=GeometryCfg)
    tracking: TrackingCfg = field(default_factory=TrackingCfg)
    filter: FilterCfg = field(default_factory=FilterCfg)
    mapping: MappingCfg = field(default_factory=MappingCfg)
    servos: ServosCfg = field(default_factory=ServosCfg)
    ui: UiCfg = field(default_factory=UiCfg)
    recording: RecordingCfg = field(default_factory=RecordingCfg)


def _build(cls: type, data: Any, path: str):
    """Bangun dataclass `cls` dari dict secara rekursif, dengan pengecekan tipe sederhana."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"'{path}' harus berupa mapping/dict")
    obj = cls()
    known = {f.name: f for f in fields(cls)}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(f"Kunci tidak dikenal: '{path}.{key}'")
        current = getattr(obj, key)
        sub_path = f"{path}.{key}" if path else key
        if is_dataclass(current):
            setattr(obj, key, _build(type(current), value, sub_path))
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"'{sub_path}' harus true/false")
            setattr(obj, key, value)
        elif isinstance(current, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"'{sub_path}' harus angka")
            setattr(obj, key, type(current)(value) if isinstance(current, float) else value)
        elif isinstance(current, list):
            if not (isinstance(value, list) and len(value) == 2
                    and all(isinstance(v, (int, float)) for v in value)):
                raise ConfigError(f"'{sub_path}' harus list 2 angka, mis. [0.1, 0.9]")
            setattr(obj, key, [float(v) for v in value])
        else:
            setattr(obj, key, str(value))
    return obj


def validate(cfg: Config) -> None:
    m = cfg.mapping
    if m.y_mode not in ("height", "angle"):
        raise ConfigError("mapping.y_mode harus 'height' atau 'angle'")
    if cfg.filter.type not in ("one_euro", "ema"):
        raise ConfigError("filter.type harus 'one_euro' atau 'ema'")
    if not m.pinch_close < m.pinch_open:
        raise ConfigError("mapping.pinch_close harus < pinch_open (hysteresis)")
    for name in ("x_range", "y_range"):
        a, b = getattr(m, name)
        if a == b:
            raise ConfigError(f"mapping.{name} tidak boleh dua nilai sama")
    p_lo, p_hi = m.pitch_range
    if not (-90 < p_lo < p_hi < 90):
        raise ConfigError("mapping.pitch_range harus -90 < min < max < 90")
    if cfg.geometry.L <= 0 or cfg.geometry.H0 < 0:
        raise ConfigError("geometry.L harus > 0 dan H0 >= 0")
    for name in ("base", "lengan"):
        s = getattr(cfg.servos, name)
        if s.sign not in (1, -1):
            raise ConfigError(f"servos.{name}.sign harus 1 atau -1")
        if not (0 <= s.min < s.max <= 180):
            raise ConfigError(f"servos.{name}: harus 0 <= min < max <= 180")
    g = cfg.servos.grip
    if not (0 <= g.open <= 180 and 0 <= g.close <= 180):
        raise ConfigError("servos.grip.open/close harus 0..180")
    if not (1 <= cfg.serial.speed_deg_per_tick <= 30):
        raise ConfigError("serial.speed_deg_per_tick harus 1..30")
    if not (20 <= cfg.serial.keepalive_ms <= 900):
        raise ConfigError("serial.keepalive_ms harus 20..900 (watchdog firmware 1000 ms)")
    if cfg.ui.backend not in ("web", "opencv"):
        raise ConfigError("ui.backend harus 'web' atau 'opencv'")
    if not (1024 <= cfg.ui.web_port <= 65535):
        raise ConfigError("ui.web_port harus 1024..65535")
    if cfg.ui.idle_timeout_s <= 0:
        raise ConfigError("ui.idle_timeout_s harus > 0")


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise ConfigError(f"File config tidak ditemukan: {p}")
    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = _build(Config, raw, "")
    validate(cfg)
    return cfg


def config_from_dict(raw: dict) -> Config:
    """Dipakai di unit test."""
    cfg = _build(Config, raw, "")
    validate(cfg)
    return cfg
