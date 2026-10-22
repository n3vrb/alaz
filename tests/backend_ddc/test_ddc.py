import subprocess

import pytest
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtTest import QTest

from alaz.backend import ddc
from alaz.backend.ddc import FEATURES, DdcClient, parse_detect, parse_getvcp

DETECT = """Invalid display
   I2C bus:          /dev/i2c-12
   DRM connector:    card1-eDP-1
   Monitor:          SDC:ATNA60DL01-0:

Display 1
   I2C bus:          /dev/i2c-13
   DRM connector:    card1-DP-1
   Monitor:          AUS:XG27UCDMG:T6LMAS028806
"""

GETVCP = {
    0x10: "VCP 10 C 30 100", 0x12: "VCP 12 C 80 100", 0x14: "VCP 14 CNC x00 x0b x00 x0b",
    0x60: "VCP 60 SNC x1a", 0xDC: "VCP DC SNC x02", 0xE2: "VCP E2 CNC x00 xfe x00 x00",
    0xE5: "VCP E5 CNC x00 x04 x00 x00", 0xE6: "VCP E6 CNC x00 x04 x00 x00",
    0xF8: "VCP F8 CNC x00 x08 x00 x08", 0xF9: "VCP F9 CNC x00 x03 x00 x02",
}


class FakeRun:
    def __init__(self, detect=DETECT, vcp=None, fail=None):
        self.calls = []
        self.detect = detect
        self.vcp = dict(vcp or GETVCP)
        self.fail = fail  # callable(argv) -> result|None

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if self.fail:
            r = self.fail(argv)
            if r is not None:
                return r
        if argv[1] == "detect":
            return 0, self.detect, ""
        if "getvcp" in argv:
            codes = [int(a, 16) for a in argv[argv.index("getvcp") + 1:]]
            return 0, "".join(self.vcp[c] + "\n" for c in codes), ""
        if "setvcp" in argv:
            code, val = int(argv[-2], 16), int(argv[-1])
            self.vcp[code] = f"VCP {code:02X} C {val} 100"
            return 0, "", ""
        return 1, "", "?"


def make(run):
    c = DdcClient(run=run, sleep=lambda s: None)
    got, errs = [], []
    c.changed.connect(got.append)
    c.error.connect(errs.append)
    return c, got, errs


def settle(c):
    c._pool.waitForDone()
    QCoreApplication.processEvents()


def test_parse_detect():
    ds = parse_detect(DETECT)
    assert len(ds) == 1
    d = ds[0]
    assert (d.bus, d.connector, d.model, d.serial) == (13, "card1-DP-1", "XG27UCDMG", "T6LMAS028806")
    assert parse_detect("") == []


@pytest.mark.parametrize("line,exp", [
    ("VCP 10 C 30 100", (0x10, 30, 100)),
    ("VCP DC SNC x02", (0xDC, 2, None)),
    ("VCP 14 CNC x00 x0b x00 x0b", (0x14, 0x0B, 0x0B)),
    ("VCP E2 CNC x00 xfe x00 x00", (0xE2, 0, 254)),
    ("VCP 60 SNC x1a", (0x60, 0x1A, None)),
])
def test_parse_getvcp(line, exp):
    v = parse_getvcp(line)
    assert (v.code, v.current, v.max) == exp


@pytest.mark.parametrize("line", ["", "garbage", "VCP 10 ERR", "VCP ZZ C 1 2", "DDC communication failed",
                                  "VCP 14 CNC x00 x0b"])
def test_parse_getvcp_bad(line):
    assert parse_getvcp(line) is None


def test_feature_table():
    assert {k: f.code for k, f in FEATURES.items()} == {
        "brightness": 0x10, "contrast": 0x12, "color_temp": 0x14, "gamevisual": 0xDC,
        "shadow_boost": 0xE5, "blue_light": 0xE6, "hdr": 0xE2, "screen_move": 0xF9,
        "pixel_clean_reminder": 0xF8, "input": 0x60}
    assert FEATURES["hdr"].kind == "readonly"
    assert FEATURES["input"].confirm
    assert sum(f.confirm for f in FEATURES.values()) == 1


