"""AsusdClient tests.

Write paths are never sent to the real daemon: dbus_util.async_call is
monkeypatched and the exact interface/method/arguments are asserted.  A
separate test checks the wire-level D-Bus types on a throw-away private bus.
"""
import os
import shutil
import subprocess
import tempfile
import time

import pytest
from PyQt6.QtCore import QCoreApplication, QElapsedTimer
from PyQt6.QtDBus import QDBusConnection

from alaz.backend import asusd, dbus_util
from alaz.backend.asusd import AsusdClient
from alaz.backend.dbus_util import Typed, Variant
from alaz.backend.types import FanCurve, Profile

app = QCoreApplication.instance() or QCoreApplication([])


def spin(ms):
    t = QElapsedTimer()
    t.start()
    while t.elapsed() < ms:
        app.processEvents()
        time.sleep(0.005)


class Recorder:
    """Stand-in for dbus_util.async_call; optionally scripts replies."""

    def __init__(self):
        self.calls = []
        self.replies = {}

    def __call__(self, bus, service, path, interface, method, args=None, callback=None, timeout_ms=0):
        self.calls.append((service, path, interface, method, list(args or [])))
        if callback is not None:
            result, error = self.replies.get((path, method), ([], None))
            callback(result, error)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(dbus_util, "async_call", r)
    return r


@pytest.fixture
def client(rec):
    c = AsusdClient()
    c.errors = []
    c.error.connect(lambda op, msg: c.errors.append((op, msg)))
    return c


def set_call(iface, name, sig, value, path="/org/asuslinux"):
    return ("org.asuslinux.Daemon", path, "org.freedesktop.DBus.Properties", "Set",
            [iface, name, Variant(sig, value)])


@pytest.mark.parametrize(
    "name,value,sig,expected",
    [
        ("ChargeControlEndThreshold", 80, "y", 80),
        ("NvDynamicBoost", 5, "y", 5),
        ("PptPl1Spl", 45, "y", 45),
        ("ThrottleThermalPolicy", Profile.PERFORMANCE, "u", 1),
        ("ThrottleQuietEpp", 4, "u", 4),
        ("PanelOd", 1, "b", True),
        ("BootSound", False, "b", False),
    ],
)
def test_set_platform_types(client, rec, name, value, sig, expected):
    client.set_platform(name, value)
    assert rec.calls == [set_call("org.asuslinux.Platform", name, sig, expected)]
    assert client.errors == []


@pytest.mark.parametrize("name,value", [("ChargeControlEndThreshold", 300), ("ChargeControlEndThreshold", -1),
                                        ("DgpuDisable", True), ("GpuMuxMode", 0), ("Nope", 1),
                                        ("PptFppt", "abc")])
def test_set_platform_rejects_bad_input_without_calling(client, rec, name, value):
    client.set_platform(name, value)
    assert rec.calls == []
    assert len(client.errors) == 1 and client.errors[0][0] == f"set_platform:{name}"


def test_set_platform_dbus_error_is_emitted(client, rec):
    rec.replies[("/org/asuslinux", "Set")] = (None, "org.freedesktop.DBus.Error.AccessDenied: no")
    client.set_platform("PanelOd", True)
    assert client.errors == [("set_platform:PanelOd", "org.freedesktop.DBus.Error.AccessDenied: no")]


def test_platform_types_table():
    for name, sig in asusd.PLATFORM_TYPES.items():
        assert sig in ("y", "u", "b"), name
    for ro in ("GpuMuxMode", "DgpuDisable", "Version"):
        assert ro not in asusd.PLATFORM_TYPES


def test_fan_curve_calls(client, rec):
    curve = FanCurve("CPU", (0, 59, 62, 65, 68, 71, 74, 76), (2, 25, 38, 51, 63, 81, 99, 117), True)
    client.set_fan_curve(Profile.QUIET, curve)
    client.set_fan_curve_enabled(Profile.BALANCED, "GPU", True)
    client.reset_fan_curves(Profile.PERFORMANCE)
    base = ("org.asuslinux.Daemon", "/org/asuslinux", "org.asuslinux.FanCurves")
    assert rec.calls == [
        (*base, "SetFanCurve", [Typed("u", 2), Typed("(s(yyyyyyyy)(yyyyyyyy)b)",
            ("CPU", (2, 25, 38, 51, 63, 81, 99, 117), (0, 59, 62, 65, 68, 71, 74, 76), True))]),
        (*base, "SetProfileFanCurveEnabled", [Typed("u", 0), Typed("s", "GPU"), Typed("b", True)]),
        (*base, "ResetProfileCurves", [Typed("u", 1)]),
    ]


