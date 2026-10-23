import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtTest import QSignalSpy

from alaz.backend.peripherals import headset as Hs
from tests.backend_periph import FakeTransport, rep, settle

R = 0xCC
CONN = rep(R, "12 00 00 01 01")
FW = rep(R, "12 00 00 00 00 05 00 04 00 05 00 04")  # VERIFIED reply bytes
POWER = rep(R, "12 07 00 00 05 57 14 01")
CHG = rep(R, "12 08 00 00 00")
LIGHT = rep(R, "12 03 00 00 01 32 ea b2 15")
SW = rep(R, "12 13 00 00 01")


def replies(sw=SW):
    return {b"\x12\x00\x00\x01": CONN, b"\x12\x00\x00\x00": FW, b"\x12\x07": POWER,
            b"\x12\x08": CHG, b"\x12\x03": LIGHT, b"\x12\x13": sw}


def test_parsers():
    assert Hs.parse_power(POWER) == {"battery_pct": 87}
    assert Hs.parse_power(rep(R, "12 07 00 00 05 fe"))["battery_pct"] is None
    assert Hs.parse_lighting(LIGHT) == {"light_effect": 1, "light_brightness": 50,
                                        "light_rgb": (0xEA, 0xB2, 0x15)}
    assert Hs.parse_swmode(SW) == {"software_led": True}
    assert Hs.parse_connected(CONN) == {"connected": True}
    assert Hs.parse_connected(rep(R, "12 00 00 01 00")) == {"connected": False}
    assert Hs.parse_charging(rep(R, "12 08 00 00 01")) == {"charging": True}
    assert Hs.parse_firmware(FW) == {"firmware": "4.0.5.0 / 4.0.5.0"}


def test_build_lighting_and_rejects():
    assert Hs.build_lighting(1, 50, (0xEA, 0xB2, 0x15)) == bytes.fromhex("512800000132eab215")
    for args in [(0, 50, (0, 0, 0)), (5, 50, (0, 0, 0)), (1, 101, (0, 0, 0)), (1, 50, (0, 0, 300))]:
        with pytest.raises(ValueError):
            Hs.build_lighting(*args)


def client_with(tr, nodes=("/dev/hidraw13",)):
    return Hs.HeadsetClient(finder=lambda: list(nodes), transport_factory=lambda p: tr)


def test_refresh_full(qtbot):
    tr = FakeTransport(replies())
    c = client_with(tr)
    spy = QSignalSpy(c.changed)
    c.refresh()
    settle(c)
    s = spy[0][0]
    assert (s.present, s.connected, s.battery_pct, s.charging) == (True, True, 87, False)
    assert (s.light_effect, s.light_brightness, s.light_rgb, s.software_led) == (1, 50, (234, 178, 21), True)
    assert s.firmware == "4.0.5.0 / 4.0.5.0" and tr.sent() == []


def test_headset_off(qtbot):
    off = {b"\x12\x00\x00\x01": rep(R, "12 00 00 01 00")}
    for k in (b"\x12\x00\x00\x00", b"\x12\x07", b"\x12\x08", b"\x12\x03", b"\x12\x13"):
        off[k] = rep(R, "ff aa")
    tr = FakeTransport(off)
    c = client_with(tr)
    spy = QSignalSpy(c.changed)
    c.refresh()
    settle(c)
    s = spy[0][0]
    assert (s.present, s.connected, s.battery_pct, s.light_effect) == (True, False, None, None)
    assert tr.requested() == [b"\x12\x00\x00\x01"]


def test_set_lighting_sequence(qtbot):
    tr = FakeTransport(replies())
    c = client_with(tr)
    c.refresh()
    settle(c)
    tr.log.clear()
    c.set_lighting(2, 70, (1, 2, 3))
    settle(c)
    assert tr.sent() == [bytes.fromhex("5110000000"), bytes.fromhex("512800000246010203")]
    assert tr.log[0][0] == "send" and tr.log[1][0] == "send"
    assert tr.requested()[0] == b"\x12\x03"


def test_set_lighting_skips_sw_off_when_already_off(qtbot):
    tr = FakeTransport(replies(sw=rep(R, "12 13 00 00 00")))
    c = client_with(tr)
    c.refresh()
    settle(c)
    tr.log.clear()
    c.set_lighting(1, 10, (0, 0, 0))
    settle(c)
    assert tr.sent() == [bytes.fromhex("5128000001" "0a000000")]


def test_absent_and_permission(qtbot):
    tr = FakeTransport(replies())
    c = client_with(tr, nodes=())
    spy = QSignalSpy(c.changed)
    c.refresh()
    settle(c)
    assert spy[0][0].present is False and tr.log == []
    tr2 = FakeTransport(replies(), deny=True)
    c2 = client_with(tr2)
    spy2 = QSignalSpy(c2.changed)
    c2.refresh()
    settle(c2)
    assert (spy2[0][0].present, spy2[0][0].permission) == (True, False) and tr2.log == []


def test_invalid_lighting_emits_error(qtbot):
    tr = FakeTransport(replies())
    c = client_with(tr)
    errs = QSignalSpy(c.error)
    c.set_lighting(9, 10, (0, 0, 0))
    settle(c)
    assert len(errs) == 1 and tr.log == []
