"""UI -> backend bridge: the only write path of the application."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSignal
from PyQt6.QtDBus import QDBusConnection

from ..backend import dbus_util
from ..backend.dbus_util import Typed
from ..backend.types import Epp, FanCurve, GfxMode, GfxPower, Profile
from ..i18n import tr
from ..backend.ddc import FEATURES as DDC_FEATURES
from ..backend.ledcolor import led_decode, led_encode
from .state import AURA_EFFECTS, AURA_TARGETS, AppState, AuraSyncView, AuraView, DisplayView, GfxView

log = logging.getLogger(__name__)

MUX_PATH = "/sys/devices/platform/asus-nb-wmi/gpu_mux_mode"

PPT_MIN, PPT_MAX = 15, 170
DEFAULT_CUSTOM = (60, 90, 110)

_POLICY_TO_MODE = {
    Profile.QUIET: "quiet",
    Profile.BALANCED: "balanced",
    Profile.PERFORMANCE: "turbo",
}
_MODE_TO_PROFILE = {
    "quiet": Profile.QUIET,
    "balanced": Profile.BALANCED,
    "turbo": Profile.PERFORMANCE,
    "custom": Profile.PERFORMANCE,
}
_EPP_PROP = {
    "quiet": "ThrottleQuietEpp",
    "balanced": "ThrottleBalancedEpp",
    "turbo": "ThrottlePerformanceEpp",
    "custom": "ThrottlePerformanceEpp",
}
_GFX_TO_VIEW = {
    GfxMode.INTEGRATED: "eco",
    GfxMode.HYBRID: "standard",
    GfxMode.ASUS_MUX_DGPU: "ultimate",
}
_VIEW_TO_GFX = {"eco": GfxMode.INTEGRATED, "standard": GfxMode.HYBRID}
_POWER_TO_STR = {
    GfxPower.ACTIVE: "active",
    GfxPower.SUSPENDED: "sleep",
    GfxPower.OFF: "off",
    GfxPower.ASUS_DISABLED: "off",
}

K_CUSTOM_ACTIVE = "perf/custom_active"
K_PL = ("custom/pl1", "custom/pl2", "custom/fppt")
K_AUTO_REFRESH = "display/auto_refresh"
K_KBD_LAST = "kbd/last_level"
K_GPU_OPTIMIZE = "gpu/optimize"
OPT_DEBOUNCE_MS = 5000          # Optimize: AC<->battery must be stable this long before switching
HOLDER_POLL_MS = 5000           # waiting for the dGPU to be released: poll interval
POST_SWITCH_REFRESH_MS = 3000   # supergfxd restarts during a switch: re-read after this
SWITCH_HINT_MS = 20000          # how long the expected mode masks a stale supergfxd answer
_LIVE_TARGET = {"eco": GfxMode.INTEGRATED, "standard": GfxMode.HYBRID}
_MODES = ("eco", "standard", "optimize", "ultimate")
K_AURA = "aura_sync/"
AURA_DEBOUNCE_MS = 300
MONITOR_BUSY_TIMEOUT_MS = 20_000
_AURA_MOUSE_MODE = {"static": 0, "breathing": 1, "cycle": 2}
_AURA_HEADSET_EFFECT = {"static": 1, "breathing": 2, "cycle": 4}
PPT_PROPS = ("PptPl1Spl", "PptPl2Sppt", "PptFppt")
# custom and turbo are the same asusd profile (PERFORMANCE): they share one set of fan curves.
_CURVE_GROUP = {"turbo": ("turbo", "custom"), "custom": ("turbo", "custom")}


def _clamp_limits(pl1: int, pl2: int, fppt: int) -> tuple[int, int, int]:
    pl1 = max(PPT_MIN, min(PPT_MAX, int(pl1)))
    pl2 = max(PPT_MIN, min(PPT_MAX, int(pl2)))
    fppt = max(PPT_MIN, min(PPT_MAX, int(fppt)))
    pl2 = max(pl2, pl1)
    fppt = max(fppt, pl2)
    return pl1, pl2, fppt


def _helper_exit_code(message: str) -> int | None:
    """Fallback only: recover the exit code from the message text.

    Prefer ``GfxClient.last_exit_code``; this is used when a gfx client
    (e.g. a test fake) doesn't provide it.
    """
    m = re.search(r"code (\d+)", message)
    if m:
        return int(m.group(1))
    if "supergfxd durdurulamadı" in message or "could not stop supergfxd" in message:
        return 7
    if "Eco'dan çıkış tamamlanamadı" in message or "Eco exit failed" in message:
        return 8
    if "MUX" in message:
        return 4
    return None


class Controller(QObject):
    # Emitted after a successful Eco exit: the dGPU is back and a reboot is REQUIRED NOW.
    gpuRebootRequired = pyqtSignal()
    # The dGPU is held by processes: UI asks wait / reboot / cancel (-> resolve_busy). Payload: [Holder].
    gpuBusy = pyqtSignal(list)
    # A GPU switch failed: (message, reboot_required).
    gpuSwitchFailed = pyqtSignal(str, bool)
    # The user picked Ultimate: UI shows the risk dialog and answers with confirm_ultimate(bool).
    gpuUltimateConfirm = pyqtSignal()

    def __init__(
        self,
        state: AppState,
        asusd,
        gfx,
        sensors,
        display,
        settings: QSettings,
        *,
        mouse=None,
        headset=None,
        ddc=None,
        mux_path: str = MUX_PATH,
        dbus_call: Callable[..., None] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.state = state
        self.asusd = asusd
        self.gfx = gfx
        self.sensors = sensors
        self.display = display
        self.settings = settings
        self.mouse, self.headset, self.ddc = mouse, headset, ddc
        self.mux_path = mux_path
        self._dbus_call = dbus_call or dbus_util.async_call
        self._started = False

        self._policy: Profile | None = None
        self._custom_flag = settings.value(K_CUSTOM_ACTIVE, False, type=bool)
        self._auto_refresh = settings.value(K_AUTO_REFRESH, False, type=bool)
        self._auto_pending = False           # auto-refresh wants to apply once a fresh display state arrives
        self._on_ac: bool | None = None
        # GPU switching / Optimize state (see the "GPU" section)
        self._optimize = settings.value(K_GPU_OPTIMIZE, False, type=bool)
        self._switching = False
        self._waiting: str | None = None
        self._holders: list = []
        self._busy_target: str | None = None       # live switch refused as busy; waiting for resolve_busy()
        self._selected_hint: str | None = None
        self._expect_active: str | None = None     # target of a finished live switch until supergfxd agrees
        self._opt_apply_pending = False
        self._poll_inflight = False
        self._mux_pending: int | None = None       # MUX value written this session (effective after reboot)
        self._mux_orig: int | None = None          # MUX value before that write
        self._mux_prev: tuple | None = None
        self._opt_timer = QTimer(self)
        self._opt_timer.setSingleShot(True)
        self._opt_timer.setInterval(OPT_DEBOUNCE_MS)
        self._opt_timer.timeout.connect(self._optimize_apply)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(HOLDER_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_holders)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(POST_SWITCH_REFRESH_MS)
        self._refresh_timer.timeout.connect(lambda: self.gfx.refresh())
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(SWITCH_HINT_MS)
        self._hint_timer.timeout.connect(self._drop_switch_hint)
        self._display_state: Any = None
        self._refresh_busy = False
        # A persisted custom flag is only trusted once the firmware state confirms it (policy PERFORMANCE and the
        # cached Ppt* values equal custom_limits()); until then the mode is derived as turbo.
        self._startup_pending = self._custom_flag
        self._seen: dict[str, Any] = {}      # last value seen per platform property
        self.state.set_display(DisplayView(auto=self._auto_refresh))
        # Aura Sync: persisted view, per-target "ready" flags (re-apply only on False -> True) and the last
        # parameters sent to each target (so a change that doesn't concern a device never touches it).
        self._aura_ready = {"mouse": False, "headset": False}
        self._kbd_written: dict[tuple, tuple] = {}   # raw keyboard colour -> sRGB colour we picked
        self._aura_last: dict[str, tuple] = {}
        self._aura_timer = QTimer(self)
        self._aura_timer.setSingleShot(True)
        self._aura_timer.setInterval(AURA_DEBOUNCE_MS)
        self._aura_timer.timeout.connect(self._aura_flush)
        self.state.set_aura_sync(self._load_aura_sync())

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.asusd.platformChanged.connect(self._on_platform)
        self.asusd.auraChanged.connect(self._on_aura)
        self.asusd.error.connect(self._on_asusd_error)
        self.gfx.modeChanged.connect(lambda _m: self._rebuild_gfx())
        self.gfx.powerChanged.connect(lambda _p: self._rebuild_gfx())
        if hasattr(self.gfx, "pendingChanged"):
            self.gfx.pendingChanged.connect(lambda *_a: self._rebuild_gfx())
        if hasattr(self.gfx, "availableChanged"):
            # supergfxd vanishes and reappears during a live switch: just re-read, never an error
            self.gfx.availableChanged.connect(lambda _a: self._rebuild_gfx())
        if self._optimize and self._read_mux_direct():
            self._optimize = False           # Optimize cannot run in Ultimate (dGPU direct)
            self.settings.setValue(K_GPU_OPTIMIZE, False)
        self.sensors.updated.connect(self._on_sensors)
        self.display.changed.connect(self._on_display)
        self.display.error.connect(self._on_display_error)

        for name, value in self._cached_platform().items():
            self._on_platform(name, value)
        self._on_aura_cached()
        self.asusd.refresh()
        self.gfx.refresh()
        self.display.refresh()
        self._rebuild_gfx()
        self.sensors.start(1000)
        self._start_peripherals()

    def _cached_platform(self) -> dict[str, Any]:
        names = ("ThrottleThermalPolicy", "ChargeControlEndThreshold", *PPT_PROPS)
        out = {}
        for n in names:
            v = self.asusd.get_cached(n)
            if v is not None:
                out[n] = v
        return out

    # ----------------------------------------------------------- busy / error
    def _pulse(self, key: str, fn: Callable[[], None]) -> None:
        """Run a fire-and-forget write wrapped in busyChanged(key, True/False)."""
        self.state.emit_busy(key, True)
        try:
            fn()
        except Exception:
            log.exception("write %s failed", key)
            self.state.emit_message("error", tr("İşlem başarısız oldu ({key}).", key=key))
        finally:
            QTimer.singleShot(0, lambda: self.state.emit_busy(key, False))

    def _on_asusd_error(self, op: str, msg: str) -> None:
        if op.endswith("GpuMuxMode") and getattr(self, "_mux_prev", None) is not None:
            self._mux_pending, self._mux_orig = self._mux_prev     # the write failed: nothing pending
            self._mux_prev = None
            self._rebuild_gfx()
        if op.endswith("ThrottleThermalPolicy") and self._custom_flag:
            # the policy write behind "custom" failed: custom is not in effect
            log.warning("policy write failed; clearing custom flag")
            self._set_custom_flag(False)
            self._derive_mode()
        self.state.emit_message("error", tr("asusd işlemi başarısız ({op}): {msg}", op=op, msg=msg))

    def _on_display_error(self, msg: str) -> None:
        self.state.emit_message("error", tr("Yenileme hızı değiştirilemedi: {msg}", msg=msg))
        self._end_refresh_busy()

    # ------------------------------------------------------------ platform
    def _on_platform(self, name: str, value: Any) -> None:
        self.state.set_platform_value(name, value)
        self._seen[name] = value
        if self._startup_pending and (name == "ThrottleThermalPolicy" or name in PPT_PROPS):
            self._resolve_startup_custom()
            if not self._startup_pending:
                self._derive_mode()
        if name == "ThrottleThermalPolicy":
            try:
                policy = Profile(int(value))
            except (TypeError, ValueError):
                return
            self._policy = policy
            if policy != Profile.PERFORMANCE and self._custom_flag:
                self._set_custom_flag(False)
            self._derive_mode()
        elif name == "ChargeControlEndThreshold":
            try:
                self.state.set_battery_limit(int(value))
            except (TypeError, ValueError):
                pass

    def _resolve_startup_custom(self) -> None:
        """Decide once whether a persisted custom flag is still backed by the firmware."""
        policy = self._seen.get("ThrottleThermalPolicy")
        if policy is None:
            return
        try:
            is_perf = int(policy) == int(Profile.PERFORMANCE)
        except (TypeError, ValueError):
            return
        if not is_perf:
            self._startup_pending = False
            self._set_custom_flag(False)
            return
        ppt = [self._seen.get(n) for n in PPT_PROPS]
        if any(v is None for v in ppt):
            return  # wait for the remaining values
        self._startup_pending = False
        try:
            same = tuple(int(v) for v in ppt) == self.custom_limits()
        except (TypeError, ValueError):
            same = False
        if not same:
            log.info("startup: persisted custom flag but Ppt %s != custom limits %s -> turbo",
                     ppt, self.custom_limits())
            self._set_custom_flag(False)

    def _set_custom_flag(self, flag: bool) -> None:
        self._custom_flag = flag
        self.settings.setValue(K_CUSTOM_ACTIVE, flag)

    def _derive_mode(self) -> None:
        if self._policy is None:
            return
        if self._policy == Profile.PERFORMANCE and self._custom_flag and not self._startup_pending:
            mode = "custom"
        else:
            mode = _POLICY_TO_MODE[self._policy]
        self.state.set_perf_mode(mode)

    # ------------------------------------------------------------ perf mode
    def custom_limits(self) -> tuple[int, int, int]:
        vals = [self.settings.value(k, d, type=int) for k, d in zip(K_PL, DEFAULT_CUSTOM)]
        return _clamp_limits(*vals)

    def set_perf_mode(self, mode: str) -> None:
        if mode not in _MODE_TO_PROFILE:
            self.state.emit_message("error", tr("Bilinmeyen mod: {mode}", mode=mode))
            return
        custom = mode == "custom"
        target = _MODE_TO_PROFILE[mode]
        leaving_custom = self.state.perf_mode == "custom" or self._custom_flag
        self._startup_pending = False

        def write() -> None:
            if leaving_custom and not custom and target == Profile.PERFORMANCE:
                # Mechanism (as in G-Helper): on ASUS firmware a thermal-policy CHANGE resets PPT to the profile
                # defaults. Policy is already PERFORMANCE while in custom, so writing it again changes nothing and
                # the custom PPT would stay. Bounce through BALANCED first so the change really happens.
                log.info("leaving custom for turbo: writing BALANCED then PERFORMANCE so the firmware "
                         "resets PPT to defaults")
                self.asusd.set_platform("ThrottleThermalPolicy", int(Profile.BALANCED))
            self.asusd.set_platform("ThrottleThermalPolicy", int(target))
            # Only after the policy write was issued without raising: persist/derive the flag. An asusd-side
            # failure arrives later via error() and clears it (_on_asusd_error).
            self._set_custom_flag(custom)
            self._derive_mode()
            if custom:
                self._write_limits(*self.custom_limits())
            elif leaving_custom:
                log.info("left custom: policy change makes the firmware restore its own power limits")

        self._pulse("perf", write)

    def _write_limits(self, pl1: int, pl2: int, fppt: int) -> None:
        log.info("writing custom limits PL1=%s PL2=%s FPPT=%s W; firmware semantics "
                 "of these Ppt* values are unverified", pl1, pl2, fppt)
        self.asusd.set_platform("PptPl1Spl", pl1)
        self.asusd.set_platform("PptPl2Sppt", pl2)
        self.asusd.set_platform("PptFppt", fppt)

    def set_custom_limits(self, pl1: int, pl2: int, fppt: int) -> None:
        pl1, pl2, fppt = _clamp_limits(pl1, pl2, fppt)
        for key, v in zip(K_PL, (pl1, pl2, fppt)):
            self.settings.setValue(key, v)
        if self.state.perf_mode == "custom":
            self._pulse("custom", lambda: self._write_limits(pl1, pl2, fppt))

    # ------------------------------------------------------------------ GPU
    def _read_mux_direct(self) -> bool | None:
        try:
            with open(self.mux_path, encoding="utf-8") as fh:
                text = fh.read().strip()
        except OSError:
            return None
        return (text == "0") if text in ("0", "1") else None

    def _rebuild_gfx(self) -> None:
        mode = getattr(self.gfx, "mode", None)
        active = _GFX_TO_VIEW.get(mode) if mode is not None else None
        if self._expect_active is not None:
            if active == self._expect_active:
                self._drop_switch_hint(rebuild=False)
            else:
                active = self._expect_active      # supergfxd restarting / not yet updated
        boot_mode = self.gfx.configured_boot_mode()
        boot = _GFX_TO_VIEW.get(boot_mode) if boot_mode is not None else None
        pending = boot if (boot is not None and active is not None and boot != active) else None
        if self._switching:
            # the helper writes the boot config first; until it finishes boot != active is expected,
            # not a "reboot to complete" state (it looked exactly like a half-done Eco exit)
            pending = None
        snap = self.state.sensors
        if snap is not None and getattr(snap, "gpu_state", "unknown") != "unknown":
            power = snap.gpu_state
        else:
            gp = getattr(self.gfx, "power", None)
            power = _POWER_TO_STR.get(gp, "unknown") if gp is not None else "unknown"
        mux_direct = self._read_mux_direct()
        if self._mux_pending == 0:
            mux_direct = True
        live_fn = getattr(self.gfx, "live_ready", None)
        live_ready = bool(live_fn()) if callable(live_fn) else False
        if self._optimize:
            selected = "optimize"
        elif self._selected_hint is not None and self._selected_hint != active:
            selected = self._selected_hint
        else:
            self._selected_hint = None
            selected = active
        self.state.set_gfx(GfxView(
            active=active, boot=boot, pending=pending, power=power,
            dgpu_disabled=self.gfx.dgpu_disabled(),
            mux_direct=mux_direct,
            can_eco_exit=True,
            selected=selected,
            switching=self._switching,
            waiting=self._waiting,
            holders=list(self._holders),
            live_ready=live_ready,
            optimize=self._optimize,
        ))
        if (self._opt_apply_pending and self._optimize and not self._switching
                and active is not None and self._on_ac is not None):
            self._opt_apply_pending = False
            self._optimize_apply()

    def _drop_switch_hint(self, rebuild: bool = True) -> None:
        self._expect_active = None
        self._hint_timer.stop()
        if rebuild:
            self.gfx.refresh()
            self._rebuild_gfx()

    # --- helpers for the MUX state ------------------------------------------------------
    def _hw_direct(self) -> bool:
        """The hardware is dGPU-direct NOW (Ultimate), whatever was written for the next boot."""
        return bool(self._read_mux_direct()) or self.state.gfx.active == "ultimate"

    def _chosen_direct(self) -> bool:
        """Ultimate is what the machine will boot into (pending write wins over the current state)."""
        return (self._mux_pending == 0) if self._mux_pending is not None else self._hw_direct()

    def _live_possible(self) -> bool:
        live_fn = getattr(self.gfx, "live_ready", None)
        return (callable(live_fn) and bool(live_fn()) and not self._hw_direct()
                and self._mux_pending is None and self.state.gfx.active in _LIVE_TARGET)

    def _warn_ultimate_blocks(self) -> None:
        self.state.emit_message(
            "warn", tr("Ultimate (dGPU doğrudan) MUX modunda Eco kullanılamaz. "
                       "Önce Ultimate modundan çıkılmalı."))

    # --- public API ---------------------------------------------------------------------
    def request_gpu_mode(self, mode: str) -> None:
        if mode not in _MODES:
            self.state.emit_message("warn", tr("Bu GPU modu henüz desteklenmiyor."))
            return
        if self._switching:
            self.state.emit_message("warn", tr("Bir GPU geçişi sürüyor; bitmesini bekle."))
            return
        self._busy_target = None
        if mode == "ultimate":
            if self._chosen_direct():
                self.state.emit_message("info", tr("Ultimate zaten etkin."))
                return
            self.gpuUltimateConfirm.emit()
            return
        if mode == "optimize":
            self._enable_optimize()
            return
        if mode == "standard" and self._chosen_direct():
            self._set_optimize(False)
            self._clear_waiting()
            self._selected_hint = "standard"
            self._write_mux(1)
            return
        if self._chosen_direct() or self._hw_direct():
            if mode == "standard":      # MUX already restored this session; reboot completes it
                self.state.emit_message("info", tr("Standart yeniden başlatınca etkin olacak."))
            else:
                self._warn_ultimate_blocks()
            return
        self._set_optimize(False)
        self._clear_waiting()
        self._selected_hint = mode
        self._switch_to(mode, "user")

    def confirm_ultimate(self, ok: bool) -> None:
        """Answer to ``gpuUltimateConfirm``: write MUX=0 (effective after reboot) when confirmed."""
        if not ok or self._switching or self._chosen_direct():
            return
        self._set_optimize(False)
        self._clear_waiting()
        self._selected_hint = "ultimate"
        self._write_mux(0)

    def resolve_busy(self, choice: str) -> None:
        """Answer to ``gpuBusy``: "wait" (switch when the dGPU is free) | "reboot" (boot config) | "cancel"."""
        target = self._busy_target
        if target is None or choice not in ("wait", "reboot", "cancel"):
            return
        self._busy_target = None
        if choice == "wait":
            self._enter_waiting(target, list(self._holders))
        elif choice == "reboot":
            self._request_boot(_LIVE_TARGET[target], target, cancel=False)
        else:
            self._selected_hint = None
            self._holders = []
            self._rebuild_gfx()

    def cancel_gpu_pending(self) -> None:
        if self._switching:
            self.state.emit_message("warn", tr("Bir GPU geçişi sürüyor; bitmesini bekle."))
            return
        if self._waiting is not None or self._busy_target is not None:
            self._busy_target = None
            self._selected_hint = None
            self._clear_waiting()
            self.state.emit_message("info", tr("Bekleyen GPU değişikliği iptal edildi."))
            return
        if self._mux_pending is not None and self._mux_orig is not None:
            self._selected_hint = None
            self._write_mux(self._mux_orig)
            return
        active = self.state.gfx.active
        if active not in _VIEW_TO_GFX:
            self.state.emit_message("warn", tr("Bekleyen değişiklik iptal edilemedi: "
                                       "etkin GPU modu bilinmiyor veya desteklenmiyor."))
            return
        self._selected_hint = None
        self._request_boot(_VIEW_TO_GFX[active], active, cancel=True)

    # --- Ultimate (MUX) -----------------------------------------------------------------
    def _write_mux(self, value: int) -> None:
        """asusd GpuMuxMode (0 = dGPU direct, 1 = hybrid); takes effect after a reboot."""
        orig = self._mux_orig if self._mux_pending is not None else (0 if self._hw_direct() else 1)
        self._mux_prev = (self._mux_pending, self._mux_orig)
        self._mux_orig = orig
        self._mux_pending = None if value == orig else value
        self.asusd.set_platform("GpuMuxMode", value)
        self._rebuild_gfx()
        if self._mux_pending is None:
            self.state.emit_message("info", tr("MUX değişikliği geri alındı."))
        elif value == 0:
            self.state.emit_message(
                "info", tr("Ultimate yeniden başlatınca etkin olacak. Bilgisayarı yeniden başlatman gerekiyor."))
            self.gpuRebootRequired.emit()
        else:
            self.state.emit_message(
                "info", tr("Ultimate'tan çıkış yeniden başlatınca etkin olacak. "
                           "Bilgisayarı yeniden başlatman gerekiyor."))
            self.gpuRebootRequired.emit()

    # --- switching ----------------------------------------------------------------------
    def _switch_to(self, target: str, source: str) -> None:
        """eco/standard: live when possible, else the boot-config path (reboot)."""
        active = self.state.gfx.active
        if active == target and self.state.gfx.pending is None and source == "user":
            self._selected_hint = None
            self._rebuild_gfx()
            self.state.emit_message("info", tr("{name} zaten etkin.", name=tr(self._label(target))))
            return
        if self._live_possible() and active != target:
            self._live(target, source)
        else:
            self._request_boot(_VIEW_TO_GFX[target], target, cancel=False)

    @staticmethod
    def _label(target: str) -> str:
        return {"eco": "Eco", "standard": "Standart"}[target]

    def _live(self, target: str, source: str) -> None:
        """Run the helper's live switch. source: "user" (may ask via gpuBusy) | "optimize" | "wait" (silent)."""
        self._switching = True
        self.state.emit_busy("gpu", True)
        self._rebuild_gfx()

        def done(result) -> None:
            self._switching = False
            self.state.emit_busy("gpu", False)
            if result.ok:
                self._live_succeeded(target)
                return
            if getattr(result, "error", None) == "busy":
                holders = list(getattr(result, "holders", []) or [])
                self._holders = holders
                if source == "user":
                    self._busy_target = target
                    self._rebuild_gfx()
                    self.gpuBusy.emit(holders)
                else:
                    self._enter_waiting(target, holders, announce=(self._waiting != target))
                return
            self._opt_apply_pending = False
            self._selected_hint = None
            if source == "wait":
                self._clear_waiting()
            self._holders = []
            self._rebuild_gfx()
            self._live_failed(result)

        try:
            self.gfx.request_live(_LIVE_TARGET[target], done)
        except Exception:
            log.exception("request_live raised")
            from ..backend.gfx import LiveResult
            done(LiveResult(False, error="exception", message="beklenmeyen hata"))

    def _live_succeeded(self, target: str) -> None:
        self._expect_active = target
        self._selected_hint = None
        self._holders = []
        if self._waiting == target:
            self._waiting = None
            self._poll_timer.stop()
        self._hint_timer.start()
        self._refresh_timer.start()
        self.gfx.refresh()
        self._rebuild_gfx()
        self.state.emit_message(
            "info", tr("{name} moduna geçildi.", name=tr(self._label(target))))

    def _live_failed(self, r) -> None:
        err, code, msg = getattr(r, "error", None), getattr(r, "code", None), getattr(r, "message", "")
        reboot = bool(getattr(r, "reboot_required", False))
        if code == 126 or err == "cancelled":
            self.state.emit_message("info", tr("Yetkilendirme iptal edildi; hiçbir şey değiştirilmedi."))
            return
        if code == 127 or err == "unavailable":
            text = tr("GPU yardımcısı çalıştırılamadı: yetki verilmedi ya da kurulu değil "
                      "(kurulum: sudo helper/install.sh).")
        elif err == "mux":
            text = tr("Ultimate (dGPU doğrudan) MUX modunda Eco kullanılamaz. "
                      "Önce Ultimate modundan çıkılmalı.")
        elif err == "supergfxd":
            text = tr("supergfxd durdurulamadı; GPU geçişi başlatılmadı. Hiçbir şey değişmedi.")
        elif err == "precondition":
            text = tr("Canlı GPU geçişi için kurulum eksik (kurulum: sudo helper/install.sh): {msg}", msg=msg)
        elif err == "aborted":
            text = tr("GPU geçişi başlamadan durduruldu; hiçbir şey değişmedi. ({msg})", msg=msg)
        elif err == "failed" or reboot:
            text = tr("GPU geçişi yarıda kaldı ({msg}). Yapılandırma hedef moda ayarlı; "
                      "yeniden başlatmak geçişi güvenle tamamlar.", msg=msg)
        else:
            text = tr("GPU modu değiştirilemedi: {msg}", msg=msg)
        self.gpuSwitchFailed.emit(text, reboot)

    # --- waiting for the dGPU to be released -----------------------------------------
    def _enter_waiting(self, target: str, holders: list, announce: bool = True) -> None:
        self._waiting = target
        self._holders = holders
        if not self._poll_timer.isActive():
            self._poll_timer.start()
        self._rebuild_gfx()
        if announce:
            names = ", ".join(dict.fromkeys(getattr(h, "comm", "") or "?" for h in holders)) or tr("Bir uygulama")
            if target == "eco":
                text = tr("{app} dGPU kullanıyor; kapanınca Eco'ya geçilecek", app=names)
            else:
                text = tr("{app} dGPU kullanıyor; kapanınca Standart'a geçilecek", app=names)
            self.state.emit_message("info", text)

    def _clear_waiting(self) -> None:
        if self._waiting is None and not self._holders:
            return
        self._waiting = None
        self._holders = []
        self._poll_timer.stop()
        self._rebuild_gfx()

    def _poll_holders(self) -> None:
        target = self._waiting
        if target is None or self._switching or self._poll_inflight:
            return
        self._poll_inflight = True

        def cb(holders: list) -> None:
            self._poll_inflight = False
            if self._waiting != target or self._switching:
                return
            self._holders = list(holders)
            if holders:
                self._rebuild_gfx()
            else:
                self._live(target, "wait")

        try:
            self.gfx.query_holders(cb)
        except Exception:
            log.exception("query_holders raised")
            self._poll_inflight = False

    # --- Optimize -----------------------------------------------------------------------
    def _set_optimize(self, on: bool) -> None:
        self._opt_timer.stop()
        if on == self._optimize:
            return
        self._optimize = on
        self._opt_apply_pending = False
        self.settings.setValue(K_GPU_OPTIMIZE, on)

    def _enable_optimize(self) -> None:
        if self._chosen_direct() or self._hw_direct():
            self._warn_ultimate_blocks()
            return
        live_fn = getattr(self.gfx, "live_ready", None)
        if not (callable(live_fn) and live_fn()):
            self.state.emit_message(
                "warn", tr("Optimize için canlı GPU geçişi gerekiyor; kurulu değil "
                           "(kurulum: sudo helper/install.sh, MUX Hybrid olmalı)."))
            return
        self._selected_hint = None
        self._clear_waiting()
        self._set_optimize(True)
        self._rebuild_gfx()
        self._optimize_apply()

    def _optimize_apply(self) -> None:
        """Bring the GPU to the mode that fits the current power source (AC -> standard, battery -> eco)."""
        if not self._optimize:
            return
        if self._on_ac is None:
            self._opt_apply_pending = True       # first sensor snapshot will trigger it
            return
        target = "standard" if self._on_ac else "eco"
        if self._waiting is not None and self._waiting != target:
            self._clear_waiting()
        active = self.state.gfx.active
        if self._switching or active is None:
            self._opt_apply_pending = True
            return
        if active == "ultimate" or self._hw_direct() or self._mux_pending is not None:
            return
        if active == target:
            self._clear_waiting()
            return
        if self._waiting == target:
            return
        if not self._live_possible():
            log.info("optimize: live switching unavailable, leaving the GPU as it is")
            return
        self._live(target, "optimize")

    def _request_boot(self, gfx_mode: GfxMode, name: str, cancel: bool) -> None:
        leaving_eco = (not cancel and name == "standard" and self.state.gfx.active == "eco")
        self.state.emit_busy("gpu", True)

        def done(ok: bool, msg: str) -> None:
            self.state.emit_busy("gpu", False)
            self._rebuild_gfx()
            if ok:
                if cancel:
                    self.state.emit_message("info", tr("Bekleyen GPU değişikliği iptal edildi."))
                elif leaving_eco:
                    self.state.emit_message(
                        "info", tr("dGPU yeniden etkinleştirildi. Standart mod için bilgisayarı ŞİMDİ "
                                   "yeniden başlatman gerekiyor."))
                    self.gpuRebootRequired.emit()
                else:
                    label = {"eco": "Eco", "standard": "Standart"}[name]
                    self.state.emit_message("info", tr("{name} yeniden başlatınca etkin olacak.", name=tr(label)))
                return
            code = getattr(self.gfx, "last_exit_code", None)
            if code is None:
                code = _helper_exit_code(msg)
            if code == 126:
                self.state.emit_message("info", tr("Yetkilendirme iptal edildi; hiçbir şey değiştirilmedi."))
            elif code == 127:
                self.state.emit_message(
                    "error",
                    tr("GPU yardımcısı çalıştırılamadı: yetki verilmedi ya da kurulu değil "
                       "(kurulum: sudo helper/install.sh)."))
            elif code == 7:
                self.state.emit_message(
                    "error",
                    tr("supergfxd durdurulamadı; Eco'dan çıkış başlatılmadı ve yapılandırma geri alındı. "
                       "Hiçbir şey değişmedi."))
            elif code == 8:
                self.state.emit_message(
                    "error",
                    tr("Eco'dan çıkış tamamlanamadı: dGPU açılamadı. Yapılandırma Standart olarak kaldı; "
                       "yeniden başlatırsan bilgisayar güvenle Eco'da açılır."))
            elif code == 4:
                self.state.emit_message(
                    "warn",
                    tr("Ultimate (dGPU doğrudan) MUX modunda Eco kullanılamaz. "
                       "Önce Ultimate modundan çıkılmalı."))
            else:
                self.state.emit_message("error", tr("GPU modu değiştirilemedi: {msg}", msg=msg))

        try:
            self.gfx.request_boot_mode(gfx_mode, done)
        except Exception:
            log.exception("request_boot_mode raised")
            done(False, "beklenmeyen hata")

    def reboot_now(self) -> None:
        log.info("requesting reboot via logind")
        self.state.emit_busy("reboot", True)

        def done(_result, err) -> None:
            self.state.emit_busy("reboot", False)
            if err:
                self.state.emit_message("error", tr("Yeniden başlatılamadı: {err}", err=err))

        self._dbus_call(
            QDBusConnection.systemBus(), "org.freedesktop.login1", "/org/freedesktop/login1",
            "org.freedesktop.login1.Manager", "Reboot", [Typed("b", False)], done,
        )

    # -------------------------------------------------------------- display
    def _on_display(self, st: Any) -> None:
        self._display_state = st
        self._publish_display()
        self._end_refresh_busy()
        self._run_auto_refresh()

    def _publish_display(self) -> None:
        st = self._display_state
        if st is None:
            self.state.set_display(DisplayView(auto=self._auto_refresh))
        else:
            self.state.set_display(DisplayView(
                connector=st.connector, current_hz=st.current_hz,
                rates=list(st.rates), auto=self._auto_refresh))

    def _end_refresh_busy(self) -> None:
        if self._refresh_busy:
            self._refresh_busy = False
            self.state.emit_busy("refresh", False)

    def _begin_refresh_busy(self) -> None:
        if not self._refresh_busy:
            self._refresh_busy = True
            self.state.emit_busy("refresh", True)
            QTimer.singleShot(10000, self._end_refresh_busy)

    def set_refresh(self, hz: int | None) -> None:
        if hz is None:
            self._auto_refresh = True
            self.settings.setValue(K_AUTO_REFRESH, True)
            self._publish_display()
            # explicit enable: apply once now (needs on_ac and a fresh display state)
            self._request_auto_refresh()
            return
        self._auto_refresh = False
        self._auto_pending = False
        self.settings.setValue(K_AUTO_REFRESH, False)
        self._publish_display()
        self._apply_hz(int(hz))

    def _apply_hz(self, hz: int) -> None:
        self._begin_refresh_busy()
        self.display.set_refresh(hz)

    def _request_auto_refresh(self) -> None:
        """Ask for a fresh display state; the rate is decided in _run_auto_refresh when it arrives."""
        if not self._auto_refresh:
            return
        self._auto_pending = True
        if self._on_ac is not None:
            self.display.refresh()

    def _run_auto_refresh(self) -> None:
        if not (self._auto_pending and self._auto_refresh) or self._on_ac is None:
            return
        st = self._display_state
        if st is None or not st.rates:
            return
        self._auto_pending = False
        rates = list(st.rates)
        target = max(rates) if self._on_ac else (60 if 60 in rates else None)
        if target is None or target == st.current_hz:
            return
        log.info("auto refresh: on_ac=%s -> %s Hz", self._on_ac, target)
        self._apply_hz(target)

    # -------------------------------------------------------------- sensors
    def _on_sensors(self, snap: Any) -> None:
        self.state.set_sensors(snap)
        on_ac = getattr(snap, "on_ac", None)
        if on_ac is not None:
            prev, self._on_ac = self._on_ac, bool(on_ac)
            # Auto applies once on the first snapshot (booting on battery must still drop to 60 Hz), then on
            # every AC<->battery TRANSITION; repeated snapshots with the same value don't write.
            if self._auto_refresh and (self._auto_pending or prev != self._on_ac):
                self._request_auto_refresh()
            if self._optimize:
                if prev is None:
                    self._optimize_apply()       # once at start
                elif prev != self._on_ac:
                    wanted = "standard" if self._on_ac else "eco"
                    if self._waiting is not None and self._waiting != wanted:
                        self._clear_waiting()
                    self._opt_timer.start()      # restart = debounce flapping power sources
            if prev is None and not self._on_ac:
                self._maybe_apply_battery_profile()
        # sensors may refine the GPU power string
        cur = self.state.gfx.power
        gs = getattr(snap, "gpu_state", "unknown")
        if gs != "unknown" and gs != cur:
            self._rebuild_gfx()

    def _maybe_apply_battery_profile(self) -> None:
        """Started on battery: apply asusd's battery profile once.

        asusd only switches ThrottleThermalPolicy on an AC<->battery TRANSITION, so after booting
        (or logging in) on battery the laptop stays in whatever profile it had — measured ~3 W more
        in Balanced than in Quiet. This is the one deliberate startup write, and only when the user
        enabled asusd's "change profile on battery" setting; manual changes later are left alone.
        """
        plat = self.state.platform
        if not plat.get("ChangeThrottlePolicyOnBattery"):
            return
        target, current = plat.get("ThrottlePolicyOnBattery"), plat.get("ThrottleThermalPolicy")
        if target is None or current is None or int(target) == int(current):
            return
        log.info("started on battery: applying battery profile %s (was %s)", target, current)
        self._pulse("perf", lambda: self.asusd.set_platform("ThrottleThermalPolicy", int(target)))

    # ----------------------------------------------------- simple platform writes
    def set_panel_od(self, on: bool) -> None:
        self._pulse("panel_od", lambda: self.asusd.set_platform("PanelOd", bool(on)))

    def set_battery_limit(self, pct: int) -> None:
        pct = max(20, min(100, int(pct)))
        self._pulse("battery_limit",
                    lambda: self.asusd.set_platform("ChargeControlEndThreshold", pct))

    def set_epp(self, mode: str, epp: int) -> None:
        prop = _EPP_PROP.get(mode)
        if prop is None:
            self.state.emit_message("error", tr("Bilinmeyen mod: {mode}", mode=mode))
            return
        try:
            value = int(Epp(int(epp)))
        except ValueError:
            self.state.emit_message("error", tr("Geçersiz EPP değeri: {epp}", epp=epp))
            return
        self._pulse("epp", lambda: self.asusd.set_platform(prop, value))

    def set_nv_boost(self, w: int) -> None:
        self._pulse("nv", lambda: self.asusd.set_platform("NvDynamicBoost", int(w)))

    def set_nv_temp_target(self, c: int) -> None:
        self._pulse("nv", lambda: self.asusd.set_platform("NvTempTarget", int(c)))

    def set_auto_profile(self, on_ac: str, on_battery: str) -> None:
        try:
            ac, bat = _MODE_TO_PROFILE[on_ac], _MODE_TO_PROFILE[on_battery]
        except KeyError:
            self.state.emit_message("error", tr("Geçersiz otomatik profil seçimi."))
            return

        def write() -> None:
            self.asusd.set_platform("ThrottlePolicyOnAc", int(ac))
            self.asusd.set_platform("ThrottlePolicyOnBattery", int(bat))
            self.asusd.set_platform("ChangeThrottlePolicyOnAc", True)
            self.asusd.set_platform("ChangeThrottlePolicyOnBattery", True)

        self._pulse("auto_profile", write)

    # ------------------------------------------------------------ fan curves
    def load_fan_curves(self, mode: str) -> None:
        profile = _MODE_TO_PROFILE.get(mode)
        if profile is None:
            self.state.emit_message("error", tr("Bilinmeyen mod: {mode}", mode=mode))
            return
        self.state.emit_busy("fan_load", True)

        def done(curves: list[FanCurve]) -> None:
            self.state.emit_busy("fan_load", False)
            if curves:
                self._store_curves(mode, list(curves))
            else:
                self.state.emit_message("error", tr("Fan eğrileri okunamadı."))

        self.asusd.fetch_fan_curves(profile, done)

    def _store_curves(self, mode: str, curves: list[FanCurve]) -> None:
        keys = _CURVE_GROUP.get(mode, (mode,))
        for key in (mode, *[k for k in keys if k != mode]):   # requested mode first
            self.state.set_fan_curves(key, curves)

    def apply_fan_curve(self, mode: str, fan: str, points: list[tuple[int, int]]) -> None:
        profile = _MODE_TO_PROFILE.get(mode)
        if profile is None:
            self.state.emit_message("error", tr("Bilinmeyen mod: {mode}", mode=mode))
            return
        if len(points) != 8:
            self.state.emit_message("error", tr("Fan eğrisi tam olarak 8 nokta içermelidir."))
            return
        try:
            temps = [int(t) for t, _ in points]
            pcts = [int(p) for _, p in points]
        except (TypeError, ValueError):
            self.state.emit_message("error", tr("Fan eğrisi noktaları geçersiz."))
            return
        if any(b <= a for a, b in zip(temps, temps[1:])):
            self.state.emit_message("error", tr("Fan eğrisinde sıcaklıklar artan sırada olmalıdır."))
            return
        if not all(0 <= t <= 255 for t in temps) or not all(0 <= p <= 100 for p in pcts):
            self.state.emit_message("error", tr("Fan eğrisi değerleri aralık dışında."))
            return
        fan_u = fan.upper()
        cached = self.state.fan_curves.get(mode)
        old = next((c for c in cached if c.fan.upper() == fan_u), None) if cached else None
        # Keep the original raw pwm for every point whose percent was not edited (percent<->pwm is lossy:
        # 2 -> 1 % -> 3). Only edited points are converted.
        pwm = []
        for i, p in enumerate(pcts):
            if old is not None and len(old.pwm) == 8 and old.percent()[i] == p:
                pwm.append(old.pwm[i])
            else:
                pwm.append(round(p * 255 / 100))
        # Applying a curve intentionally ENABLES it (enabled=True): that is what the user expects from "Uygula".
        curve = FanCurve(fan_u, tuple(temps), tuple(pwm), True)
        self._pulse("fan", lambda: self.asusd.set_fan_curve(profile, curve))
        if cached:
            self._store_curves(mode, [curve if c.fan.upper() == fan_u else c for c in cached])

    def reset_fan_curves(self, mode: str) -> None:
        profile = _MODE_TO_PROFILE.get(mode)
        if profile is None:
            self.state.emit_message("error", tr("Bilinmeyen mod: {mode}", mode=mode))
            return
        self._pulse("fan", lambda: self.asusd.reset_fan_curves(profile))
        QTimer.singleShot(500, lambda: self.load_fan_curves(mode))

    # ------------------------------------------------------------- keyboard
    def _on_aura(self, name: str, value: Any) -> None:
        cur = self.state.aura
        if name == "Brightness":
            try:
                self.state.set_aura(AuraView(int(value), cur.color))
            except (TypeError, ValueError):
                pass
        elif name == "LedModeData":
            try:
                c = value[2]
                raw = (int(c[0]), int(c[1]), int(c[2]))
            except (TypeError, ValueError, IndexError):
                return
            # the keyboard gets linearised colours: show the colour we picked (exact) or the decoded value
            color = self._kbd_written.get(raw) or led_decode(raw)
            self.state.set_aura(AuraView(cur.brightness, color))

    def _on_aura_cached(self) -> None:
        getter = getattr(self.asusd, "get_aura_cached", None)
        if getter is None:
            return
        for n in ("Brightness", "LedModeData"):
            v = getter(n)
            if v is not None:
                self._on_aura(n, v)

    def set_kbd_brightness(self, level: int) -> None:
        level = max(0, min(3, int(level)))
        self._pulse("kbd", lambda: self.asusd.set_kbd_brightness(level))

    def toggle_kbd_light(self) -> None:
        """Keyboard backlight on/off; remembers the last non-zero level (default 2 = Med)."""
        cur = self.state.aura.brightness
        if cur is not None and cur > 0:
            self.settings.setValue(K_KBD_LAST, int(cur))
            self.set_kbd_brightness(0)
            return
        last = self.settings.value(K_KBD_LAST, 2, type=int)
        self.set_kbd_brightness(max(1, min(3, last)))

    def _send_kbd_color(self, rgb) -> None:
        """Static keyboard colour. LEDs are linear, UI colours sRGB -> linearise (VERIFIED visually: #FFD84D
        looked greenish raw, FF AF 13 matched)."""
        rgb = tuple(int(c) for c in rgb)
        raw = led_encode(rgb)
        self._kbd_written[raw] = rgb
        self._pulse("kbd", lambda: self.asusd.set_aura_static(raw))

    def set_kbd_color(self, rgb: tuple[int, int, int]) -> None:
        self._aura_last.pop("keyboard", None)
        self._send_kbd_color(rgb)

    # ----------------------------------------------------------- peripherals
    def _start_peripherals(self) -> None:
        if self.mouse is not None:
            self.mouse.changed.connect(self._on_mouse)
            self.mouse.error.connect(lambda m: self.state.emit_message("error", tr("Fare: {msg}", msg=m)))
            self.mouse.refresh()
            self.mouse.start_polling(30_000)
        if self.headset is not None:
            self.headset.changed.connect(self._on_headset)
            self.headset.error.connect(lambda m: self.state.emit_message("error", tr("Kulaklık: {msg}", msg=m)))
            self.headset.refresh()
            self.headset.start_polling(30_000)
        if self.ddc is not None:
            # No periodic polling: DDC/CI reads take seconds. Refreshed when the Devices window opens.
            self.ddc.changed.connect(self._on_monitor)
            self.ddc.error.connect(self._on_monitor_error)
        if self.state.aura_sync.enabled:
            self._aura_timer.start()

    def _on_mouse(self, st) -> None:
        self.state.set_peripheral("mouse", st)
        ready = bool(st.present and st.permission and not st.asleep)
        was, self._aura_ready["mouse"] = self._aura_ready["mouse"], ready
        if ready and not was:
            self._aura_last.pop("mouse", None)
            self._aura_apply("mouse")

    def _on_headset(self, st) -> None:
        self.state.set_peripheral("headset", st)
        ready = bool(st.present and st.permission and st.connected is True)
        was, self._aura_ready["headset"] = self._aura_ready["headset"], ready
        if ready and not was:
            self._aura_last.pop("headset", None)    # the headset may have forgotten its lighting while off
            self._aura_apply("headset")

    def _on_monitor(self, st) -> None:
        self.state.set_peripheral("monitor", st)
        self.state.emit_busy("monitor", False)

    def _on_monitor_error(self, msg: str) -> None:
        self.state.emit_message("error", tr("Monitör: {msg}", msg=msg))
        self.state.emit_busy("monitor", False)

    # ---- mouse
    def _mouse_call(self, name: str, *args) -> None:
        if self.mouse is None:
            return
        try:
            getattr(self.mouse, name)(*args)
        except Exception as exc:  # noqa: BLE001 - never let a device error reach the UI thread's caller
            log.exception("mouse %s failed", name)
            self.state.emit_message("error", tr("Fare: {msg}", msg=exc))

    def mouse_set_dpi(self, i: int, dpi: int) -> None:
        self._mouse_call("set_dpi_stage_value", int(i), int(dpi))

    def mouse_set_active_stage(self, stage: int) -> None:
        self._mouse_call("set_active_stage", int(stage))

    def mouse_set_polling(self, hz: int) -> None:
        self._mouse_call("set_polling", int(hz))

    def mouse_set_debounce(self, ms: int) -> None:
        self._mouse_call("set_debounce", int(ms))

    def mouse_set_angle_snapping(self, on: bool) -> None:
        self._mouse_call("set_angle_snapping", bool(on))

    def mouse_set_sleep(self, code: int) -> None:
        self._mouse_call("set_sleep", int(code))

    def mouse_set_led(self, mode: int, brightness: int, rgb) -> None:
        self._aura_last.pop("mouse", None)
        self._mouse_call("set_led", int(mode), max(0, min(100, int(brightness))), tuple(rgb), True)

    # ---- headset
    def headset_set_lighting(self, effect: int, brightness: int, rgb) -> None:
        if self.headset is None:
            return
        self._aura_last.pop("headset", None)
        try:
            self.headset.set_lighting(int(effect), max(0, min(100, int(brightness))), tuple(rgb))
        except Exception as exc:  # noqa: BLE001
            log.exception("headset set_lighting failed")
            self.state.emit_message("error", tr("Kulaklık: {msg}", msg=exc))

    # ---- monitor (DDC/CI)
    def refresh_monitor(self) -> None:
        """Read the monitor (takes seconds; busy key "monitor" is on until the result arrives)."""
        if self.ddc is None:
            return
        self.state.emit_busy("monitor", True)
        self.ddc.refresh()
        # failsafe: never leave the UI busy if the backend answers neither way
        QTimer.singleShot(MONITOR_BUSY_TIMEOUT_MS, lambda: self.state.emit_busy("monitor", False))

    def monitor_set(self, key: str, value: int) -> None:
        if self.ddc is None:
            return
        feat = DDC_FEATURES.get(key)
        if feat is None or feat.kind == "readonly":
            self.state.emit_message("error", tr("Monitör: {msg}", msg=key))
            return
        if feat.confirm:       # input source: only through monitor_set_input() after the UI's confirm dialog
            log.warning("monitor_set(%s) refused: needs the confirm path", key)
            self.state.emit_message("error", tr("Bu ayar onay gerektirir."))
            return
        if feat.kind == "range":
            self.ddc.set_value_debounced(key, int(value), 300)
        else:
            self.ddc.set_value(key, int(value))

    def monitor_set_input(self, value: int) -> None:
        """Input source switch. The UI MUST have shown the confirm dialog (it may blank this laptop's picture)."""
        if self.ddc is not None:
            self.ddc.set_value("input", int(value), confirmed=True)

    # ------------------------------------------------------------ Aura Sync
    def _load_aura_sync(self) -> AuraSyncView:
        g = self.settings.value
        d = AuraSyncView()
        effect = str(g(K_AURA + "effect", d.effect))
        c = str(g(K_AURA + "color", "")).lstrip("#")
        try:
            color = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)) if len(c) == 6 else d.color
        except ValueError:
            color = d.color
        raw_targets = g(K_AURA + "targets", None)
        if raw_targets is None:
            targets = set(d.targets)
        else:
            if isinstance(raw_targets, str):
                raw_targets = raw_targets.split(",")
            targets = {str(t) for t in raw_targets if str(t) in AURA_TARGETS}
        return AuraSyncView(
            enabled=g(K_AURA + "enabled", False, type=bool),
            effect=effect if effect in AURA_EFFECTS else d.effect,
            color=color,
            brightness=max(0, min(100, g(K_AURA + "brightness", d.brightness, type=int))),
            targets=targets)

    def _save_aura_sync(self, v: AuraSyncView) -> None:
        s = self.settings
        s.setValue(K_AURA + "enabled", v.enabled)
        s.setValue(K_AURA + "effect", v.effect)
        s.setValue(K_AURA + "color", "#{:02X}{:02X}{:02X}".format(*v.color))
        s.setValue(K_AURA + "brightness", v.brightness)
        s.setValue(K_AURA + "targets", ",".join(t for t in AURA_TARGETS if t in v.targets))

    def aura_sync_set(self, view: AuraSyncView) -> None:
        try:
            color = tuple(max(0, min(255, int(c))) for c in view.color)
            if len(color) != 3:
                raise ValueError
        except (TypeError, ValueError):
            self.state.emit_message("error", tr("Geçersiz renk."))
            return
        v = AuraSyncView(
            enabled=bool(view.enabled),
            effect=view.effect if view.effect in AURA_EFFECTS else "static",
            color=color,
            brightness=max(0, min(100, int(view.brightness))),
            targets={t for t in view.targets if t in AURA_TARGETS})
        if v.enabled and not self.state.aura_sync.enabled:
            self._aura_last.clear()          # switching on: every selected device gets the full state
        self._save_aura_sync(v)
        self.state.set_aura_sync(v)
        if v.enabled:
            self._aura_timer.start()          # debounce: slider drags must not hammer the devices
        else:
            self._aura_timer.stop()

    def _aura_flush(self) -> None:
        self._aura_apply(None)

    def _aura_target_ready(self, target: str) -> bool:
        if target == "keyboard":
            return True                       # built-in; asusd errors surface through the usual error path
        return self._aura_ready.get(target, False)

    def _device_lighting(self, target: str) -> tuple | None:
        """The lighting the device last reported, in the same shape as the Aura Sync params."""
        st = self.state.peripheral(target)
        if st is None:
            return None
        if target == "mouse":
            return (st.led_mode, st.led_brightness, st.led_rgb)
        return (st.light_effect, st.light_brightness, st.light_rgb)

    def _aura_apply(self, only: str | None) -> None:
        v = self.state.aura_sync
        if not v.enabled:
            return
        for t in AURA_TARGETS:
            if t not in v.targets or (only is not None and t != only) or not self._aura_target_ready(t):
                continue
            if t == "keyboard":
                # static colour only; brightness is never touched by Aura Sync
                params: tuple = (v.color,)
                if self._aura_last.get(t) == params:
                    continue
                self._aura_last[t] = params
                self._send_kbd_color(v.color)
            elif t == "mouse" and self.mouse is not None:
                params = (_AURA_MOUSE_MODE[v.effect], v.brightness, tuple(v.color))
                # the mouse keeps its lighting in flash: on every wake-up it already shows this -> no write
                if self._aura_last.get(t) == params or self._device_lighting(t) == params:
                    self._aura_last[t] = params
                    continue
                self._aura_last[t] = params
                self._mouse_call("set_led", params[0], v.brightness, tuple(v.color), True)
            elif t == "headset" and self.headset is not None:
                params = (_AURA_HEADSET_EFFECT[v.effect], v.brightness, tuple(v.color))
                if self._aura_last.get(t) == params or self._device_lighting(t) == params:
                    self._aura_last[t] = params
                    continue
                self._aura_last[t] = params
                try:
                    self.headset.set_lighting(params[0], v.brightness, tuple(v.color))
                except Exception as exc:  # noqa: BLE001
                    log.exception("headset aura sync failed")
                    self.state.emit_message("error", tr("Kulaklık: {msg}", msg=exc))
