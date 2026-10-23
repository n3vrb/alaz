"""ROG Pelta headset via its 2.4 GHz dongle (report 0xCC). Protocol: docs/PERIPHERALS.md.

Builders return the command bytes AFTER the report id (the transport prepends 0xCC).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QObject

from .hidraw import HidClientBase, HidTransport, is_error_reply, pad

log = logging.getLogger(__name__)

VID = 0x0B05
PIDS = {0x1B84, 0x1B82}  # dongle / USB-C cable (cable = SOURCE only)
REPORT_ID = 0xCC

EFFECTS = (1, 2, 3, 4)  # static, breathing, strobing, colour cycle
SOFTWARE_LED_OFF = b"\x51\x10\x00\x00\x00"


@dataclass
class HeadsetState:
    present: bool = False
    permission: bool = True
    connected: bool | None = None   # headset powered on / paired
    firmware: str | None = None
    battery_pct: int | None = None
    charging: bool | None = None
    light_effect: int | None = None
    light_brightness: int | None = None
    light_rgb: tuple[int, int, int] | None = None
    software_led: bool | None = None


def parse_connected(r: bytes) -> dict:
    return {"connected": pad(r)[5] == 1}


def parse_firmware(r: bytes) -> dict:
    d = pad(r)[5:13]
    if not any(d):
        return {"firmware": None}
    # two little-endian 32-bit values, most significant byte first in the version string
    # (VERIFIED: 00 05 00 04 00 05 00 04 -> "4.0.5.0 / 4.0.5.0")
    return {"firmware": ".".join(map(str, d[3::-1])) + " / " + ".".join(map(str, d[7:3:-1]))}


def parse_power(r: bytes) -> dict:
    b = pad(r)[6]
    return {"battery_pct": b if b <= 100 else None}  # 0xFE = unknown


def parse_charging(r: bytes) -> dict:
    return {"charging": pad(r)[5] == 1}


def parse_lighting(r: bytes) -> dict:
    r = pad(r)
    return {"light_effect": r[5], "light_brightness": r[6] if r[6] <= 100 else None,
            "light_rgb": tuple(r[7:10])}


def parse_swmode(r: bytes) -> dict:
    return {"software_led": pad(r)[5] == 1}


def build_lighting(effect: int, brightness: int, rgb) -> bytes:
    if effect not in EFFECTS:
        raise ValueError(f"effect {effect} not in {EFFECTS}")
    if not 0 <= brightness <= 100:
        raise ValueError(f"brightness {brightness} outside 0..100")
    if len(rgb) != 3 or any(not 0 <= int(c) <= 255 for c in rgb):
        raise ValueError(f"bad RGB {rgb!r}")
    return bytes([0x51, 0x28, 0x00, 0x00, effect, brightness]) + bytes(int(c) for c in rgb)


# name -> (command, match, parser)
_BLOCKS: dict[str, tuple[bytes, bytes, Callable[[bytes], dict]]] = {
    "connected": (b"\x12\x00\x00\x01", b"\x12\x00\x00\x01", parse_connected),
    "firmware": (b"\x12\x00\x00\x00", b"\x12\x00\x00\x00", parse_firmware),
    "power": (b"\x12\x07", b"\x12\x07", parse_power),
    "charging": (b"\x12\x08", b"\x12\x08", parse_charging),
    "lighting": (b"\x12\x03", b"\x12\x03", parse_lighting),
    "swmode": (b"\x12\x13", b"\x12\x13", parse_swmode),
}


class HeadsetClient(HidClientBase):
    VID, PIDS, REPORT_ID, TIMEOUT = VID, PIDS, REPORT_ID, 1.0

    def __init__(self, parent: QObject | None = None, *, finder=None,
                 transport_factory: Callable[[str], HidTransport] | None = None):
        super().__init__(parent, finder=finder, transport_factory=transport_factory)

    def _fresh_state(self, present: bool, permission: bool) -> HeadsetState:
        return HeadsetState(present=present, permission=permission)

    def _read_blocks(self, *names: str) -> None:
        for name in names:
            cmd, match, parser = _BLOCKS[name]
            r = self._ask(cmd, match)
            if r is None or is_error_reply(r):
                continue
            for key, val in parser(r).items():
                setattr(self._state, key, val)

    def _read_all(self) -> None:
        st = self._state
        self._read_blocks("connected")
        if not st.connected:
            # Headset off (or dongle silent): everything else would be ff aa. Keep nothing stale.
            self._state = HeadsetState(present=True, permission=True, connected=st.connected,
                                       firmware=st.firmware)
            return
        self._read_blocks("firmware", "power", "charging", "lighting", "swmode")

    def set_lighting(self, effect: int, brightness: int, rgb) -> None:
        try:
            cmd = build_lighting(effect, brightness, rgb)
        except ValueError as exc:
            self.error.emit(str(exc))
            return

        def job():
            if not self._ensure():
                self._publish()
                self._failed.emit("headset dongle not available")
                return
            if self._state.software_led is not False:
                self._tell(SOFTWARE_LED_OFF)
            self._tell(cmd)
            # 12 13 is re-read as well so software_led reflects the device (avoids a blind resend).
            self._read_blocks("lighting", "swmode")
            self._publish()
        self._submit(job)
