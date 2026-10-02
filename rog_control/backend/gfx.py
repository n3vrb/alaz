"""supergfxd client: read-only D-Bus access plus an async pkexec helper call.

This module never changes the GPU mode live.  supergfxd's mode-changing
methods are deliberately not used anywhere; a boot-time mode change goes
through the root helper (``request_boot_mode``) and takes effect only after a
reboot.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from PyQt6.QtCore import QObject, QProcess, pyqtSignal
from PyQt6.QtDBus import QDBusConnection

from . import dbus_util
from .types import GfxMode, GfxPower

log = logging.getLogger(__name__)

SERVICE = "org.supergfxctl.Daemon"
PATH = "/org/supergfxctl/Gfx"
IFACE = "org.supergfxctl.Daemon"

HELPER_PATH = "/usr/local/libexec/rog-control-gfx-helper"
SUPERGFXD_CONF = "/etc/supergfxd.conf"
SYSFS_DGPU_DISABLE = "/sys/devices/platform/asus-nb-wmi/dgpu_disable"
PCI_DEVICES = "/sys/bus/pci/devices"

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
    ):
        super().__init__(parent)
        self._bus = bus if bus is not None else QDBusConnection.systemBus()
        self.conf_path = conf_path
        self.dgpu_disable_path = dgpu_disable_path
        self.pci_root = pci_root
        self.helper_path = helper_path
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
        """
        try:
            arg = _HELPER_ARGS[GfxMode(mode)]
        except (KeyError, ValueError):
            callback(False, f"unsupported boot mode: {mode!r}")
            return
        if self._process is not None:
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
