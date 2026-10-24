"""supergfxd client: read-only D-Bus access plus async pkexec helper calls.

supergfxd's own mode-changing D-Bus methods are deliberately not used anywhere.  A boot-time mode change goes through the root helper
(``request_boot_mode``, effective after a reboot); a LIVE Eco<->Hybrid switch goes
through the helper's ``live-eco`` / ``live-hybrid`` commands (``request_live``),
which are only offered when ``live_ready()`` (see docs/LIVE_GPU_CONTRACT.md).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

from PyQt6.QtCore import QObject, QProcess, pyqtSignal
from PyQt6.QtDBus import QDBusConnection

from . import dbus_util
from .types import GfxMode, GfxPower

log = logging.getLogger(__name__)

SERVICE = "org.supergfxctl.Daemon"
PATH = "/org/supergfxctl/Gfx"
IFACE = "org.supergfxctl.Daemon"

HELPER_PATH = "/usr/local/libexec/alaz-gfx-helper"
SUPERGFXD_CONF = "/etc/supergfxd.conf"
SYSFS_DGPU_DISABLE = "/sys/devices/platform/asus-nb-wmi/dgpu_disable"
PCI_DEVICES = "/sys/bus/pci/devices"
SYSFS_MUX = "/sys/devices/platform/asus-nb-wmi/gpu_mux_mode"
MUTTER_RULE = "/etc/udev/rules.d/61-alaz-mutter-ignore-nvidia.rules"

NVIDIA_VENDOR = 0x10DE
PCI_CLASS_DISPLAY = 0x03

# Names used in /etc/supergfxd.conf ("mode") -> enum.
_CONF_MODE_NAMES = {
    "Hybrid": GfxMode.HYBRID,
    "Integrated": GfxMode.INTEGRATED,
    "NvidiaNoModeset": GfxMode.NVIDIA_NO_MODESET,
    "Vfio": GfxMode.VFIO,
    "AsusEgpu": GfxMode.ASUS_EGPU,
    "AsusMuxDgpu": GfxMode.ASUS_MUX_DGPU,
    "None": GfxMode.NONE,
}
_HELPER_ARGS = {GfxMode.INTEGRATED: "integrated", GfxMode.HYBRID: "hybrid"}


@dataclass
class Holder:
    """A process that holds the dGPU open (helper ``holders`` / busy answer)."""
    pid: int
    comm: str
    user: str = ""
    exe: str | None = None
    nodes: list = field(default_factory=list)


@dataclass
class LiveResult:
    ok: bool
    code: int | None = None          # process exit code (None: never ran)
    error: str | None = None         # helper "error" key, or "cancelled" (126) / "unavailable" (127) / "start"
    holders: list = field(default_factory=list)
    reboot_required: bool = False
    message: str = ""


_LIVE_ARGS = {GfxMode.INTEGRATED: "live-eco", GfxMode.HYBRID: "live-hybrid"}
_CODE_ERRORS = {
    4: "mux", 7: "supergfxd", 9: "busy", 10: "failed", 11: "precondition", 12: "aborted",
    126: "cancelled", 127: "unavailable",
}


def _parse_holders(raw) -> list[Holder]:
    out: list[Holder] = []
    for h in raw if isinstance(raw, list) else []:
        if not isinstance(h, dict):
            continue
        try:
            out.append(Holder(
                pid=int(h.get("pid", 0)), comm=str(h.get("comm", "")), user=str(h.get("user", "")),
                exe=(str(h["exe"]) if h.get("exe") else None),
                nodes=[str(n) for n in (h.get("nodes") or [])],
            ))
        except (TypeError, ValueError):
            continue
    return out


def _last_json(text: str) -> dict | None:
    """The helper prints one JSON object as the LAST stdout line."""
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None
    return None


def parse_live_result(code: int | None, out: str, err: str) -> LiveResult:
    """Map helper exit code + output to a LiveResult (contract table, P1)."""
    data = _last_json(out) or {}
    holders = _parse_holders(data.get("holders"))
    error = data.get("error") if isinstance(data.get("error"), str) else None
    if code == 0:
        return LiveResult(ok=bool(data.get("ok", True)), code=0, holders=holders,
                          message=str(data.get("mode") or "ok"))
    if error is None:
        error = _CODE_ERRORS.get(code, "failed") if code is not None else "start"
    reboot = bool(data.get("reboot_required")) or code == 10
    message = (err.strip().splitlines()[-1] if err.strip() else "") or out.strip() or f"helper exited with code {code}"
    if data.get("missing"):
        message = f"{message} ({', '.join(str(m) for m in data['missing'])})"
    if data.get("step"):
        message = f"{message} [{data['step']}]"
    return LiveResult(ok=False, code=code, error=error, holders=holders, reboot_required=reboot, message=message)


def _enum_or_none(enum_cls, value):
    try:
        return enum_cls(int(value))
    except (TypeError, ValueError):
        return None


def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


class GfxClient(QObject):
    modeChanged = pyqtSignal(int)    # GfxMode
    powerChanged = pyqtSignal(int)   # GfxPower
    pendingChanged = pyqtSignal(object, object)  # (pending GfxMode | None, pending user action | None)
    availableChanged = pyqtSignal(bool)

    def __init__(
        self,
        bus: QDBusConnection | None = None,
        parent: QObject | None = None,
        *,
        conf_path: str = SUPERGFXD_CONF,
        dgpu_disable_path: str = SYSFS_DGPU_DISABLE,
        pci_root: str = PCI_DEVICES,
        helper_path: str = HELPER_PATH,
        mux_path: str = SYSFS_MUX,
        mutter_rule_path: str = MUTTER_RULE,
    ):
        super().__init__(parent)
        self._bus = bus if bus is not None else QDBusConnection.systemBus()
        self.conf_path = conf_path
        self.dgpu_disable_path = dgpu_disable_path
        self.pci_root = pci_root
        self.helper_path = helper_path
        self.mux_path = mux_path
        self.mutter_rule_path = mutter_rule_path
        # Command prefix and process class are attributes so tests can substitute them.
        self.launcher: list[str] = ["pkexec"]
        self.process_factory: Callable[..., QProcess] = QProcess

        self.available = False
        self.mode: GfxMode | None = None
        self.power: GfxPower | None = None
        self.supported: list[GfxMode] = []
        self.pending_mode: GfxMode | None = None
        self.pending_action: int | None = None
        self.vendor: str | None = None
        self.version: str | None = None
        self._process: QProcess | None = None
        self._live_process: QProcess | None = None
        self._holders_process: QProcess | None = None
        self._holders_waiters: list[Callable[[list], None]] = []

        # Any notification just triggers a cheap re-read; Mode()/Power() stay authoritative.
        self._subs = [
            dbus_util.subscribe_signal(
                self._bus, SERVICE, PATH, IFACE, "NotifyGfxStatus", self._on_status_signal, self
            ),
            dbus_util.subscribe_signal(
                self._bus, SERVICE, PATH, IFACE, "NotifyGfx", lambda _a: self.refresh(), self
            ),
            dbus_util.subscribe_signal(
                self._bus, SERVICE, PATH, IFACE, "NotifyAction", lambda _a: self.refresh(), self
            ),
        ]
        self._watcher = dbus_util.watch_service(self._bus, SERVICE, self._on_owner, self)

    # ------------------------------------------------------------------ D-Bus
    def _on_owner(self, present: bool) -> None:
        if present:
            self.refresh()
        else:
            self._set_available(False)

    def _set_available(self, value: bool) -> None:
        if value != self.available:
            self.available = value
            self.availableChanged.emit(value)

    def _on_status_signal(self, args: list[Any]) -> None:
        if args:
            self._update_power(args[0])

    def _update_power(self, raw) -> None:
        power = _enum_or_none(GfxPower, raw)
        if power != self.power:
            self.power = power
            if power is not None:
                self.powerChanged.emit(int(power))

    def _update_mode(self, raw) -> None:
        mode = _enum_or_none(GfxMode, raw)
        if mode != self.mode:
            self.mode = mode
            if mode is not None:
                self.modeChanged.emit(int(mode))

    def _read(self, method: str, apply: Callable[[Any], None]) -> None:
        def done(result, err):
            if err is not None or not result:
                if method == "Mode":
                    self._set_available(False)
                log.warning("supergfxd %s failed: %s", method, err or "no reply")
                return
            if method == "Mode":
                self._set_available(True)
            apply(result[0])

        dbus_util.async_call(self._bus, SERVICE, PATH, IFACE, method, [], done)

    def refresh(self) -> None:
        """Async Mode/Power/Supported/PendingMode/PendingUserAction/Vendor/Version."""
        self._read("Mode", self._update_mode)
        self._read("Power", self._update_power)
        self._read("Supported", self._set_supported)
        self._read("PendingMode", self._set_pending_mode)
        self._read("PendingUserAction", self._set_pending_action)
        self._read("Vendor", lambda v: setattr(self, "vendor", str(v)))
        self._read("Version", lambda v: setattr(self, "version", str(v)))

    def _set_supported(self, raw) -> None:
        modes = [_enum_or_none(GfxMode, v) for v in (raw or [])]
        self.supported = [m for m in modes if m is not None]

    def _set_pending_mode(self, raw) -> None:
        mode = _enum_or_none(GfxMode, raw)
        self.pending_mode = None if mode in (None, GfxMode.NONE) else mode
        self.pendingChanged.emit(self.pending_mode, self.pending_action)

    def _set_pending_action(self, raw) -> None:
        try:
            self.pending_action = int(raw)
        except (TypeError, ValueError):
            self.pending_action = None
        self.pendingChanged.emit(self.pending_mode, self.pending_action)

    # ------------------------------------------------------------ file system
    def configured_boot_mode(self) -> GfxMode | None:
        """"mode" from /etc/supergfxd.conf (world-readable)."""
        text = _read_text(self.conf_path)
        if text is None:
            return None
        try:
            name = json.loads(text).get("mode")
        except (ValueError, AttributeError):
            log.warning("cannot parse %s", self.conf_path)
            return None
        return _CONF_MODE_NAMES.get(name) if isinstance(name, str) else None

    def dgpu_disabled(self) -> bool | None:
        """Firmware dgpu_disable flag (None when unavailable)."""
        text = _read_text(self.dgpu_disable_path)
        if text in ("0", "1"):
            return text == "1"
        return None

    def live_ready(self) -> bool:
        """Live Eco<->Hybrid switching is safe: MUX=1 and the mutter-ignore rule (61) is installed."""
        return _read_text(self.mux_path) == "1" and os.path.exists(self.mutter_rule_path)

    def nvidia_pci_path(self) -> str | None:
        """Sysfs path of the NVIDIA display device (vendor 0x10de, class 0x03xxxx), if present."""
        try:
            names = sorted(os.listdir(self.pci_root))
        except OSError:
            return None
        for name in names:
            base = os.path.join(self.pci_root, name)
            vendor = _read_text(os.path.join(base, "vendor"))
            klass = _read_text(os.path.join(base, "class"))
            if vendor is None or klass is None:
                continue
            try:
                if int(vendor, 16) == NVIDIA_VENDOR and (int(klass, 16) >> 16) == PCI_CLASS_DISPLAY:
                    return base
            except ValueError:
                continue
        return None

    # ----------------------------------------------------------- helper (root)
    def request_boot_mode(self, mode: GfxMode, callback: Callable[[bool, str], None]) -> None:
        """Ask the root helper to set the *boot-time* mode (applies after reboot).

        Runs ``pkexec <helper> set-boot-mode <integrated|hybrid>`` asynchronously;
        ``callback(ok, message)`` is invoked once.  Nothing changes live.
        The process exit code (or ``None`` if it never ran) is stored in
        ``self.last_exit_code`` before the callback fires.
        """
        self.last_exit_code = None
        try:
            arg = _HELPER_ARGS[GfxMode(mode)]
        except (KeyError, ValueError):
            callback(False, f"unsupported boot mode: {mode!r}")
            return
        if self._process is not None or self._live_process is not None:
            callback(False, "another mode request is already running")
            return

        cmd = [*self.launcher, self.helper_path, "set-boot-mode", arg]
        proc = self.process_factory(self)
        self._process = proc
        state = {"done": False}

        def finish(ok: bool, message: str) -> None:
            if state["done"]:
                return
            state["done"] = True
            self._process = None
            proc.deleteLater()
            try:
                callback(ok, message)
            except Exception:
                log.exception("request_boot_mode callback raised")

        def on_finished(code, _status) -> None:
            self.last_exit_code = int(code)
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace").strip()
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            if code == 0:
                finish(True, out or "ok")
            else:
                finish(False, err or out or f"helper exited with code {code}")

        def on_error(error) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                finish(False, f"could not start {cmd[0]}")

        proc.finished.connect(on_finished)
        proc.errorOccurred.connect(on_error)
        log.info("requesting boot mode %s via %s", arg, cmd[0])
        proc.start(cmd[0], cmd[1:])


    # ------------------------------------------------------------ live switch
    def request_live(self, target: GfxMode, callback: Callable[[LiveResult], None]) -> None:
        """Run ``pkexec <helper> live-eco|live-hybrid`` (10-15 s) asynchronously.

        ``callback(LiveResult)`` is invoked exactly once.  One request at a time.  The last stdout line
        is parsed as JSON; exit codes are mapped per the contract (docs/LIVE_GPU_CONTRACT.md, P1).
        """
        self.last_exit_code = None
        try:
            arg = _LIVE_ARGS[GfxMode(target)]
        except (KeyError, ValueError):
            callback(LiveResult(False, error="unsupported", message=f"unsupported live target: {target!r}"))
            return
        if self._live_process is not None or self._process is not None:
            callback(LiveResult(False, error="running", message="another mode request is already running"))
            return

        cmd = [*self.launcher, self.helper_path, arg]
        proc = self.process_factory(self)
        self._live_process = proc
        state = {"done": False}

        def finish(result: LiveResult) -> None:
            if state["done"]:
                return
            state["done"] = True
            self._live_process = None
            proc.deleteLater()
            try:
                callback(result)
            except Exception:
                log.exception("request_live callback raised")

        def on_finished(code, _status) -> None:
            self.last_exit_code = int(code)
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
            finish(parse_live_result(int(code), out, err))

        def on_error(error) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                finish(LiveResult(False, error="start", message=f"could not start {cmd[0]}"))

        proc.finished.connect(on_finished)
        proc.errorOccurred.connect(on_error)
        log.info("requesting live switch %s via %s", arg, cmd[0])
        proc.start(cmd[0], cmd[1:])

    def query_holders(self, callback: Callable[[list], None]) -> None:
        """Run ``<helper> holders`` (no pkexec, read-only) asynchronously; callback gets [Holder] ([] on failure)."""
        self._holders_waiters.append(callback)
        if self._holders_process is not None:
            return                      # a query is in flight: share its answer
        cmd = [self.helper_path, "holders"]
        proc = self.process_factory(self)
        self._holders_process = proc
        state = {"done": False}

        def finish(holders: list[Holder]) -> None:
            if state["done"]:
                return
            state["done"] = True
            self._holders_process = None
            proc.deleteLater()
            waiters, self._holders_waiters = self._holders_waiters, []
            for cb in waiters:
                try:
                    cb(list(holders))
                except Exception:
                    log.exception("query_holders callback raised")

        def on_finished(code, _status) -> None:
            out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            data = _last_json(out) if code == 0 else None
            if data is None or not data.get("ok", False):
                log.warning("helper holders failed (code %s)", code)
                finish([])
            else:
                finish(_parse_holders(data.get("holders")))

        def on_error(error) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                log.warning("could not start %s", cmd[0])
                finish([])

        proc.finished.connect(on_finished)
        proc.errorOccurred.connect(on_error)
        proc.start(cmd[0], cmd[1:])
