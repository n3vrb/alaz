"""ROG Harpe Ace Mini via the ROG Omni receiver (report 0x03). Protocol: docs/PERIPHERALS.md.

Builders return the command bytes AFTER the report id (the transport prepends 0x03).
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QObject

from ..ledcolor import led_decode, led_encode  # LED colours are linearised (see ledcolor.py)
from .hidraw import HidClientBase, HidTransport, is_error_reply, pad

log = logging.getLogger(__name__)

VID = 0x0B05
PIDS = {0x1ACE}
REPORT_ID = 0x03

# VERIFIED visually on the owner's Harpe Ace Mini: only zone 0x01 changes the physical LED (as G-Helper does).
# The LED read (12 03, the zone byte is ignored) reports zone 0x00, a separate stored copy that the LED never
# shows. Every LED write therefore goes to 0x01 (the LED) and then 0x00 (so reads match what the LED shows).
LED_ZONE = 0x01
LED_ZONES = (0x01, 0x00)

POLLING_CODES = {125: 0, 250: 1, 500: 2, 1000: 3}
POLLING_BY_CODE = {v: k for k, v in POLLING_CODES.items()}
SLEEP_CODES = (0, 1, 2, 3, 4, 0xFF)  # 1, 2, 3, 5, 10 min, never
LED_MODES = (0, 1, 2, 4, 6, 0xF0)
SAVE = b"\x50\x03"


@dataclass
class MouseState:
    present: bool = False
    permission: bool = True
    asleep: bool = False
    serial: str | None = None
    battery_pct: int | None = None
    charging: bool | None = None
    sleep_code: int | None = None
    low_battery_pct: int | None = None
    profile: int | None = None
    dpi_stage: int | None = None            # 1-based
    dpi_stages: list[int] | None = None     # 4 values
    dpi_colors: list[tuple[int, int, int]] | None = None
    polling_hz: int | None = None
    debounce_ms: int | None = None
    angle_snapping: bool | None = None
    angle_tuning: int | None = None
    led_mode: int | None = None
    led_brightness: int | None = None
    led_rgb: tuple[int, int, int] | None = None
    led_direction: int | None = None
    led_random: int | None = None
    led_speed: int | None = None
    liftoff: int | None = None              # not verified -> always None


# ---- parsers (r = full 64-byte reply incl. report id; short input is zero-padded) -----------

def parse_battery(r: bytes) -> dict:
    r = pad(r)
    pct = r[5] if r[5] <= 100 else None
    return {"battery_pct": pct, "sleep_code": r[6], "low_battery_pct": r[7], "charging": r[10] > 0}


def parse_serial(r: bytes) -> dict:
    s = pad(r)[5:17].split(b"\x00")[0].decode("ascii", "ignore").strip()
    return {"serial": s or None}


def parse_profile(r: bytes) -> dict:
    r = pad(r)
    return {"profile": r[11], "dpi_stage": r[12] if 1 <= r[12] <= 4 else None}


def parse_settings(r: bytes) -> dict:
    r = pad(r)
    code = r[15]
    return {
        "polling_hz": POLLING_BY_CODE.get(r[13] & 7),
        "debounce_ms": (code + 1) * 4 if code <= 7 else None,  # code 0 ambiguous -> "4 ms"
        "angle_snapping": r[17] == 1,
        "angle_tuning": int.from_bytes(r[19:21], "little", signed=True),
    }


def parse_dpi(r: bytes) -> dict:
    r = pad(r)
    return {"dpi_stages": [int.from_bytes(r[5 + 4 * i:7 + 4 * i], "little") * 50 + 50
                           for i in range(4)]}


def parse_dpicolor(r: bytes) -> dict:
    r = pad(r)
    return {"dpi_colors": [tuple(r[5 + 3 * i:8 + 3 * i]) for i in range(4)]}


def parse_led(r: bytes) -> dict:
    r = pad(r)
    return {"led_mode": r[5], "led_brightness": r[6] if r[6] <= 100 else None,
            "led_rgb": tuple(r[7:10]), "led_direction": r[11], "led_random": r[12],
            "led_speed": r[13]}


# ---- builders ---------------------------------------------------------

def _rgb(rgb) -> bytes:
    if len(rgb) != 3 or any(not 0 <= int(c) <= 255 for c in rgb):
        raise ValueError(f"bad RGB {rgb!r}")
    return bytes(int(c) for c in rgb)


def build_dpi_stage(i: int, dpi: int, rgb) -> bytes:
    if not 0 <= i <= 3:
        raise ValueError(f"DPI stage index {i} outside 0..3")
    if not (100 <= dpi <= 42000 and dpi % 50 == 0):
        raise ValueError(f"DPI {dpi} outside 100..42000 step 50")
    raw = (dpi - 50) // 50
    return bytes([0x51, 0x31, i, 0x00]) + raw.to_bytes(2, "little") + _rgb(rgb)


def build_active_stage(stage: int) -> bytes:
    """``stage`` is 1-based (1..4), like MouseState.dpi_stage."""
    if not 1 <= stage <= 4:
        raise ValueError(f"active stage {stage} outside 1..4")
    return bytes([0x51, 0x31, 0x09, 0x00, stage])


def build_polling(hz: int) -> bytes:
    if hz not in POLLING_CODES:
        raise ValueError(f"polling rate {hz} not in {sorted(POLLING_CODES)}")
    return bytes([0x51, 0x31, 0x04, 0x00, POLLING_CODES[hz]])


def debounce_code(ms: int) -> int:
    if not (8 <= ms <= 32 and ms % 4 == 0):
        raise ValueError(f"debounce {ms} ms outside 8..32 step 4")
    return ms // 4 - 1


def build_debounce(ms: int) -> bytes:
    return bytes([0x51, 0x31, 0x05, 0x00, debounce_code(ms)])


def build_angle_snapping(on: bool) -> bytes:
    return bytes([0x51, 0x31, 0x06, 0x00, 1 if on else 0])


def build_sleep(sleep_code: int, low_pct: int) -> bytes:
    if sleep_code not in SLEEP_CODES:
        raise ValueError(f"sleep code {sleep_code} not in {SLEEP_CODES}")
    if not 0 <= low_pct <= 100:
        raise ValueError(f"low-battery {low_pct} outside 0..100")
    return bytes([0x51, 0x37, 0x00, 0x00, sleep_code, 0x00, low_pct])


def build_led(mode: int, brightness: int, rgb, direction: int = 0, random: int = 0,
              speed: int = 0, zone: int | None = None) -> bytes:
    if mode not in LED_MODES:
        raise ValueError(f"LED mode {mode} not in {LED_MODES}")
    if not 0 <= brightness <= 100:
        raise ValueError(f"brightness {brightness} outside 0..100")
    for v in (direction, random, speed):
        if not 0 <= v <= 255:
            raise ValueError("LED direction/random/speed outside 0..255")
    z = LED_ZONE if zone is None else zone
    return bytes([0x51, 0x28, z, 0x00, mode, brightness]) + _rgb(rgb) + bytes([direction, random, speed])


# name -> (command, match, parser)
_BLOCKS: dict[str, tuple[bytes, bytes, Callable[[bytes], dict]]] = {
    "battery": (b"\x12\x07", b"\x12\x07", parse_battery),
    "serial": (b"\x12\x12\x02", b"\x12\x12\x02", parse_serial),
    "profile": (b"\x12\x00", b"\x12\x00", parse_profile),
    "settings": (b"\x12\x04\x00", b"\x12\x04\x00", parse_settings),
    "dpi": (b"\x12\x04\x02", b"\x12\x04\x02", parse_dpi),
    "dpicolor": (b"\x12\x04\x03", b"\x12\x04\x03", parse_dpicolor),
    "led": (b"\x12\x03\x00", b"\x12\x03\x00", parse_led),
}
_READ_ORDER = ("serial", "profile", "settings", "dpi", "dpicolor", "led")


class MouseClient(HidClientBase):
    VID, PIDS, REPORT_ID, TIMEOUT = VID, PIDS, REPORT_ID, 0.5

    def __init__(self, parent: QObject | None = None, *, finder=None,
                 transport_factory: Callable[[str], HidTransport] | None = None):
        super().__init__(parent, finder=finder, transport_factory=transport_factory)
        self._led_written: dict[tuple, tuple] = {}   # raw LED value -> sRGB colour we wrote (worker thread)

    def _fresh_state(self, present: bool, permission: bool) -> MouseState:
        return MouseState(present=present, permission=permission)

    # -- reads (worker thread)
    def _read_blocks(self, *names: str) -> bool:
        """Read blocks into the state; False if the mouse did not answer the first one."""
        ok_first = True
        for k, name in enumerate(names):
            cmd, match, parser = _BLOCKS[name]
            r = self._ask(cmd, match)
            if r is None or is_error_reply(r):
                if k == 0:
                    ok_first = False
                    break
                continue
            for key, val in parser(r).items():
                if key == "led_rgb":
                    # exact colour if we wrote it (the decode is lossy for dark channels), else decoded
                    val = self._led_written.get(val) or led_decode(val)
                setattr(self._state, key, val)
        return ok_first

    def _read_all(self) -> None:
        st = self._state
        if not self._read_blocks("battery"):
            self._state = MouseState(present=True, permission=True, asleep=True, serial=st.serial)
            return
        st.asleep = False
        names = [n for n in _READ_ORDER if not (n == "serial" and st.serial)]
        self._read_blocks(*names)

    # -- writes
    def _write_job(self, writes: Callable[[], list[bytes]], reread: tuple[str, ...], save: bool = True,
                   local: Callable[[], None] | None = None) -> None:
        def job():
            if not self._ensure():
                self._publish()
                self._failed.emit("mouse not available")
                return
            cmds = writes()
            for c in cmds:
                self._tell(c)
            if save:
                self._tell(SAVE)
            if reread:
                if not self._read_blocks(*reread):
                    st = self._state
                    self._state = MouseState(present=True, permission=True, asleep=True,
                                             serial=st.serial)
            elif local:
                local()
            self._publish()
        self._submit(job)

    def _reject(self, exc: Exception) -> None:
        self.error.emit(str(exc))

    def set_dpi_stage_value(self, i: int, dpi: int) -> None:
        try:
            build_dpi_stage(i, dpi, (0, 0, 0))  # validate eagerly
        except ValueError as exc:
            return self._reject(exc)

        def writes():
            self._read_blocks("dpicolor")
            colors = self._state.dpi_colors
            if not colors:
                raise ValueError("DPI stage colour unknown; refusing to write")
            return [build_dpi_stage(i, dpi, colors[i])]
        self._write_job(writes, ("dpi",))

    def set_active_stage(self, stage: int) -> None:
        """``stage`` is 1-based (1..4)."""
        try:
            cmd = build_active_stage(stage)
        except ValueError as exc:
            return self._reject(exc)
        self._write_job(lambda: [cmd], ("profile",))

    def set_polling(self, hz: int) -> None:
        try:
            cmd = build_polling(hz)
        except ValueError as exc:
            return self._reject(exc)
        self._write_job(lambda: [cmd], ("settings",))

    def set_debounce(self, ms: int) -> None:
        try:
            cmd = build_debounce(ms)
        except ValueError as exc:
            return self._reject(exc)
        self._write_job(lambda: [cmd], ("settings",))

    def set_angle_snapping(self, on: bool) -> None:
        cmd = build_angle_snapping(bool(on))
        self._write_job(lambda: [cmd], ("settings",))

    def set_sleep(self, code: int) -> None:
        try:
            build_sleep(code, 0)
        except ValueError as exc:
            return self._reject(exc)

        def writes():
            self._read_blocks("battery")
            low = self._state.low_battery_pct
            if low is None:
                raise ValueError("low-battery level unknown; refusing to write")
            return [build_sleep(code, low)]
        self._write_job(writes, ("battery",))

    def set_led(self, mode: int, brightness: int, rgb, save: bool = True) -> None:
        try:
            build_led(mode, brightness, rgb)
        except ValueError as exc:
            return self._reject(exc)
        rgb_t = tuple(int(c) for c in rgb)

        def writes():
            st = self._state
            raw = led_encode(rgb_t)
            self._led_written[raw] = rgb_t
            return [build_led(mode, brightness, raw, st.led_direction or 0, st.led_random or 0,
                              st.led_speed or 0, zone=z) for z in LED_ZONES]

        def local():
            self._state.led_mode, self._state.led_brightness, self._state.led_rgb = mode, brightness, rgb_t
        # save=False (live Aura Sync): no save command, no re-read; the caller rate-limits (>=200 ms).
        self._write_job(writes, ("led",) if save else (), save=save, local=local)
