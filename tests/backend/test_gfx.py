"""GfxClient tests.  Nothing here changes the system: no pkexec, no GPU mode calls."""
import os
import re
import stat
import time

import pytest
from PyQt6.QtCore import QCoreApplication, QElapsedTimer
from PyQt6.QtDBus import QDBusConnection

from alaz.backend import dbus_util, gfx
from alaz.backend.gfx import GfxClient
from alaz.backend.types import GfxMode, GfxPower

app = QCoreApplication.instance() or QCoreApplication([])


def spin_until(cond, timeout_ms=3000):
    t = QElapsedTimer()
    t.start()
    while not cond() and t.elapsed() < timeout_ms:
        app.processEvents()
        time.sleep(0.005)
    return cond()


class Recorder:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = replies or {}

    def __call__(self, bus, service, path, interface, method, args=None, callback=None, timeout_ms=0):
        self.calls.append((service, path, interface, method, list(args or [])))
        if callback is not None:
            result, error = self.replies.get(method, (None, "no scripted reply"))
            callback(result, error)


def test_module_never_uses_mode_changing_methods():
    pattern = re.compile(r"\bSet(Mode|Config)\b")
    here = os.path.dirname(gfx.__file__)
    for name in ("gfx.py", "asusd.py", "dbus_util.py"):
        with open(os.path.join(here, name), encoding="utf-8") as fh:
            assert not pattern.search(fh.read()), name


def test_refresh_with_scripted_replies(monkeypatch):
    rec = Recorder({
        "Mode": ([0], None), "Power": ([1], None), "Supported": ([[1, 0, 5]], None),
        "PendingMode": ([6], None), "PendingUserAction": ([4], None),
        "Vendor": (["Nvidia"], None), "Version": (["5.2.7"], None),
    })
    monkeypatch.setattr(dbus_util, "async_call", rec)
    c = GfxClient()
    modes, powers = [], []
    c.modeChanged.connect(modes.append)
    c.powerChanged.connect(powers.append)
    c.refresh()
    assert c.available and c.mode == GfxMode.HYBRID and c.power == GfxPower.SUSPENDED
    assert c.supported == [GfxMode.INTEGRATED, GfxMode.HYBRID, GfxMode.ASUS_MUX_DGPU]
    assert c.pending_mode is None and c.pending_action == 4
    assert (c.vendor, c.version) == ("Nvidia", "5.2.7")
    assert modes == [0] and powers == [1]
    # only read-only methods, always with no arguments
    assert {x[3] for x in rec.calls} == {"Mode", "Power", "Supported", "PendingMode",
                                         "PendingUserAction", "Vendor", "Version"}
    assert all(x[4] == [] for x in rec.calls)
    c.refresh()
    assert modes == [0] and powers == [1]  # unchanged values do not re-emit


def test_pending_mode_reported(monkeypatch):
    rec = Recorder({"Mode": ([0], None), "Power": ([0], None), "Supported": ([[0, 1]], None),
                    "PendingMode": ([1], None), "PendingUserAction": ([3], None),
                    "Vendor": (["x"], None), "Version": (["y"], None)})
    monkeypatch.setattr(dbus_util, "async_call", rec)
    c = GfxClient()
    c.refresh()
    assert c.pending_mode == GfxMode.INTEGRATED


def test_unknown_values_become_none(monkeypatch):
    rec = Recorder({"Mode": ([99], None), "Power": ([77], None), "Supported": ([[0, 42]], None),
                    "PendingMode": ([6], None), "PendingUserAction": ([None], None),
                    "Vendor": (["v"], None), "Version": (["1"], None)})
    monkeypatch.setattr(dbus_util, "async_call", rec)
    c = GfxClient()
    c.refresh()
    assert c.mode is None and c.power is None
    assert c.supported == [GfxMode.HYBRID]
    assert c.pending_action is None


def test_refresh_failure_leaves_unavailable(monkeypatch):
    monkeypatch.setattr(dbus_util, "async_call", Recorder())
    c = GfxClient()
    c.refresh()
    assert c.available is False and c.mode is None


