import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtTest import QSignalSpy

from alaz.backend.peripherals import mouse as M
from tests.backend_periph import FakeTransport, rep, settle

BATT = rep(3, "12 07 00 00 43 02 14 29 0f 00 00 01")
SERIAL = rep(3, "12 12 02 00 53 37 4d 50 4b 52 30 33 39 38 35 38")
PROFILE = rep(3, "12 00 00 00 08 00 07 00 05 07 00 02 ff ff 15 00 01")
SETTINGS = rep(3, "12 04 00 00 ff ff ff ff ff ff ff ff 03 00 02 00 00 00 00")
DPI = rep(3, "12 04 02 00 07 00 07 00 0f 00 0f 00 1f 00 1f 00 3f 00 3f")
DPICOL = rep(3, "12 04 03 00 ff 00 00 c1 00 ff 00 3d ff 31 ff 00")
LED = rep(3, "12 03 00 00 02 32 ff 00 00")


def replies():
    return {b"\x12\x07": BATT, b"\x12\x12\x02": SERIAL, b"\x12\x00": PROFILE,
            b"\x12\x04\x00": SETTINGS, b"\x12\x04\x02": DPI, b"\x12\x04\x03": DPICOL,
            b"\x12\x03\x00": LED}


# ---- parsers
def test_parse_battery():
    assert M.parse_battery(BATT) == {"battery_pct": 67, "sleep_code": 2, "low_battery_pct": 20,
                                     "charging": False}
    assert M.parse_battery(rep(3, "12 07 00 00 43 02 14 29 0f 01"))["charging"] is True


def test_parse_misc():
    assert M.parse_serial(SERIAL) == {"serial": "S7MPKR039858"}
    assert M.parse_profile(PROFILE) == {"profile": 0, "dpi_stage": 2}
    assert M.parse_settings(SETTINGS) == {"polling_hz": 1000, "debounce_ms": 12,
                                          "angle_snapping": False, "angle_tuning": 0}
    assert M.parse_dpi(DPI) == {"dpi_stages": [400, 800, 1600, 3200]}
    assert M.parse_dpicolor(DPICOL)["dpi_colors"] == [(255, 0, 0), (193, 0, 255), (0, 61, 255),
                                                      (49, 255, 0)]
    led = M.parse_led(LED)
    assert (led["led_mode"], led["led_brightness"], led["led_rgb"]) == (2, 50, (255, 0, 0))


# ---- builders
def test_builders_exact():
    assert M.build_dpi_stage(1, 800, (1, 2, 3)) == bytes.fromhex("513101000f00010203")
    assert M.build_dpi_stage(0, 100, (0, 0, 0))[4:6] == b"\x01\x00"
    assert M.build_dpi_stage(3, 42000, (0, 0, 0))[4:6] == (839).to_bytes(2, "little")
    assert M.build_active_stage(2) == bytes.fromhex("5131090002")
    assert M.build_polling(1000) == bytes.fromhex("5131040003")
    assert M.build_polling(125) == bytes.fromhex("5131040000")
    assert M.build_debounce(12) == bytes.fromhex("5131050002")
    assert M.build_debounce(8)[-1] == 1 and M.build_debounce(32)[-1] == 7
    assert M.build_angle_snapping(True) == bytes.fromhex("5131060001")
    assert M.build_sleep(3, 20) == bytes.fromhex("51370000030014")
    assert M.build_led(0, 80, (1, 2, 3)) == bytes.fromhex("512801000050010203000000")  # default = LED zone 0x01
    assert M.build_led(2, 50, (255, 0, 0), 1, 2, 3, zone=1) == bytes.fromhex("51280100023 2ff0000010203".replace(" ", ""))


@pytest.mark.parametrize("fn,args", [
    (M.build_dpi_stage, (4, 800, (0, 0, 0))), (M.build_dpi_stage, (0, 75, (0, 0, 0))),
    (M.build_dpi_stage, (0, 50, (0, 0, 0))), (M.build_dpi_stage, (0, 42050, (0, 0, 0))),
    (M.build_dpi_stage, (0, 800, (0, 0, 256))),
    (M.build_active_stage, (0,)), (M.build_active_stage, (5,)),
    (M.build_polling, (2000,)), (M.build_debounce, (6,)), (M.build_debounce, (36,)),
    (M.build_debounce, (10,)), (M.build_sleep, (7, 20)), (M.build_sleep, (1, 101)),
    (M.build_led, (3, 50, (0, 0, 0))), (M.build_led, (0, 101, (0, 0, 0))),
])
def test_builders_reject(fn, args):
    with pytest.raises(ValueError):
        fn(*args)


# ---- client
def client_with(tr, nodes=("/dev/hidraw3",)):
    created = []

    def factory(path):
        created.append(path)
        return tr
    return M.MouseClient(finder=lambda: list(nodes), transport_factory=factory), created


