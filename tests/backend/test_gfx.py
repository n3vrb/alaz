"""GfxClient tests.  Nothing here changes the system: no pkexec, no GPU mode calls."""
import os
import re
import stat
import time

import pytest
from PyQt6.QtCore import QCoreApplication, QElapsedTimer
from PyQt6.QtDBus import QDBusConnection

from rog_control.backend import dbus_util, gfx
from rog_control.backend.gfx import GfxClient
from rog_control.backend.types import GfxMode, GfxPower

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
    assert gfx.HELPER_PATH == "/usr/local/libexec/rog-control-gfx-helper"
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
    assert proc.started == ("pkexec", ["/usr/local/libexec/rog-control-gfx-helper", "set-boot-mode", arg])
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