def test_status_signal_updates_power(monkeypatch):
    monkeypatch.setattr(dbus_util, "async_call", Recorder())
    c = GfxClient()
    seen = []
    c.powerChanged.connect(seen.append)
    c._on_status_signal([0])
    c._on_status_signal([0])
    assert seen == [0] and c.power == GfxPower.ACTIVE


# ----------------------------------------------------------------- filesystem
def test_configured_boot_mode(tmp_path):
    conf = tmp_path / "supergfxd.conf"
    c = GfxClient(conf_path=str(conf))
    assert c.configured_boot_mode() is None  # missing
    conf.write_text('{"mode": "Integrated", "always_reboot": true}')
    assert c.configured_boot_mode() == GfxMode.INTEGRATED
    conf.write_text('{"mode": "Hybrid"}')
    assert c.configured_boot_mode() == GfxMode.HYBRID
    conf.write_text('{"mode": "Bogus"}')
    assert c.configured_boot_mode() is None
    conf.write_text("not json")
    assert c.configured_boot_mode() is None


def test_dgpu_disabled(tmp_path):
    f = tmp_path / "dgpu_disable"
    c = GfxClient(dgpu_disable_path=str(f))
    assert c.dgpu_disabled() is None
    f.write_text("1\n")
    assert c.dgpu_disabled() is True
    f.write_text("0\n")
    assert c.dgpu_disabled() is False
    f.write_text("weird")
    assert c.dgpu_disabled() is None


def _pci(root, name, vendor, klass):
    d = root / name
    d.mkdir()
    (d / "vendor").write_text(vendor + "\n")
    (d / "class").write_text(klass + "\n")


def test_nvidia_pci_path_scan(tmp_path):
    _pci(tmp_path, "0000:00:02.0", "0x8086", "0x030000")      # Intel iGPU
    _pci(tmp_path, "0000:01:00.1", "0x10de", "0x040300")      # NVIDIA audio function
    _pci(tmp_path, "0000:01:00.0", "0x10de", "0x030200")      # NVIDIA 3D controller
    c = GfxClient(pci_root=str(tmp_path))
    assert c.nvidia_pci_path() == str(tmp_path / "0000:01:00.0")
    assert GfxClient(pci_root=str(tmp_path / "missing")).nvidia_pci_path() is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert GfxClient(pci_root=str(empty)).nvidia_pci_path() is None


def test_defaults_match_contract():
    assert gfx.HELPER_PATH == "/usr/local/libexec/alaz-gfx-helper"
    c = GfxClient()
    assert c.helper_path == gfx.HELPER_PATH and c.launcher == ["pkexec"]


# --------------------------------------------------------------- boot request
class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class FakeProcess:
    instances = []

    def __init__(self, parent=None):
        self.finished, self.errorOccurred = FakeSignal(), FakeSignal()
        self.started = None
        self.out, self.err = b"", b""
        FakeProcess.instances.append(self)

    def start(self, program, args):
        self.started = (program, list(args))

    def readAllStandardOutput(self):
        return self.out

    def readAllStandardError(self):
        return self.err

    def deleteLater(self):
        pass


@pytest.mark.parametrize("mode,arg", [(GfxMode.INTEGRATED, "integrated"), (GfxMode.HYBRID, "hybrid")])
def test_request_boot_mode_command_line(mode, arg):
    FakeProcess.instances.clear()
    c = GfxClient()
    c.process_factory = FakeProcess
    results = []
    c.request_boot_mode(mode, lambda ok, msg: results.append((ok, msg)))
    proc = FakeProcess.instances[0]
    assert proc.started == ("pkexec", ["/usr/local/libexec/alaz-gfx-helper", "set-boot-mode", arg])
    proc.out = b"done\n"
    proc.finished.slots[0](0, None)
    assert results == [(True, "done")]
    assert c._process is None