def test_set_fan_curve_validates(client, rec):
    client.set_fan_curve(Profile.QUIET, FanCurve("CPU", (1, 2), (1, 2), True))
    client.set_fan_curve(Profile.QUIET, FanCurve("CPU", (300,) * 8, (1,) * 8, True))
    assert rec.calls == [] and len(client.errors) == 2


def test_fetch_fan_curves_parses_pwm_then_temps(client, rec):
    raw = [[("CPU", (2, 25, 38, 51, 63, 81, 99, 117), (0, 59, 62, 65, 68, 71, 74, 76), False)]]
    rec.replies[("/org/asuslinux", "FanCurveData")] = (raw, None)
    got = []
    client.fetch_fan_curves(Profile.BALANCED, got.append)
    assert rec.calls == [("org.asuslinux.Daemon", "/org/asuslinux", "org.asuslinux.FanCurves",
                          "FanCurveData", [Typed("u", 0)])]
    assert got == [[FanCurve("CPU", (0, 59, 62, 65, 68, 71, 74, 76), (2, 25, 38, 51, 63, 81, 99, 117), False)]]


def test_fetch_fan_curves_error_gives_empty_list(client, rec):
    rec.replies[("/org/asuslinux", "FanCurveData")] = (None, "boom")
    got = []
    client.fetch_fan_curves(Profile.QUIET, got.append)
    assert got == [[]] and client.errors == [("fetch_fan_curves", "boom")]


ROOT_XML = '<node><interface name="org.asuslinux.Platform"/><node name="19b6_3_6"/><node name="other"/></node>'
AURA_XML = '<node><interface name="org.asuslinux.Aura"/></node>'
OTHER_XML = '<node><interface name="org.freedesktop.DBus.Peer"/></node>'


def script_aura(rec):
    rec.replies[("/org/asuslinux", "Introspect")] = ([ROOT_XML], None)
    rec.replies[("/org/asuslinux/19b6_3_6", "Introspect")] = ([AURA_XML], None)
    rec.replies[("/org/asuslinux/other", "Introspect")] = ([OTHER_XML], None)


def test_aura_discovery_and_brightness(client, rec):
    script_aura(rec)
    client.set_kbd_brightness(2)
    assert client.aura_path == "/org/asuslinux/19b6_3_6"
    assert rec.calls[-1] == set_call("org.asuslinux.Aura", "Brightness", "u", 2, "/org/asuslinux/19b6_3_6")


def test_aura_discovery_skips_non_aura_children(client, rec):
    rec.replies[("/org/asuslinux", "Introspect")] = ([ROOT_XML], None)
    rec.replies[("/org/asuslinux/19b6_3_6", "Introspect")] = ([OTHER_XML], None)
    rec.replies[("/org/asuslinux/other", "Introspect")] = ([AURA_XML], None)
    client.set_kbd_brightness(0)
    assert client.aura_path == "/org/asuslinux/other"


def test_aura_missing_reports_error(client, rec):
    rec.replies[("/org/asuslinux", "Introspect")] = (["<node/>"], None)
    client.set_kbd_brightness(1)
    assert ("set_kbd_brightness", "no Aura device found") in client.errors


def test_brightness_out_of_range(client, rec):
    client.set_kbd_brightness(4)
    assert rec.calls == [] and len(client.errors) == 1


def test_aura_static_uses_cached_speed(client, rec):
    script_aura(rec)
    client._aura["LedModeData"] = (0, 0, (1, 2, 3), (0, 0, 0), 245, 1)
    client.set_aura_static((10, 20, 30))
    assert rec.calls[-1] == set_call(
        "org.asuslinux.Aura", "LedModeData", "(uu(yyy)(yyy)uu)",
        (0, 0, (10, 20, 30), (0, 0, 0), 245, 1), "/org/asuslinux/19b6_3_6")


def test_aura_static_validates_colour(client, rec):
    client.set_aura_static((256, 0, 0))
    assert rec.calls == [] and len(client.errors) == 1


