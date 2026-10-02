"""Async client for asusd (org.asuslinux.Daemon on the system bus)."""
from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtDBus import QDBusConnection

from . import dbus_util
from .dbus_util import Typed
from .types import FanCurve, Profile

log = logging.getLogger(__name__)

SERVICE = "org.asuslinux.Daemon"
ROOT_PATH = "/org/asuslinux"
IFACE_PLATFORM = "org.asuslinux.Platform"
IFACE_FAN = "org.asuslinux.FanCurves"
IFACE_AURA = "org.asuslinux.Aura"

FAN_CURVE_SIG = "(s(yyyyyyyy)(yyyyyyyy)b)"  # fan, pwm, temps, enabled
# Real signature of Aura.LedModeData (introspection claims "ss" for the last two
# members but the daemon serialises those enums as u).
LED_MODE_DATA_SIG = "(uu(yyy)(yyy)uu)"
DEFAULT_LED_SPEED = 235  # 0xEB, "medium"

# Platform property -> D-Bus type (verified against asusd 6.0.12 introspection).
PLATFORM_TYPES: dict[str, str] = {
    "ThrottleThermalPolicy": "u",
    "ChargeControlEndThreshold": "y",
    "PanelOd": "b",
    "MiniLedMode": "b",
    "PptPl1Spl": "y",
    "PptPl2Sppt": "y",
    "PptFppt": "y",
    "PptApuSppt": "y",
    "PptPlatformSppt": "y",
    "NvDynamicBoost": "y",
    "NvTempTarget": "y",
    "ThrottleQuietEpp": "u",
    "ThrottleBalancedEpp": "u",
    "ThrottlePerformanceEpp": "u",
    "ThrottlePolicyLinkedEpp": "b",
    "ThrottlePolicyOnAc": "u",
    "ThrottlePolicyOnBattery": "u",
    "ChangeThrottlePolicyOnAc": "b",
    "ChangeThrottlePolicyOnBattery": "b",
    "BootSound": "b",
}
# Read-only (or must-not-be-written-by-the-app) properties.
PLATFORM_READONLY = {"GpuMuxMode", "DgpuDisable", "EgpuEnable", "Version"}

_INT_RANGES = {"y": (0, 255), "u": (0, 2**32 - 1)}


