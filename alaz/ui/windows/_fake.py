"""FakeState / FakeController: the Wave-2 contract surface without hardware (demos, screenshots, tests).

Setters update the fake state and log; `calls` records every controller call as (name, args).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal

from alaz.backend.ddc import MonitorState
from alaz.backend.peripherals.headset import HeadsetState
from alaz.backend.peripherals.mouse import MouseState
from alaz.backend.sensors import SensorSnapshot
from alaz.backend.types import FanCurve
from alaz.core.state import AuraSyncView

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
    # live switching (contract P3)
    selected: str | None = None
    switching: bool = False
    waiting: str | None = None
    holders: list = field(default_factory=list)
    live_ready: bool = False
    optimize: bool = False


@dataclass
class FakeHolder:
    pid: int = 1234
    comm: str = "blender"
    user: str = "enes"
    exe: str = "/usr/bin/blender"
    nodes: list = field(default_factory=lambda: ["/dev/nvidia0"])


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


def fake_mouse(**kw) -> MouseState:
    base = dict(present=True, permission=True, asleep=False, serial="S7MPKR039858", battery_pct=66, charging=False,
                sleep_code=3, low_battery_pct=20, profile=0, dpi_stage=2, dpi_stages=[400, 800, 1600, 3200],
                dpi_colors=[(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)], polling_hz=1000, debounce_ms=12,
                angle_snapping=False, led_mode=2, led_brightness=50, led_rgb=(0, 255, 0))
    base.update(kw)
    return MouseState(**base)


def fake_headset(**kw) -> HeadsetState:
    base = dict(present=True, permission=True, connected=True, firmware="4.0.5.0", battery_pct=87, charging=False,
                light_effect=1, light_brightness=50, light_rgb=(0xEA, 0xB2, 0x15), software_led=False)
    base.update(kw)
    return HeadsetState(**base)


def fake_monitor(**kw) -> MonitorState:
    base = dict(present=True, bus=13, model="XG27UCDMG", serial="T7LMQS012345",
                values={"brightness": 30, "contrast": 80, "color_temp": 0x0B, "gamevisual": 0x02, "shadow_boost": 0,
                        "blue_light": 0, "hdr": 0, "screen_move": 2, "pixel_clean_reminder": 8, "input": 0x1A},
                locked=set(), maxima={"brightness": 100, "contrast": 100})
    base.update(kw)
    return MonitorState(**base)


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
    peripheralsChanged = pyqtSignal(str, object)
    auraSyncChanged = pyqtSignal(object)
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
        self._peripherals = {"mouse": fake_mouse(), "headset": fake_headset(), "monitor": fake_monitor()}
        self._aura_sync = AuraSyncView(enabled=False, effect="static", color=(0xEA, 0xB2, 0x15), brightness=80)

    perf_mode = property(lambda s: s._perf)
    accent = property(lambda s: ACCENTS[s._perf])
    sensors = property(lambda s: s._sensors)
    gfx = property(lambda s: s._gfx)
    display = property(lambda s: s._display)
    battery_limit = property(lambda s: s._battery_limit)
    platform = property(lambda s: s._platform)
    aura = property(lambda s: s._aura)
    aura_sync = property(lambda s: s._aura_sync)

    def peripheral(self, kind: str):
        return self._peripherals.get(kind)

    def set_peripheral(self, kind: str, st) -> None:
        self._peripherals[kind] = st
        self.peripheralsChanged.emit(kind, st)

    def set_aura_sync(self, view: AuraSyncView) -> None:
        self._aura_sync = view
        self.auraSyncChanged.emit(view)

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
    gpuBusy = pyqtSignal(list)
    gpuSwitchFailed = pyqtSignal(str, bool)
    gpuUltimateConfirm = pyqtSignal()

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
        g = self.state.gfx
        if mode == "ultimate":
            self.gpuUltimateConfirm.emit()
            return
        if mode == "optimize":
            self.state.set_gfx(optimize=True, selected="optimize")
            return
        if g.live_ready:                       # live switch: instant in the fake
            self.state.set_gfx(active=mode, boot=mode, selected=mode, optimize=False, pending=None, waiting=None)
            return
        leaving_eco = mode == "standard" and g.active == "eco"
        if leaving_eco:
            self.state.set_gfx(boot=mode, pending=mode, dgpu_disabled=False, optimize=False)
            self.gpuRebootRequired.emit()
            return
        self.state.set_gfx(boot=mode, optimize=False, pending=mode if mode != g.active else None)

    def resolve_busy(self, choice: str) -> None:
        self._rec("resolve_busy", choice)

    def confirm_ultimate(self, ok: bool) -> None:
        self._rec("confirm_ultimate", ok)

    def cancel_gpu_pending(self) -> None:
        self._rec("cancel_gpu_pending")
        self.state.set_gfx(boot=self.state.gfx.active, pending=None, waiting=None)

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

    # ---- peripherals (wave 2): update the fake device states the way the real backends would
    def _mouse_patch(self, **kw) -> None:
        import dataclasses
        self.state.set_peripheral("mouse", dataclasses.replace(self.state.peripheral("mouse"), **kw))

    def mouse_set_dpi(self, i: int, dpi: int) -> None:
        self._rec("mouse_set_dpi", i, dpi)
        stages = list(self.state.peripheral("mouse").dpi_stages or [400, 800, 1600, 3200])
        stages[i] = dpi
        self._mouse_patch(dpi_stages=stages)

    def mouse_set_active_stage(self, stage: int) -> None:
        self._rec("mouse_set_active_stage", stage)
        self._mouse_patch(dpi_stage=stage)

    def mouse_set_polling(self, hz: int) -> None:
        self._rec("mouse_set_polling", hz)
        self._mouse_patch(polling_hz=hz)

    def mouse_set_debounce(self, ms: int) -> None:
        self._rec("mouse_set_debounce", ms)
        self._mouse_patch(debounce_ms=ms)

    def mouse_set_angle_snapping(self, on: bool) -> None:
        self._rec("mouse_set_angle_snapping", on)
        self._mouse_patch(angle_snapping=on)

    def mouse_set_sleep(self, code: int) -> None:
        self._rec("mouse_set_sleep", code)
        self._mouse_patch(sleep_code=code)

    def mouse_set_led(self, mode: int, brightness: int, rgb) -> None:
        self._rec("mouse_set_led", mode, brightness, tuple(rgb))
        self._mouse_patch(led_mode=mode, led_brightness=brightness, led_rgb=tuple(rgb))

    def headset_set_lighting(self, effect: int, brightness: int, rgb) -> None:
        import dataclasses
        self._rec("headset_set_lighting", effect, brightness, tuple(rgb))
        self.state.set_peripheral("headset", dataclasses.replace(
            self.state.peripheral("headset"), light_effect=effect, light_brightness=brightness,
            light_rgb=tuple(rgb)))

    def refresh_monitor(self) -> None:
        self._rec("refresh_monitor")

    def monitor_set(self, key: str, value: int) -> None:
        import dataclasses
        self._rec("monitor_set", key, value)
        m = self.state.peripheral("monitor")
        self.state.set_peripheral("monitor", dataclasses.replace(m, values={**m.values, key: value}))

    def monitor_set_input(self, value: int) -> None:
        import dataclasses
        self._rec("monitor_set_input", value)
        m = self.state.peripheral("monitor")
        self.state.set_peripheral("monitor", dataclasses.replace(m, values={**m.values, "input": value}))

    def aura_sync_set(self, view: AuraSyncView) -> None:
        self._rec("aura_sync_set", view)
        self.state.set_aura_sync(view)
