"""External monitor control over DDC/CI via ddcutil (ASUS XG27UCDMG, see docs/PERIPHERALS.md).

Only the VCP codes listed in FEATURES are ever sent. All ddcutil calls run on one worker thread;
results come back to the GUI thread through private signals.
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

log = logging.getLogger(__name__)

CALL_TIMEOUT_S = 8.0
CALL_GAP_S = 0.05
LOCKED_VALUE = 254  # 0xFE read from E5/E6: locked in the current GameVisual mode
VENDOR = "AUS"


# ---- feature table --------------------------------------------------------

@dataclass(frozen=True)
class Feature:
    key: str
    code: int
    kind: str  # "range" | "choice" | "readonly"
    choices: dict[int, str] = field(default_factory=dict)
    confirm: bool = False
    range_max: int = 100
    lockable: bool = False


def _levels(n: int) -> dict[int, str]:
    return {0: "Off", **{i: f"Level {i}" for i in range(1, n + 1)}}


FEATURES: dict[str, Feature] = {f.key: f for f in (
    Feature("brightness", 0x10, "range"),
    Feature("contrast", 0x12, "range"),
    Feature("color_temp", 0x14, "choice", {
        0x03: "4000K", 0x04: "5000K", 0x05: "6500K", 0x06: "7500K",
        0x07: "8200K", 0x08: "9300K", 0x09: "10000K", 0x0B: "User"}),
    Feature("gamevisual", 0xDC, "choice", {
        0x01: "Cinema", 0x02: "Scenery", 0x04: "User", 0x05: "Racing", 0x06: "RTS/RPG",
        0x07: "FPS", 0x08: "MOBA", 0x09: "Night Vision", 0x0A: "sRGB Cal"}),
    Feature("shadow_boost", 0xE5, "choice", {**_levels(3), 4: "Dynamic"}, lockable=True),
    Feature("blue_light", 0xE6, "choice", _levels(4), lockable=True),
    Feature("hdr", 0xE2, "readonly"),
    Feature("screen_move", 0xF9, "choice", {0: "Off", 1: "Light", 2: "Middle", 3: "Strong"}),
    Feature("pixel_clean_reminder", 0xF8, "choice", {0: "Off", 2: "2 hours", 4: "4 hours", 8: "8 hours"}),
    Feature("input", 0x60, "choice", {0x0F: "DisplayPort", 0x11: "HDMI-1", 0x12: "HDMI-2", 0x1A: "USB-C"},
            confirm=True),
)}
_BY_CODE = {f.code: f for f in FEATURES.values()}


# ---- parsers --------------------------------------------------------------

@dataclass
class DdcDisplay:
    bus: int
    connector: str | None = None
    model: str | None = None
    serial: str | None = None
    vendor: str | None = None


@dataclass
class VcpValue:
    code: int
    current: int
    max: int | None = None


def parse_detect(text: str) -> list[DdcDisplay]:
    out: list[DdcDisplay] = []
    for block in re.split(r"\n\s*\n", text or ""):
        lines = [ln.strip() for ln in block.strip().splitlines()]
        if not lines or not re.match(r"Display\s+\d+", lines[0]):
            continue  # "Invalid display", "Phantom display", ...
        bus = connector = vendor = model = serial = None
        for ln in lines[1:]:
            key, _, val = ln.partition(":")
            val = val.strip()
            if key == "I2C bus":
                m = re.search(r"i2c-(\d+)", val)
                bus = int(m.group(1)) if m else None
            elif key == "DRM connector":
                connector = val or None
            elif key == "Monitor":
                parts = val.split(":", 2) + ["", ""]
                vendor, model, serial = (p.strip() or None for p in parts[:3])
        if bus is not None:
            out.append(DdcDisplay(bus, connector, model, serial, vendor))
    return out


def _hex(tok: str) -> int:
    return int(tok.lstrip("xX"), 16)


def parse_getvcp(line: str) -> VcpValue | None:
    try:
        t = (line or "").strip().split()
        if len(t) < 4 or t[0] != "VCP":
            return None
        code, kind = _hex(t[1]), t[2]
        if kind == "C" and len(t) >= 5:
            return VcpValue(code, int(t[3]), int(t[4]))
        if kind == "SNC":
            return VcpValue(code, _hex(t[3]))
        if kind == "CNC" and len(t) >= 7:
            mh, ml, sh, sl = (_hex(x) for x in t[2 + 1:2 + 5])
            return VcpValue(code, (sh << 8) | sl, (mh << 8) | ml)
    except (ValueError, IndexError):
        return None
    return None


# ---- state / runner -------------------------------------------------------

@dataclass
class MonitorState:
    present: bool = False
    bus: int | None = None
    model: str | None = None
    serial: str | None = None
    values: dict[str, int | None] = field(default_factory=dict)
    locked: set[str] = field(default_factory=set)
    maxima: dict[str, int | None] = field(default_factory=dict)


def default_run(argv: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as exc:
        return 127, "", str(exc)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], None]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn()
        except Exception:  # noqa: BLE001
            log.exception("ddc task failed")


class DdcClient(QObject):
    changed = pyqtSignal(object)  # MonitorState
    error = pyqtSignal(str)
    _result = pyqtSignal(object)
    _failed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None, *, run=None, sleep=None):
        super().__init__(parent)
        self._run = run or default_run
        self._sleep = sleep or time.sleep
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._result.connect(self.changed)
        self._failed.connect(self.error)
        self._state = MonitorState()  # touched only by the worker thread
        self._display: DdcDisplay | None = None
        self._timers: dict[str, QTimer] = {}
        self._pending: dict[str, int] = {}

    # -- worker-side helpers ------------------------------------------------
    def _call(self, argv: list[str]) -> tuple[int, str, str]:
        try:
            return self._run(argv, CALL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except Exception as exc:  # noqa: BLE001
            return 1, "", str(exc)

    def _discover(self) -> DdcDisplay | None:
        rc, out, err = self._call(["ddcutil", "detect", "--brief"])
        if rc != 0:
            log.warning("ddcutil detect failed: %s", err.strip())
            return None
        for d in parse_detect(out):
            if d.vendor == VENDOR and not (d.connector or "").split("-", 1)[-1].startswith("eDP"):
                return d
        return None

    def _getvcp_many(self, feats: list[Feature]) -> dict[int, VcpValue] | None:
        """One ddcutil call for several codes (~1 s instead of ~0.5 s per code). None = call failed."""
        assert self._display is not None
        rc, out, _err = self._call(["ddcutil", "--bus", str(self._display.bus), "--brief", "getvcp",
                                    *(f"0x{f.code:02X}" for f in feats)])
        found: dict[int, VcpValue] = {}
        for line in out.splitlines():
            v = parse_getvcp(line)
            if v is not None:
                found[v.code] = v
        if rc != 0 and not found:
            return None
        return found

    def _getvcp(self, feat: Feature) -> VcpValue | None:
        found = self._getvcp_many([feat])
        return (found or {}).get(feat.code)

    def _apply_read(self, feat: Feature, v: VcpValue | None) -> None:
        st = self._state
        st.locked.discard(feat.key)
        st.maxima[feat.key] = v.max if v else None
        if v is None:
            st.values[feat.key] = None
        elif feat.lockable and v.current == LOCKED_VALUE:
            st.values[feat.key] = None
            st.locked.add(feat.key)
        else:
            st.values[feat.key] = v.current

    def _snapshot(self) -> MonitorState:
        s = self._state
        return MonitorState(s.present, s.bus, s.model, s.serial, dict(s.values),
                            set(s.locked), dict(s.maxima))

    def _ensure_display(self) -> bool:
        if self._display is None:
            self._display = self._discover()
        d = self._display
        st = self._state
        st.present = d is not None
        st.bus = d.bus if d else None
        st.model = d.model if d else None
        st.serial = d.serial if d else None
        if d is None:
            st.values, st.locked, st.maxima = {}, set(), {}
        return d is not None

    def _do_refresh(self) -> None:
        if not self._ensure_display():
            self._result.emit(self._snapshot())
            return
        feats = list(FEATURES.values())
        found = self._getvcp_many(feats)
        if found is None:
            # call failed: the bus may have moved; rediscover once and retry
            self._display = None
            if not self._ensure_display():
                self._result.emit(self._snapshot())
                self._failed.emit("monitor not reachable over DDC/CI")
                return
            found = self._getvcp_many(feats) or {}
        failures = 0
        for feat in feats:
            v = found.get(feat.code)
            if v is None:
                failures += 1
            self._apply_read(feat, v)
        self._result.emit(self._snapshot())
        if failures:
            self._failed.emit(f"ddcutil: {failures} feature read(s) failed")

    def _do_set(self, feat: Feature, value: int) -> None:
        if not self._ensure_display():
            self._result.emit(self._snapshot())
            self._failed.emit("monitor not present")
            return
        argv = ["ddcutil", "--bus", str(self._display.bus), "setvcp", f"0x{feat.code:02X}", str(value)]
        rc, _out, err = self._call(argv)
        if rc != 0:
            self._display = None  # force rediscovery next time
            self._failed.emit(f"ddcutil setvcp {feat.key} failed: {err.strip() or rc}")
            return
        self._sleep(CALL_GAP_S)
        if self._display is not None or self._ensure_display():
            self._apply_read(feat, self._getvcp(feat))
        self._result.emit(self._snapshot())

    # -- public API ----------------------------------------------------------
    def refresh(self) -> None:
        self._pool.start(_Task(self._do_refresh))

    def validate(self, key: str, value: int, confirmed: bool = False) -> str | None:
        """Return an error string, or None when the write is allowed."""
        feat = FEATURES.get(key)
        if feat is None:
            return f"unknown feature: {key}"
        if feat.kind == "readonly":
            return f"{key} is read-only"
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{key}: value must be an integer"
        if feat.kind == "choice" and value not in feat.choices:
            return f"{key}: invalid value {value}"
        if feat.kind == "range" and not 0 <= value <= feat.range_max:
            return f"{key}: {value} out of range 0..{feat.range_max}"
        if feat.confirm and not confirmed:
            return f"{key} requires explicit confirmation"
        return None

    def set_value(self, key: str, value: int, confirmed: bool = False) -> bool:
        err = self.validate(key, value, confirmed)
        if err:
            log.warning("ddc set refused: %s", err)
            self.error.emit(err)
            return False
        feat = FEATURES[key]
        self._pool.start(_Task(lambda: self._do_set(feat, value)))
        return True

    def set_value_debounced(self, key: str, value: int, ms: int = 300) -> None:
        err = self.validate(key, value)
        if err:
            self.error.emit(err)
            return
        self._pending[key] = value
        t = self._timers.get(key)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda k=key: self._flush(k))
            self._timers[key] = t
        t.start(ms)

    def _flush(self, key: str) -> None:
        value = self._pending.pop(key, None)
        if value is not None:
            self.set_value(key, value)
