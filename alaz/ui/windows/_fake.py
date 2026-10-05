"""FakeState / FakeController: the Wave-2 contract surface without hardware (demos, screenshots, tests).

Setters update the fake state and log; `calls` records every controller call as (name, args).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal

from alaz.backend.sensors import SensorSnapshot
from alaz.backend.types import FanCurve

log = logging.getLogger(__name__)

PERF_MODES = ("quiet", "balanced", "turbo", "custom")
ACCENTS = {"quiet": "#34C08A", "balanced": "#4C8DFF", "turbo": "#FF5A5F", "custom": "#F2A93B"}
POLICY = {"quiet": 2, "balanced": 0, "turbo": 1}

RAW = {
    "quiet": {"CPU": ((55, 58, 61, 64, 67, 70, 73, 255), (2, 25, 38, 51, 63, 81, 99, 99)),
              "GPU": ((47, 49, 53, 56, 59, 62, 65, 255), (2, 20, 33, 43, 61, 79, 96, 96)),
              "MID": ((55, 58, 61, 64, 67, 70, 73, 255), (2, 2, 20, 40, 86, 86, 142, 142))},
    "balanced": {"CPU": ((0, 59, 62, 65, 68, 71, 74, 76), (2, 25, 38, 51, 63, 81, 99, 117)),
                 "GPU": ((0, 60, 63, 66, 69, 71, 72, 74), (2, 20, 33, 43, 61, 79, 96, 114)),
                 "MID": ((0, 59, 62, 65, 68, 71, 74, 76), (2, 2, 20, 40, 86, 86, 142, 142))},
    "turbo": {"CPU": ((0, 55, 59, 64, 69, 74, 79, 81), (25, 51, 63, 91, 117, 147, 183, 219)),
              "GPU": ((0, 50, 55, 60, 65, 70, 75, 80), (20, 43, 61, 91, 114, 142, 165, 209)),
              "MID": ((0, 55, 59, 64, 69, 74, 79, 81), (2, 40, 86, 104, 142, 198, 214, 249))},
}
RAW["custom"] = RAW["turbo"]


@dataclass
class GfxView:
    active: str | None = "standard"
    boot: str | None = "standard"
    pending: str | None = None
    power: str = "sleep"
    dgpu_disabled: bool | None = False
    mux_direct: bool | None = False
    can_eco_exit: bool = True


@dataclass
class DisplayView:
    connector: str | None = "eDP-1"
    current_hz: int | None = 240
    rates: list[int] = field(default_factory=lambda: [60, 90, 120, 144, 165, 240])
    auto: bool = True


@dataclass
class AuraView:
    brightness: int | None = 2
    color: tuple[int, int, int] | None = (76, 141, 255)


def fake_curves(mode: str) -> list[FanCurve]:
    return [FanCurve(fan, tuple(t), tuple(p), True) for fan, (t, p) in RAW[mode].items()]


def fake_sensors(**kw) -> SensorSnapshot:
    base = dict(cpu_temp=48.0, cpu_load=12.0, ram_pct=38.0, gpu_state="sleep", gpu_temp=None, gpu_load=None,
                gpu_power_w=0.0, fans_rpm={"cpu": 2300, "gpu": 2100, "mid": 3800}, battery_pct=90.0,
                battery_status="Full", on_ac=True, battery_power_w=None,
                system_power_w=31.0, psys_available=True)  # AC+Full: no charge watts
    # battery case: battery_status="Discharging", on_ac=False, battery_power_w=26.4; AC charging: "Charging", True, 65.2
    base.update(kw)
    return SensorSnapshot(**base)


class FakeState(QObject):
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

    def __init__(self, perf: str = "balanced"):
        super().__init__()
        self._perf = perf
        self._sensors = fake_sensors()
        self._gfx = GfxView()
        self._display = DisplayView()
        self._battery_limit = 80
        self._platform = {"PanelOd": True, "ThrottlePolicyOnAc": 1, "ThrottlePolicyOnBattery": 2, "NvDynamicBoost": 5,
                          "NvTempTarget": 75, "ThrottleQuietEpp": 4, "ThrottleBalancedEpp": 3,
                          "ThrottlePerformanceEpp": 1, "PptPl1Spl": 60, "PptPl2Sppt": 90, "PptFppt": 110}
        self._aura = AuraView()

    perf_mode = property(lambda s: s._perf)
    accent = property(lambda s: ACCENTS[s._perf])
    sensors = property(lambda s: s._sensors)
    gfx = property(lambda s: s._gfx)
    display = property(lambda s: s._display)
    battery_limit = property(lambda s: s._battery_limit)
    platform = property(lambda s: s._platform)
    aura = property(lambda s: s._aura)

    # mutation helpers (what the real controller/core would do)
    def set_perf_mode(self, mode: str) -> None:
        if mode == self._perf:
            return
        old = self.accent
        self._perf = mode
        self.perfModeChanged.emit(mode)
        if self.accent != old:
            self.accentChanged.emit(self.accent)

    def set_sensors(self, snap) -> None:
        self._sensors = snap
        self.sensorsChanged.emit(snap)

    def set_gfx(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self._gfx, k, v)
        self.gfxChanged.emit(self._gfx)

    def set_display(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self._display, k, v)
        self.displayChanged.emit(self._display)

    def set_battery_limit(self, pct: int) -> None:
        self._battery_limit = pct
        self.batteryLimitChanged.emit(pct)

    def set_platform_value(self, name: str, value) -> None:
        self._platform[name] = value
        self.platformChanged.emit(name, value)

    def set_aura(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self._aura, k, v)
        self.auraChanged.emit(self._aura)

    def emit_busy(self, key: str, on: bool) -> None:
        self.busyChanged.emit(key, on)

    def emit_message(self, level: str, text: str) -> None:
        self.message.emit(level, text)


class FakeController(QObject):
    gpuRebootRequired = pyqtSignal()

    def __init__(self, state: FakeState):
        super().__init__()
        self.state = state
        self.calls: list[tuple[str, tuple]] = []
        self.rebooted = False

    def _rec(self, name: str, *args) -> None:
        self.calls.append((name, args))
        log.info("fake controller: %s%r", name, args)

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def start(self) -> None:
        self._rec("start")

    def set_perf_mode(self, mode: str) -> None:
        self._rec("set_perf_mode", mode)
        self.state.set_perf_mode(mode)

    def custom_limits(self) -> tuple[int, int, int]:
        return getattr(self, "_limits", (60, 90, 110))

    def set_custom_limits(self, pl1: int, pl2: int, fppt: int) -> None:
        self._rec("set_custom_limits", pl1, pl2, fppt)
        pl2 = max(pl2, pl1)             # same clamping as the real controller
        fppt = max(fppt, pl2)
        self._limits = (pl1, pl2, fppt)

    def request_gpu_mode(self, mode: str) -> None:
        self._rec("request_gpu_mode", mode)
        leaving_eco = mode == "standard" and self.state.gfx.active == "eco"
        if leaving_eco:
            self.state.set_gfx(boot=mode, pending=mode, dgpu_disabled=False)
            self.gpuRebootRequired.emit()
            return
        self.state.set_gfx(boot=mode, pending=mode if mode != self.state.gfx.active else None)

    def cancel_gpu_pending(self) -> None:
        self._rec("cancel_gpu_pending")
        self.state.set_gfx(boot=self.state.gfx.active, pending=None)

    def reboot_now(self) -> None:
        self._rec("reboot_now")
        self.rebooted = True

    def set_refresh(self, hz) -> None:
        self._rec("set_refresh", hz)
        if hz is None:
            self.state.set_display(auto=True, current_hz=max(self.state.display.rates, default=None))
        else:
            self.state.set_display(auto=False, current_hz=hz)

    def set_panel_od(self, on: bool) -> None:
        self._rec("set_panel_od", on)
        self.state.set_platform_value("PanelOd", on)

    def set_battery_limit(self, pct: int) -> None:
        self._rec("set_battery_limit", pct)
        self.state.set_battery_limit(pct)

    def load_fan_curves(self, mode: str) -> None:
        self._rec("load_fan_curves", mode)
        self.state.fanCurvesChanged.emit(mode, fake_curves(mode))

    def apply_fan_curve(self, mode: str, fan: str, points) -> None:
        self._rec("apply_fan_curve", mode, fan, list(points))

    def reset_fan_curves(self, mode: str) -> None:
        self._rec("reset_fan_curves", mode)
        self.state.fanCurvesChanged.emit(mode, fake_curves(mode))

    def set_epp(self, mode: str, epp: int) -> None:
        self._rec("set_epp", mode, epp)
        name = {"quiet": "ThrottleQuietEpp", "balanced": "ThrottleBalancedEpp"}.get(mode, "ThrottlePerformanceEpp")
        self.state.set_platform_value(name, epp)

    def set_nv_boost(self, w: int) -> None:
        self._rec("set_nv_boost", w)
        self.state.set_platform_value("NvDynamicBoost", w)

    def set_nv_temp_target(self, c: int) -> None:
        self._rec("set_nv_temp_target", c)
        self.state.set_platform_value("NvTempTarget", c)

    def set_auto_profile(self, on_ac: str, on_battery: str) -> None:
        self._rec("set_auto_profile", on_ac, on_battery)
        self.state.set_platform_value("ThrottlePolicyOnAc", POLICY[on_ac])
        self.state.set_platform_value("ThrottlePolicyOnBattery", POLICY[on_battery])

    def set_kbd_brightness(self, level: int) -> None:
        self._rec("set_kbd_brightness", level)
        self.state.set_aura(brightness=level)

    def toggle_kbd_light(self) -> None:
        self._rec("toggle_kbd_light")
        cur = self.state.aura.brightness
        self.state.set_aura(brightness=0 if cur else 2)

    def set_kbd_color(self, rgb) -> None:
        self._rec("set_kbd_color", tuple(rgb))
        self.state.set_aura(color=tuple(rgb))