def test_request_boot_mode_failure_message():
    FakeProcess.instances.clear()
    c = GfxClient()
    c.process_factory = FakeProcess
    results = []
    c.request_boot_mode(GfxMode.HYBRID, lambda ok, msg: results.append((ok, msg)))
    proc = FakeProcess.instances[0]
    proc.err = b"Eco'dan cikis henuz desteklenmiyor\n"
    proc.finished.slots[0](3, None)
    proc.finished.slots[0](0, None)  # a second finish must not call back again
    assert results == [(False, "Eco'dan cikis henuz desteklenmiyor")]


@pytest.mark.parametrize("mode", [GfxMode.VFIO, GfxMode.ASUS_MUX_DGPU, GfxMode.NONE, 42])
def test_request_boot_mode_rejects_unsupported(mode):
    FakeProcess.instances.clear()
    c = GfxClient()
    c.process_factory = FakeProcess
    results = []
    c.request_boot_mode(mode, lambda ok, msg: results.append((ok, msg)))
    assert FakeProcess.instances == []
    assert results and results[0][0] is False


def test_request_boot_mode_busy():
    FakeProcess.instances.clear()
    c = GfxClient()
    c.process_factory = FakeProcess
    results = []
    c.request_boot_mode(GfxMode.HYBRID, lambda ok, msg: results.append((ok, msg)))
    c.request_boot_mode(GfxMode.INTEGRATED, lambda ok, msg: results.append((ok, msg)))
    assert len(FakeProcess.instances) == 1 and results[0][0] is False


def test_request_boot_mode_failed_to_start():
    from PyQt6.QtCore import QProcess

    FakeProcess.instances.clear()
    c = GfxClient()
    c.process_factory = FakeProcess
    results = []
    c.request_boot_mode(GfxMode.HYBRID, lambda ok, msg: results.append((ok, msg)))
    FakeProcess.instances[0].errorOccurred.slots[0](QProcess.ProcessError.FailedToStart)
    assert results == [(False, "could not start pkexec")] and c._process is None