class AsusdClient(QObject):
    platformChanged = pyqtSignal(str, object)   # (property name, new value)
    auraChanged = pyqtSignal(str, object)
    error = pyqtSignal(str, str)                # (operation, message)
    availableChanged = pyqtSignal(bool)

    def __init__(self, bus: QDBusConnection | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._bus = bus if bus is not None else QDBusConnection.systemBus()
        self.available = False
        self._platform: dict[str, Any] = {}
        self._aura: dict[str, Any] = {}
        self.aura_path: str | None = None
        self._aura_sub = None
        self._aura_discovering = False
        self._aura_waiters: list[Callable[[str | None], None]] = []
        self._platform_sub = dbus_util.subscribe_properties_changed(
            self._bus, SERVICE, ROOT_PATH, self._on_platform_signal, self
        )
        self._watcher = dbus_util.watch_service(self._bus, SERVICE, self._on_service_owner, self)

    # ------------------------------------------------------------------ state
    def _set_available(self, value: bool) -> None:
        if value != self.available:
            self.available = value
            self.availableChanged.emit(value)

    def _on_service_owner(self, present: bool) -> None:
        if present:
            self.refresh()
        else:
            self.aura_path = None
            self._aura_sub = None
            self._set_available(False)

    def get_cached(self, name: str) -> object | None:
        return self._platform.get(name)

    def get_aura_cached(self, name: str) -> object | None:
        return self._aura.get(name)

    def _fail(self, op: str, message: str) -> None:
        log.warning("%s failed: %s", op, message)
        self.error.emit(op, message)

    # ---------------------------------------------------------------- signals
    def _on_platform_signal(self, iface: str, changed: dict, invalidated: list[str]) -> None:
        if iface != IFACE_PLATFORM:
            return
        self._apply_platform(changed)
        for name in invalidated:
            dbus_util.get_property(
                self._bus, SERVICE, ROOT_PATH, IFACE_PLATFORM, name,
                lambda v, e, n=name: self._apply_platform({n: v}) if e is None else None,
            )

    def _on_aura_signal(self, iface: str, changed: dict, invalidated: list[str]) -> None:
        if iface != IFACE_AURA:
            return
        self._apply_aura(changed)

    def _apply_platform(self, props: dict[str, Any]) -> None:
        for name, value in props.items():
            self._platform[name] = value
            self.platformChanged.emit(name, value)

    def _apply_aura(self, props: dict[str, Any]) -> None:
        for name, value in props.items():
            self._aura[name] = value
            self.auraChanged.emit(name, value)

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Async GetAll of the Platform (and Aura) interface; emits per-property signals."""

        def done(props, err):
            if err is not None or props is None:
                self._set_available(False)
                self._fail("refresh", err or "no reply")
                return
            self._set_available(True)
            self._apply_platform(props)

        dbus_util.get_all(self._bus, SERVICE, ROOT_PATH, IFACE_PLATFORM, done)
        self._discover_aura(self._refresh_aura, force=True)

    def _refresh_aura(self, path: str | None) -> None:
        if path is None:
            return

        def done(props, err):
            if err is None and props is not None:
                self._apply_aura(props)
            else:
                self._fail("refresh_aura", err or "no reply")

        dbus_util.get_all(self._bus, SERVICE, path, IFACE_AURA, done)

    # ------------------------------------------------------------------- aura
    def _discover_aura(self, callback: Callable[[str | None], None], force: bool = False) -> None:
        """Find the child of /org/asuslinux that implements org.asuslinux.Aura."""
        if self.aura_path is not None and not force:
            callback(self.aura_path)
            return
        self._aura_waiters.append(callback)
        if self._aura_discovering:
            return
        self._aura_discovering = True

        def finish(path: str | None) -> None:
            self._aura_discovering = False
            if path != self.aura_path:
                self.aura_path = path
                self._aura_sub = None
                if path is not None:
                    self._aura_sub = dbus_util.subscribe_properties_changed(
                        self._bus, SERVICE, path, self._on_aura_signal, self
                    )
            waiters, self._aura_waiters = self._aura_waiters, []
            for w in waiters:
                w(path)

        def root_done(xml, err):
            if err is not None or xml is None:
                self._fail("discover_aura", err or "no reply")
                finish(None)
                return
            try:
                children, _ = dbus_util.parse_introspection(xml)
            except Exception as exc:
                self._fail("discover_aura", f"bad introspection XML: {exc}")
                finish(None)
                return
            self._probe_children([f"{ROOT_PATH}/{c}" for c in children], finish)

        dbus_util.introspect(self._bus, SERVICE, ROOT_PATH, root_done)

    def _probe_children(self, paths: list[str], finish: Callable[[str | None], None]) -> None:
        if not paths:
            finish(None)
            return
        head, rest = paths[0], paths[1:]

        def done(xml, err):
            if err is None and xml is not None:
                try:
                    _, ifaces = dbus_util.parse_introspection(xml)
                except Exception:
                    ifaces = []
                if IFACE_AURA in ifaces:
                    finish(head)
                    return
            self._probe_children(rest, finish)

        dbus_util.introspect(self._bus, SERVICE, head, done)

    def _set_aura_property(self, op: str, name: str, sig: str, value: Any) -> None:
        def with_path(path: str | None) -> None:
            if path is None:
                self._fail(op, "no Aura device found")
                return
            dbus_util.set_property(
                self._bus, SERVICE, path, IFACE_AURA, name, sig, value,
                lambda _r, e: self._fail(op, e) if e else None,
            )

        self._discover_aura(with_path)

    def set_kbd_brightness(self, level: int) -> None:
        """Keyboard backlight, 0 (off) .. 3 (high)."""
        level = int(level)
        if not 0 <= level <= 3:
            self._fail("set_kbd_brightness", f"level out of range: {level}")
            return
        self._set_aura_property("set_kbd_brightness", "Brightness", "u", level)

    def set_aura_static(self, rgb: tuple[int, int, int]) -> None:
        """Static single-colour mode (mode 0, no zone)."""
        try:
            r, g, b = (int(c) for c in rgb)
        except (TypeError, ValueError):
            self._fail("set_aura_static", f"bad colour: {rgb!r}")
            return
        if not all(0 <= c <= 255 for c in (r, g, b)):
            self._fail("set_aura_static", f"colour out of range: {rgb!r}")
            return
        cached = self._aura.get("LedModeData")
        speed, direction = DEFAULT_LED_SPEED, 0
        if isinstance(cached, tuple) and len(cached) == 6:
            speed, direction = int(cached[4]), int(cached[5])
        data = (0, 0, (r, g, b), (0, 0, 0), speed, direction)
        self._set_aura_property("set_aura_static", "LedModeData", LED_MODE_DATA_SIG, data)

    # --------------------------------------------------------------- platform
    def set_platform(self, name: str, value) -> None:
        """Async Properties.Set on org.asuslinux.Platform with the right type."""
        sig = PLATFORM_TYPES.get(name)
        if sig is None:
            reason = "read-only property" if name in PLATFORM_READONLY else "unknown property"
            self._fail(f"set_platform:{name}", reason)
            return
        if sig == "b":
            value = bool(value)
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                self._fail(f"set_platform:{name}", f"not an integer: {value!r}")
                return
            lo, hi = _INT_RANGES[sig]
            if not lo <= value <= hi:
                self._fail(f"set_platform:{name}", f"value out of range for {sig}: {value}")
                return
        dbus_util.set_property(
            self._bus, SERVICE, ROOT_PATH, IFACE_PLATFORM, name, sig, value,
            lambda _r, e: self._fail(f"set_platform:{name}", e) if e else None,
        )

    # -------------------------------------------------------------- fan curves
    def _fan_call(self, op: str, method: str, args: list[Any]) -> None:
        dbus_util.async_call(
            self._bus, SERVICE, ROOT_PATH, IFACE_FAN, method, args,
            lambda _r, e: self._fail(op, e) if e else None,
        )

    def fetch_fan_curves(self, profile: Profile, callback: Callable[[list[FanCurve]], None]) -> None:
        """Async FanCurveData(profile); ``callback`` gets [] on failure (error is emitted)."""

        def done(result, err):
            if err is not None or not result:
                self._fail("fetch_fan_curves", err or "no reply")
                callback([])
                return
            curves: list[FanCurve] = []
            for item in result[0]:
                try:
                    fan, pwm, temps, enabled = item
                    curves.append(
                        FanCurve(str(fan), tuple(int(t) for t in temps),
                                 tuple(int(p) for p in pwm), bool(enabled))
                    )
                except (TypeError, ValueError):
                    log.warning("unparsable fan curve entry: %r", item)
            callback(curves)

        dbus_util.async_call(
            self._bus, SERVICE, ROOT_PATH, IFACE_FAN, "FanCurveData",
            [Typed("u", int(profile))], done,
        )

    def set_fan_curve(self, profile: Profile, curve: FanCurve) -> None:
        if len(curve.temps) != 8 or len(curve.pwm) != 8:
            self._fail("set_fan_curve", "a curve needs exactly 8 points")
            return
        if not all(0 <= v <= 255 for v in (*curve.temps, *curve.pwm)):
            self._fail("set_fan_curve", "curve values must be within 0-255")
            return
        value = (curve.fan, tuple(curve.pwm), tuple(curve.temps), bool(curve.enabled))
        self._fan_call(
            "set_fan_curve", "SetFanCurve", [Typed("u", int(profile)), Typed(FAN_CURVE_SIG, value)]
        )

    def set_fan_curve_enabled(self, profile: Profile, fan: str, enabled: bool) -> None:
        self._fan_call(
            "set_fan_curve_enabled", "SetProfileFanCurveEnabled",
            [Typed("u", int(profile)), Typed("s", fan), Typed("b", bool(enabled))],
        )

    def reset_fan_curves(self, profile: Profile) -> None:
        self._fan_call("reset_fan_curves", "ResetProfileCurves", [Typed("u", int(profile))])
