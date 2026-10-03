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
from .state import AppState, AuraView, DisplayView, GfxView

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

    def __init__(
        self,
        state: AppState,
        asusd,
        gfx,
        sensors,
        display,
        settings: QSettings,
        *,
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
        self.mux_path = mux_path
        self._dbus_call = dbus_call or dbus_util.async_call
        self._started = False

        self._policy: Profile | None = None
        self._custom_flag = settings.value(K_CUSTOM_ACTIVE, False, type=bool)
        self._auto_refresh = settings.value(K_AUTO_REFRESH, False, type=bool)
        self._auto_pending = False           # auto-refresh wants to apply once a fresh display state arrives
        self._on_ac: bool | None = None
        self._display_state: Any = None
        self._refresh_busy = False
        # A persisted custom flag is only trusted once the firmware state confirms it (policy PERFORMANCE and the
        # cached Ppt* values equal custom_limits()); until then the mode is derived as turbo.
        self._startup_pending = self._custom_flag
        self._seen: dict[str, Any] = {}      # last value seen per platform property
        self.state.set_display(DisplayView(auto=self._auto_refresh))

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
        boot_mode = self.gfx.configured_boot_mode()
        boot = _GFX_TO_VIEW.get(boot_mode) if boot_mode is not None else None
        pending = boot if (boot is not None and active is not None and boot != active) else None
        snap = self.state.sensors
        if snap is not None and getattr(snap, "gpu_state", "unknown") != "unknown":
            power = snap.gpu_state
        else:
            gp = getattr(self.gfx, "power", None)
            power = _POWER_TO_STR.get(gp, "unknown") if gp is not None else "unknown"
        self.state.set_gfx(GfxView(
            active=active, boot=boot, pending=pending, power=power,
            dgpu_disabled=self.gfx.dgpu_disabled(),
            mux_direct=self._read_mux_direct(),
            can_eco_exit=True,
        ))

    def request_gpu_mode(self, mode: str) -> None:
        if mode not in _VIEW_TO_GFX:
            self.state.emit_message("warn", tr("Bu GPU modu henüz desteklenmiyor."))
            return
        self._request_boot(_VIEW_TO_GFX[mode], mode, cancel=False)

    def cancel_gpu_pending(self) -> None:
        active = self.state.gfx.active
        if active not in _VIEW_TO_GFX:
            self.state.emit_message("warn", tr("Bekleyen değişiklik iptal edilemedi: "
                                       "etkin GPU modu bilinmiyor veya desteklenmiyor."))
            return
        self._request_boot(_VIEW_TO_GFX[active], active, cancel=True)

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
            # The first snapshot only records on_ac (no write at startup); act on a later TRANSITION, or when
            # the user explicitly enabled auto and is still waiting for a first on_ac value.
            if self._auto_refresh and (self._auto_pending or (prev is not None and prev != self._on_ac)):
                self._request_auto_refresh()
        # sensors may refine the GPU power string
        cur = self.state.gfx.power
        gs = getattr(snap, "gpu_state", "unknown")
        if gs != "unknown" and gs != cur:
            self._rebuild_gfx()

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
                color = (int(c[0]), int(c[1]), int(c[2]))
            except (TypeError, ValueError, IndexError):
                return
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

    def set_kbd_color(self, rgb: tuple[int, int, int]) -> None:
        self._pulse("kbd", lambda: self.asusd.set_aura_static(tuple(rgb)))