def test_refresh_populates_cache_and_signals(client, rec):
    script_aura(rec)
    rec.replies[("/org/asuslinux", "GetAll")] = ([{"PanelOd": True, "ChargeControlEndThreshold": 90}], None)
    rec.replies[("/org/asuslinux/19b6_3_6", "GetAll")] = ([{"Brightness": 3}], None)
    plat, aura = [], []
    client.platformChanged.connect(lambda n, v: plat.append((n, v)))
    client.auraChanged.connect(lambda n, v: aura.append((n, v)))
    client.refresh()
    assert client.available is True
    assert sorted(plat) == [("ChargeControlEndThreshold", 90), ("PanelOd", True)]
    assert aura == [("Brightness", 3)]
    assert client.get_cached("ChargeControlEndThreshold") == 90
    assert client.get_cached("Missing") is None
    assert client.get_aura_cached("Brightness") == 3
    # refresh is read-only
    assert {c[3] for c in rec.calls} <= {"GetAll", "Introspect"}


def test_refresh_failure_marks_unavailable(client, rec):
    rec.replies[("/org/asuslinux", "GetAll")] = (None, "org.freedesktop.DBus.Error.ServiceUnknown: x")
    client.refresh()
    assert client.available is False
    assert client.errors[0][0] == "refresh"


def test_properties_changed_signal_updates_cache(client, rec):
    seen = []
    client.platformChanged.connect(lambda n, v: seen.append((n, v)))
    client._on_platform_signal("org.asuslinux.Platform", {"ThrottleThermalPolicy": 2}, [])
    client._on_platform_signal("org.other", {"X": 1}, [])
    assert seen == [("ThrottleThermalPolicy", 2)]
    assert client.get_cached("ThrottleThermalPolicy") == 2


def test_invalidated_properties_are_refetched(client, rec):
    rec.replies[("/org/asuslinux", "Get")] = ([4], None)
    client._on_platform_signal("org.asuslinux.Platform", {}, ["ThrottleQuietEpp"])
    assert rec.calls[-1][3] == "Get"
    assert client.get_cached("ThrottleQuietEpp") == 4


# ---------------------------------------------------------------- wire types
@pytest.mark.skipif(not (shutil.which("dbus-daemon") and shutil.which("dbus-monitor")),
                    reason="dbus-daemon/dbus-monitor not installed")
def test_wire_types_on_private_bus():
    """Send the exact write messages to a throw-away private bus and inspect them."""
    tmp = tempfile.mkdtemp(prefix="rcb", dir="/tmp")
    addr = f"unix:path={tmp}/bus"
    daemon = subprocess.Popen(["dbus-daemon", "--session", f"--address={addr}", "--nofork"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mon = None
    try:
        for _ in range(100):
            if os.path.exists(f"{tmp}/bus"):
                break
            time.sleep(0.02)
        mon = subprocess.Popen(["dbus-monitor", "--address", addr], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
        time.sleep(0.5)
        bus = QDBusConnection.connectToBus(addr, "wire-test")
        assert bus.isConnected()
        c = AsusdClient(bus=bus)
        c.aura_path = "/org/asuslinux/19b6_3_6"
        c.set_platform("ChargeControlEndThreshold", 80)
        c.set_platform("ThrottleThermalPolicy", 1)
        c.set_platform("PanelOd", True)
        c.set_fan_curve(Profile.QUIET, FanCurve("CPU", (0, 59, 62, 65, 68, 71, 74, 76),
                                                (2, 25, 38, 51, 63, 81, 99, 117), True))
        c.set_aura_static((1, 2, 3))
        spin(500)
        time.sleep(0.3)
        mon.terminate()
        out = mon.communicate(timeout=5)[0]
    finally:
        if mon and mon.poll() is None:
            mon.kill()
        daemon.terminate()
        daemon.wait(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)
    flat = " ".join(out.split())
    assert 'member=Set string "org.asuslinux.Platform" string "ChargeControlEndThreshold" variant byte 80' in flat
    assert 'string "ThrottleThermalPolicy" variant uint32 1' in flat
    assert 'string "PanelOd" variant boolean true' in flat
    assert 'member=SetFanCurve uint32 2 struct { string "CPU" struct { byte 2 byte 25' in flat
    assert ('variant struct { uint32 0 uint32 0 struct { byte 1 byte 2 byte 3 } '
            'struct { byte 0 byte 0 byte 0 } uint32 235 uint32 0 }') in flat