def test_refresh():
    run = FakeRun()
    c, got, errs = make(run)
    c.refresh()
    settle(c)
    st = got[-1]
    assert st.present and st.bus == 13 and st.model == "XG27UCDMG"
    assert st.values["brightness"] == 30 and st.values["gamevisual"] == 2
    assert st.values["color_temp"] == 0x0B and st.values["input"] == 0x1A
    assert st.values["screen_move"] == 2 and st.values["hdr"] == 0
    assert not errs
    reads = [a for a in run.calls if "getvcp" in a]
    assert len(reads) == 1  # one batched ddcutil call for all features
    assert reads[0][:5] == ["ddcutil", "--bus", "13", "--brief", "getvcp"]
    assert set(reads[0][5:]) == {f"0x{f.code:02X}" for f in FEATURES.values()}


def test_locked_254():
    vcp = dict(GETVCP)
    vcp[0xE5] = "VCP E5 CNC x00 xfe x00 xfe"
    c, got, _ = make(FakeRun(vcp=vcp))
    c.refresh()
    settle(c)
    assert "shadow_boost" in got[-1].locked and got[-1].values["shadow_boost"] is None


def test_set_value_and_reread():
    run = FakeRun()
    c, got, _ = make(run)
    c.refresh()
    settle(c)
    run.calls.clear()
    assert c.set_value("brightness", 55)
    settle(c)
    assert run.calls[0] == ["ddcutil", "--bus", "13", "setvcp", "0x10", "55"]
    assert run.calls[1] == ["ddcutil", "--bus", "13", "--brief", "getvcp", "0x10"]
    assert got[-1].values["brightness"] == 55


@pytest.mark.parametrize("key,val,conf", [
    ("hdr", 0, True), ("nope", 1, True), ("brightness", 101, False), ("brightness", -1, False),
    ("gamevisual", 3, False), ("input", 0x1A, False), ("input", 0x33, True)])
def test_refused(key, val, conf):
    run = FakeRun()
    c, got, errs = make(run)
    assert c.set_value(key, val, confirmed=conf) is False
    settle(c)
    assert run.calls == [] and len(errs) == 1


def test_input_confirmed():
    run = FakeRun()
    c, _, errs = make(run)
    assert c.set_value("input", 0x0F, confirmed=True)
    settle(c)
    assert ["ddcutil", "--bus", "13", "setvcp", "0x60", "15"] in run.calls
    assert not errs


def test_debounce():
    run = FakeRun()
    c, got, _ = make(run)
    c.refresh()
    settle(c)
    run.calls.clear()
    for v in (10, 20, 30, 40):
        c.set_value_debounced("brightness", v, ms=30)
    QTest.qWait(150)
    settle(c)
    sets = [a for a in run.calls if "setvcp" in a]
    assert sets == [["ddcutil", "--bus", "13", "setvcp", "0x10", "40"]]


def test_partial_failure():
    # ddcutil exits non-zero and omits the codes it could not read
    def fail(argv):
        if "getvcp" in argv:
            lines = [GETVCP[int(x, 16)] for x in argv[argv.index("getvcp") + 1:] if x not in ("0x12", "0xDC")]
            return 1, "\n".join(lines) + "\n", "boom"
    c, got, errs = make(FakeRun(fail=fail))
    c.refresh()
    settle(c)
    st = got[-1]
    assert st.values["contrast"] is None and st.values["gamevisual"] is None
    assert st.values["brightness"] == 30
    assert errs


def test_timeout_whole_call():
    def fail(argv):
        if "getvcp" in argv:
            raise subprocess.TimeoutExpired(argv, 8)
    c, got, errs = make(FakeRun(fail=fail))
    c.refresh()
    settle(c)
    st = got[-1]
    assert all(v is None for v in st.values.values()) and st.values
    assert errs


def test_absent_monitor():
    c, got, _ = make(FakeRun(detect="Invalid display\n   I2C bus:  /dev/i2c-12\n"
                                    "   DRM connector:    card1-eDP-1\n   Monitor:   SDC:X:\n"))
    c.refresh()
    settle(c)
    assert got[-1].present is False and got[-1].values == {}


def test_internal_never_chosen_even_if_aus():
    d = "Display 1\n   I2C bus:  /dev/i2c-5\n   DRM connector:    card1-eDP-1\n   Monitor:   AUS:PANEL:\n"
    c, got, _ = make(FakeRun(detect=d))
    c.refresh()
    settle(c)
    assert got[-1].present is False


def test_detect_failure():
    c, got, _ = make(FakeRun(fail=lambda a: (1, "", "no ddcutil") if a[1] == "detect" else None))
    c.refresh()
    settle(c)
    assert got[-1].present is False