def test_refresh_full_state(qtbot):
    tr = FakeTransport(replies())
    c, _ = client_with(tr)
    spy = QSignalSpy(c.changed)
    c.refresh()
    settle(c)
    assert len(spy) == 1
    s = spy[0][0]
    assert (s.present, s.permission, s.asleep) == (True, True, False)
    assert (s.battery_pct, s.charging, s.sleep_code, s.low_battery_pct) == (67, False, 2, 20)
    assert (s.serial, s.profile, s.dpi_stage) == ("S7MPKR039858", 0, 2)
    assert s.dpi_stages == [400, 800, 1600, 3200] and s.polling_hz == 1000 and s.debounce_ms == 12
    assert s.led_mode == 2 and s.led_rgb == (255, 0, 0) and s.liftoff is None
    assert all(not c.startswith(b"\x51") for c in tr.requested())
    assert tr.sent() == []


def test_absent_no_io(qtbot):
    tr = FakeTransport(replies())
    c, created = client_with(tr, nodes=())
    spy = QSignalSpy(c.changed)
    c.refresh()
    settle(c)
    assert spy[0][0].present is False and created == [] and tr.log == []


def test_permission_denied(qtbot):
    tr = FakeTransport(replies(), deny=True)
    c, _ = client_with(tr)
    spy = QSignalSpy(c.changed)
    c.refresh()
    settle(c)
    s = spy[0][0]
    assert (s.present, s.permission) == (True, False) and tr.log == []


def test_asleep_on_error_or_timeout(qtbot):
    for first in (rep(3, "ff aa"), None):
        tr = FakeTransport({b"\x12\x07": first})
        c, _ = client_with(tr)
        spy = QSignalSpy(c.changed)
        c.refresh()
        settle(c)
        s = spy[0][0]
        assert (s.present, s.asleep, s.battery_pct, s.dpi_stages) == (True, True, None, None)
        assert len(tr.requested()) == 1


def test_set_dpi_sequence(qtbot):
    tr = FakeTransport(replies())
    c, _ = client_with(tr)
    c.refresh()
    settle(c)
    tr.log.clear()
    tr.replies[b"\x12\x04\x02"] = rep(3, "12 04 02 00 07 00 07 00 1f 00 1f 00 1f 00 1f 00 3f 00 3f")
    spy = QSignalSpy(c.changed)
    c.set_dpi_stage_value(1, 1600)
    settle(c)
    assert tr.log == [
        ("req", b"\x12\x04\x03"),
        ("send", bytes.fromhex("513101001f00c100ff")),
        ("send", b"\x50\x03"),
        ("req", b"\x12\x04\x02"),
    ]
    assert spy[0][0].dpi_stages[1] == 1600


def test_set_polling_and_sleep(qtbot):
    tr = FakeTransport(replies())
    c, _ = client_with(tr)
    c.refresh()
    settle(c)
    tr.log.clear()
    c.set_polling(500)
    c.set_sleep(4)
    settle(c)
    assert tr.log == [
        ("send", bytes.fromhex("5131040002")), ("send", b"\x50\x03"), ("req", b"\x12\x04\x00"),
        ("req", b"\x12\x07"), ("send", bytes.fromhex("51370000040014")), ("send", b"\x50\x03"),
        ("req", b"\x12\x07"),
    ]


def test_set_led_save_variants(qtbot):
    tr = FakeTransport(replies())
    c, _ = client_with(tr)
    c.refresh()
    settle(c)
    tr.log.clear()
    c.set_led(0, 80, (1, 2, 3), save=False)
    settle(c)
    # VERIFIED: zone 0x01 drives the physical LED; zone 0x00 is the copy the LED read reports -> write both
    assert tr.log == [("send", bytes.fromhex("512801000050010203000000")),
                      ("send", bytes.fromhex("512800000050010203000000"))]
    tr.log.clear()
    c.set_led(0, 80, (1, 2, 3))
    settle(c)
    assert [k for k, _ in tr.log] == ["send", "send", "send", "req"]
    assert tr.sent()[2] == b"\x50\x03"


def test_invalid_write_emits_error_no_io(qtbot):
    tr = FakeTransport(replies())
    c, _ = client_with(tr)
    errs = QSignalSpy(c.error)
    c.set_polling(2000)
    c.set_dpi_stage_value(9, 800)
    c.set_led(3, 10, (0, 0, 0))
    settle(c)
    assert len(errs) == 3 and tr.log == []


def test_io_failure_marks_absent(qtbot):
    class Boom(FakeTransport):
        def request(self, *a, **k):
            raise OSError(19, "gone")
    c, _ = client_with(Boom(replies()))
    spy = QSignalSpy(c.changed)
    c.refresh()
    settle(c)
    assert spy[0][0].present is False