@pytest.mark.parametrize("code,ok", [(0, True), (3, False)])
def test_request_boot_mode_real_qprocess_with_stub_helper(tmp_path, code, ok):
    """Real QProcess, but a stub script instead of pkexec/the real helper."""
    stub = tmp_path / "helper"
    redirect = ">&2" if code else ""
    stub.write_text(f'#!/bin/sh\necho "$@" {redirect}\nexit {code}\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    c = GfxClient(helper_path=str(stub))
    c.launcher = []
    results = []
    c.request_boot_mode(GfxMode.INTEGRATED, lambda o, m: results.append((o, m)))
    assert spin_until(lambda: bool(results))
    assert results == [(ok, "set-boot-mode integrated")]


# ----------------------------------------------------------- live (read-only)
def _service_present():
    bus = QDBusConnection.systemBus()
    return bus.isConnected() and bus.interface().isServiceRegistered("org.supergfxctl.Daemon").value()


@pytest.mark.skipif(not _service_present(), reason="supergfxd not running")
def test_live_read_only_refresh():
    c = GfxClient()
    c.refresh()
    assert spin_until(lambda: c.mode is not None and c.power is not None and c.supported)
    assert c.available
    assert c.mode in list(GfxMode) and c.power in list(GfxPower)
    assert c.mode in c.supported


def test_request_boot_mode_stores_exit_code():
    FakeProcess.instances.clear()
    c = GfxClient()
    c.process_factory = FakeProcess
    seen = []
    c.request_boot_mode(GfxMode.HYBRID, lambda ok, msg: seen.append(c.last_exit_code))
    FakeProcess.instances[0].finished.slots[0](126, None)
    assert seen == [126]


# ------------------------------------------------------------------ live switch
import json as _json

from alaz.backend.gfx import Holder, LiveResult, parse_live_result


def _live_client():
    FakeProcess.instances.clear()
    c = GfxClient()
    c.process_factory = FakeProcess
    return c


@pytest.mark.parametrize("mode,arg", [(GfxMode.INTEGRATED, "live-eco"), (GfxMode.HYBRID, "live-hybrid")])
def test_request_live_command_line_and_ok(mode, arg):
    c = _live_client()
    results = []
    c.request_live(mode, results.append)
    proc = FakeProcess.instances[0]
    assert proc.started == ("pkexec", ["/usr/local/libexec/alaz-gfx-helper", arg])
    proc.out = b'log line\n{"ok": true, "mode": "Integrated", "changed": true}\n'
    proc.finished.slots[0](0, None)
    proc.finished.slots[0](0, None)          # second finish ignored
    assert len(results) == 1 and results[0].ok and results[0].code == 0 and results[0].error is None
    assert c._live_process is None and c.last_exit_code == 0


def test_request_live_busy_parses_holders():
    c = _live_client()
    results = []
    c.request_live(GfxMode.INTEGRATED, results.append)
    proc = FakeProcess.instances[0]
    h = {"pid": 7, "comm": "firefox", "user": "enes", "exe": "/usr/bin/firefox", "nodes": ["/dev/nvidia0"]}
    proc.out = (_json.dumps({"ok": False, "error": "busy", "holders": [h]}) + "\n").encode()
    proc.finished.slots[0](9, None)
    r = results[0]
    assert not r.ok and r.code == 9 and r.error == "busy" and not r.reboot_required
    assert r.holders == [Holder(7, "firefox", "enes", "/usr/bin/firefox", ["/dev/nvidia0"])]


@pytest.mark.parametrize("code,out,error,reboot", [
    (4, '{"ok": false, "error": "mux"}', "mux", False),
    (7, '{"ok": false, "error": "supergfxd"}', "supergfxd", False),
    (10, '{"ok": false, "error": "failed", "step": "pci", "reboot_required": true}', "failed", True),
    (10, "", "failed", True),                                   # no JSON: code alone decides
    (11, '{"ok": false, "error": "precondition", "missing": ["rule61"]}', "precondition", False),
    (12, '{"ok": false, "error": "aborted", "step": "modprobe"}', "aborted", False),
    (126, "", "cancelled", False),
    (127, "", "unavailable", False),
    (3, "garbage", "failed", False),
])
def test_parse_live_result_codes(code, out, error, reboot):
    r = parse_live_result(code, out, "err text\n")
    assert r.ok is False and r.code == code and r.error == error and r.reboot_required is reboot
    assert r.message


def test_parse_live_result_message_details():
    r = parse_live_result(11, '{"ok": false, "error": "precondition", "missing": ["rule61"]}', "")
    assert "rule61" in r.message
    r = parse_live_result(12, '{"ok": false, "error": "aborted", "step": "modprobe"}', "stderr\n")
    assert "modprobe" in r.message and "stderr" in r.message


def test_parse_live_result_ok_unchanged_and_garbage_holders():
    assert parse_live_result(0, '{"ok": true, "mode": "Hybrid", "changed": false}', "").ok
    assert parse_live_result(0, "", "").ok                       # exit 0 without JSON still counts
    r = parse_live_result(9, '{"error": "busy", "holders": [1, {"pid": "x"}, {"pid": 3, "comm": "a"}]}', "")
    assert r.holders == [Holder(3, "a", "", None, [])]


def test_request_live_is_one_at_a_time_and_blocks_boot_request():
    c = _live_client()
    results = []
    c.request_live(GfxMode.INTEGRATED, results.append)
    c.request_live(GfxMode.HYBRID, results.append)
    assert len(FakeProcess.instances) == 1 and results[0].ok is False and results[0].error == "running"
    done = []
    c.request_boot_mode(GfxMode.HYBRID, lambda ok, m: done.append(ok))
    assert len(FakeProcess.instances) == 1 and done == [False]


@pytest.mark.parametrize("mode", [GfxMode.VFIO, GfxMode.ASUS_MUX_DGPU, 42])
def test_request_live_rejects_unsupported(mode):
    c = _live_client()
    results = []
    c.request_live(mode, results.append)
    assert FakeProcess.instances == [] and results[0].ok is False


def test_request_live_failed_to_start():
    from PyQt6.QtCore import QProcess

    c = _live_client()
    results = []
    c.request_live(GfxMode.HYBRID, results.append)
    FakeProcess.instances[0].errorOccurred.slots[0](QProcess.ProcessError.FailedToStart)
    assert results[0].error == "start" and results[0].code is None and c._live_process is None


def test_request_live_callback_exception_is_contained():
    c = _live_client()

    def boom(_r):
        raise RuntimeError("x")

    c.request_live(GfxMode.HYBRID, boom)
    FakeProcess.instances[0].finished.slots[0](0, None)
    assert c._live_process is None


def test_request_live_real_qprocess_with_stub_helper(tmp_path):
    stub = tmp_path / "helper"
    stub.write_text('#!/bin/sh\necho progress >&2\necho \'{"ok": false, "error": "busy", "holders": '
                    '[{"pid": 1, "comm": "x", "user": "u", "exe": null, "nodes": []}]}\'\nexit 9\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    c = GfxClient(helper_path=str(stub))
    c.launcher = []
    results = []
    c.request_live(GfxMode.INTEGRATED, results.append)
    assert spin_until(lambda: bool(results))
    assert results[0].error == "busy" and results[0].holders[0].comm == "x" and results[0].holders[0].exe is None


# --------------------------------------------------------------------- holders
def test_query_holders_runs_without_pkexec():
    c = _live_client()
    got = []
    c.query_holders(got.append)
    proc = FakeProcess.instances[0]
    assert proc.started == ("/usr/local/libexec/alaz-gfx-helper", ["holders"])
    proc.out = b'{"ok": true, "dgpu_present": true, "holders": [{"pid": 5, "comm": "blender", "user": "u", "exe": null, "nodes": ["/dev/nvidia0"]}]}\n'
    proc.finished.slots[0](0, None)
    assert got == [[Holder(5, "blender", "u", None, ["/dev/nvidia0"])]] and c._holders_process is None


def test_query_holders_shares_one_inflight_query():
    c = _live_client()
    a, b = [], []
    c.query_holders(a.append)
    c.query_holders(b.append)
    assert len(FakeProcess.instances) == 1
    FakeProcess.instances[0].out = b'{"ok": true, "dgpu_present": false, "holders": []}'
    FakeProcess.instances[0].finished.slots[0](0, None)
    assert a == [[]] and b == [[]]


@pytest.mark.parametrize("code,out", [(5, ""), (0, "not json"), (0, '{"ok": false}')])
def test_query_holders_failure_gives_empty_list(code, out):
    c = _live_client()
    got = []
    c.query_holders(got.append)
    FakeProcess.instances[0].out = out.encode()
    FakeProcess.instances[0].finished.slots[0](code, None)
    assert got == [[]]
    c.query_holders(got.append)                   # a new query can start afterwards
    assert len(FakeProcess.instances) == 2


def test_query_holders_failed_to_start():
    from PyQt6.QtCore import QProcess

    c = _live_client()
    got = []
    c.query_holders(got.append)
    FakeProcess.instances[0].errorOccurred.slots[0](QProcess.ProcessError.FailedToStart)
    assert got == [[]]


# ------------------------------------------------------------------ live_ready
def test_live_ready_needs_mux1_and_rule(tmp_path):
    mux, rule = tmp_path / "mux", tmp_path / "61.rules"
    c = GfxClient(mux_path=str(mux), mutter_rule_path=str(rule))
    assert c.live_ready() is False                      # nothing exists
    mux.write_text("1\n")
    assert c.live_ready() is False                      # rule missing
    rule.write_text("x")
    assert c.live_ready() is True
    mux.write_text("0\n")
    assert c.live_ready() is False                      # Ultimate
    mux.write_text("garbage")
    assert c.live_ready() is False
