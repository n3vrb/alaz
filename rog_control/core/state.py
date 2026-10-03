"""Observable application state (data + signals only; imports no backend code)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

PERF_MODES = ("quiet", "balanced", "turbo", "custom")
ACCENTS = {
    "quiet": "#34C08A",
    "balanced": "#4C8DFF",
    "turbo": "#FF5A5F",
    "custom": "#F2A93B",
}


@dataclass
class GfxView:
    active: str | None = None        # "eco" | "standard" | "ultimate"
    boot: str | None = None          # mode in /etc/supergfxd.conf
    pending: str | None = None       # boot if boot != active else None
    power: str = "unknown"           # "sleep" | "active" | "off" | "unknown"
    dgpu_disabled: bool | None = None
    mux_direct: bool | None = None
    can_eco_exit: bool = True


@dataclass
class DisplayView:
    connector: str | None = None
    current_hz: int | None = None
    rates: list[int] = field(default_factory=list)
    auto: bool = False


@dataclass
class AuraView:
    brightness: int | None = None
    color: tuple[int, int, int] | None = None


class AppState(QObject):
    perfModeChanged = pyqtSignal(str)
    accentChanged = pyqtSignal(str)
    sensorsChanged = pyqtSignal(object)
    gfxChanged = pyqtSignal(object)
    displayChanged = pyqtSignal(object)
    batteryLimitChanged = pyqtSignal(int)
    platformChanged = pyqtSignal(str, object)
    fanCurvesChanged = pyqtSignal(str, object)
    auraChanged = pyqtSignal(object)
    busyChanged = pyqtSignal(str, bool)
    message = pyqtSignal(str, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._perf_mode = "balanced"
        self._sensors: Any = None
        self._gfx = GfxView()
        self._display = DisplayView()
        self._battery_limit: int | None = None
        self._platform: dict[str, Any] = {}
        self._aura = AuraView()
        self._fan_curves: dict[str, list] = {}

    # ---------------------------------------------------------- read access
    @property
    def perf_mode(self) -> str:
        return self._perf_mode

    @property
    def accent(self) -> str:
        return ACCENTS[self._perf_mode]

    @property
    def sensors(self) -> Any:
        return self._sensors

    @property
    def gfx(self) -> GfxView:
        return self._gfx

    @property
    def display(self) -> DisplayView:
        return self._display

    @property
    def battery_limit(self) -> int | None:
        return self._battery_limit

    @property
    def platform(self) -> dict[str, Any]:
        return self._platform

    @property
    def aura(self) -> AuraView:
        return self._aura

    @property
    def fan_curves(self) -> dict[str, list]:
        """Last known curves per perf mode (addition to the contract)."""
        return self._fan_curves

    # --------------------------------------------- mutation (controller only)
    def set_perf_mode(self, mode: str) -> None:
        if mode not in PERF_MODES:
            raise ValueError(f"unknown perf mode: {mode!r}")
        if mode == self._perf_mode:
            return
        old_accent = self.accent
        self._perf_mode = mode
        self.perfModeChanged.emit(mode)
        if self.accent != old_accent:
            self.accentChanged.emit(self.accent)

    def set_sensors(self, snapshot: Any) -> None:
        self._sensors = snapshot
        self.sensorsChanged.emit(snapshot)

    def set_gfx(self, view: GfxView) -> None:
        if view == self._gfx:
            return
        self._gfx = view
        self.gfxChanged.emit(view)

    def set_display(self, view: DisplayView) -> None:
        if view == self._display:
            return
        self._display = view
        self.displayChanged.emit(view)

    def set_battery_limit(self, pct: int) -> None:
        if pct == self._battery_limit:
            return
        self._battery_limit = pct
        self.batteryLimitChanged.emit(pct)

    def set_platform_value(self, name: str, value: Any) -> None:
        self._platform[name] = value
        self.platformChanged.emit(name, value)

    def set_aura(self, view: AuraView) -> None:
        if view == self._aura:
            return
        self._aura = view
        self.auraChanged.emit(view)

    def set_fan_curves(self, mode: str, curves: list) -> None:
        self._fan_curves[mode] = list(curves)
        self.fanCurvesChanged.emit(mode, list(curves))

    def emit_busy(self, key: str, busy: bool) -> None:
        self.busyChanged.emit(key, busy)

    def emit_message(self, level: str, text: str) -> None:
        self.message.emit(level, text)
