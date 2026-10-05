"""Controller tests with fake backend clients (no real writes of any kind)."""
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QCoreApplication, QObject, QSettings, pyqtSignal

from rog_control.backend.dbus_util import Typed
from rog_control.backend.sensors import SensorSnapshot
from rog_control.backend.types import FanCurve, GfxMode, GfxPower, Profile
from rog_control.core.controller import Controller
from rog_control.core.state import AppState


@dataclass
class DS:
    connector: str = "eDP-1"
    current_hz: int = 60
    rates: list = field(default_factory=lambda: [60, 144, 240])


class FakeAsusd(QObject):
    platformChanged = pyqtSignal(str, object)
    auraChanged = pyqtSignal(str, object)
    error = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.cache = {}
        self.sets = []
        self.calls = []
        self.curves = []

    def get_cached(self, n):
        return self.cache.get(n)

    def get_aura_cached(self, n):
        return None

    def refresh(self):
        self.calls.append("refresh")

    def set_platform(self, name, value):
        self.sets.append((name, value))
        self.cache[name] = value
        self.platformChanged.emit(name, value)

    def fetch_fan_curves(self, profile, cb):
        self.calls.append(("fetch", profile))
        cb(self.curves)

    def set_fan_curve(self, profile, curve):
        self.calls.append(("set_curve", profile, curve))

    def reset_fan_curves(self, profile):
        self.calls.append(("reset", profile))

    def set_kbd_brightness(self, lvl):
        self.calls.append(("kbd", lvl))

    def set_aura_static(self, rgb):
        self.calls.append(("color", rgb))


class FakeGfx(QObject):
    modeChanged = pyqtSignal(int)
    powerChanged = pyqtSignal(int)
    pendingChanged = pyqtSignal(object, object)

    def __init__(self):
        super().__init__()
        self.mode = GfxMode.HYBRID
        self.power = GfxPower.SUSPENDED
        self.boot = GfxMode.HYBRID
        self.dgpu = False
        self.requests = []
        self.reply = (True, "ok")
        self.write_boot = True

    def refresh(self):
        pass

    def configured_boot_mode(self):
        return self.boot

    def dgpu_disabled(self):
        return self.dgpu

    def request_boot_mode(self, mode, cb):
        self.requests.append(mode)
        if self.reply[0] and self.write_boot:
            self.boot = mode
        cb(*self.reply)


class FakeSensors(QObject):
    updated = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.started = None

    def start(self, interval_ms=1000):
        self.started = interval_ms


class FakeDisplay(QObject):
    changed = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.sets = []
        self.st = DS()

    def refresh(self):
        self.changed.emit(self.st)

    def set_refresh(self, hz):
        self.sets.append(hz)
        self.st = DS(current_hz=hz, rates=self.st.rates)
        self.changed.emit(self.st)


class Env:
    def __init__(self, tmp_path, policy=None, custom_flag=False):
        self.settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        if custom_flag:
            self.settings.setValue("perf/custom_active", True)
        self.state = AppState()
        self.asusd, self.gfx = FakeAsusd(), FakeGfx()
        self.sensors, self.display = FakeSensors(), FakeDisplay()
        if policy is not None:
            self.asusd.cache["ThrottleThermalPolicy"] = int(policy)
        mux = tmp_path / "mux"
        mux.write_text("1\n")
        self.mux = mux
        self.dbus = MagicMock()
        self.ctl = Controller(self.state, self.asusd, self.gfx, self.sensors,
                              self.display, self.settings, mux_path=str(mux),
                              dbus_call=self.dbus)
        self.msgs, self.busy = [], []
        self.state.message.connect(lambda l, t: self.msgs.append((l, t)))
        self.state.busyChanged.connect(lambda k, b: self.busy.append((k, b)))

    def spin(self):
        QCoreApplication.processEvents()


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path, policy=Profile.BALANCED)


# ------------------------------------------------------------ mode derivation
@pytest.mark.parametrize("policy,mode", [
    (Profile.QUIET, "quiet"), (Profile.BALANCED, "balanced"), (Profile.PERFORMANCE, "turbo")])
def test_mode_from_policy(tmp_path, policy, mode):
    e = Env(tmp_path, policy=policy)
    e.ctl.start()
    assert e.state.perf_mode == mode
    assert e.sensors.started == 1000


def _cache_ppt(e, vals=(60, 90, 110)):
    for n, v in zip(("PptPl1Spl", "PptPl2Sppt", "PptFppt"), vals):
        e.asusd.cache[n] = v


def test_custom_persists_across_restart(tmp_path):
    e = Env(tmp_path, policy=Profile.PERFORMANCE, custom_flag=True)
    _cache_ppt(e)
    e.ctl.start()
    assert e.state.perf_mode == "custom"
    assert e.state.accent == "#F2A93B"


def test_custom_flag_ignored_when_policy_not_performance(tmp_path):
    e = Env(tmp_path, policy=Profile.QUIET, custom_flag=True)
    e.ctl.start()
    assert e.state.perf_mode == "quiet"
    assert e.settings.value("perf/custom_active", False, type=bool) is False


def test_external_fn_change_drops_custom(tmp_path):
    e = Env(tmp_path, policy=Profile.PERFORMANCE, custom_flag=True)
    e.ctl.start()
    e.asusd.platformChanged.emit("ThrottleThermalPolicy", int(Profile.QUIET))
    assert e.state.perf_mode == "quiet"
    e.asusd.platformChanged.emit("ThrottleThermalPolicy", int(Profile.PERFORMANCE))
    assert e.state.perf_mode == "turbo"  # custom info is gone
    assert e.settings.value("perf/custom_active", False, type=bool) is False


def test_platform_forwarded_and_battery_limit(env):
    env.ctl.start()
    env.asusd.platformChanged.emit("ChargeControlEndThreshold", 80)
    env.asusd.platformChanged.emit("PanelOd", True)
    assert env.state.battery_limit == 80
    assert env.state.platform["PanelOd"] is True


def test_set_turbo_from_custom_clears_flag(tmp_path):
    e = Env(tmp_path, policy=Profile.PERFORMANCE, custom_flag=True)
    e.ctl.start()
    e.ctl.set_perf_mode("turbo")
    assert e.state.perf_mode == "turbo"
    assert e.settings.value("perf/custom_active", False, type=bool) is False


# ---------------------------------------------------------------- custom write
def test_custom_write_order_and_clamp(env):
    env.ctl.start()
    env.settings.setValue("custom/pl1", 300)
    env.settings.setValue("custom/pl2", 10)
    env.settings.setValue("custom/fppt", 20)
    env.ctl.set_perf_mode("custom")
    assert env.asusd.sets == [
        ("ThrottleThermalPolicy", 1), ("PptPl1Spl", 170),
        ("PptPl2Sppt", 170), ("PptFppt", 170)]
    assert env.state.perf_mode == "custom"
    assert env.settings.value("perf/custom_active", False, type=bool) is True


def test_custom_defaults_and_ordering(env):
    env.ctl.start()
    env.ctl.set_perf_mode("custom")
    assert env.asusd.sets[1:] == [("PptPl1Spl", 60), ("PptPl2Sppt", 90), ("PptFppt", 110)]
    env.asusd.sets.clear()
    env.ctl.set_custom_limits(100, 80, 90)   # pl2<pl1, fppt<pl2 -> raised
    assert env.asusd.sets == [("PptPl1Spl", 100), ("PptPl2Sppt", 100), ("PptFppt", 100)]
    env.asusd.sets.clear()
    env.ctl.set_custom_limits(5, 50, 60)
    assert env.asusd.sets[0] == ("PptPl1Spl", 15)


def test_custom_limits_not_written_when_not_custom(env):
    env.ctl.start()
    env.ctl.set_custom_limits(50, 60, 70)
    assert env.asusd.sets == []
    assert env.ctl.custom_limits() == (50, 60, 70)


# ------------------------------------------------------------------------ GPU
def test_gfx_view_mapping(env):
    env.gfx.mode = GfxMode.INTEGRATED
    env.gfx.boot = GfxMode.HYBRID
    env.gfx.dgpu = True
    env.ctl.start()
    g = env.state.gfx
    assert (g.active, g.boot, g.pending) == ("eco", "standard", "standard")
    assert g.dgpu_disabled is True and g.mux_direct is False
    assert g.can_eco_exit is True and g.power == "sleep"


def test_gfx_no_pending_and_mux_direct(env):
    env.mux.write_text("0\n")
    env.gfx.mode = GfxMode.ASUS_MUX_DGPU
    env.gfx.boot = GfxMode.ASUS_MUX_DGPU
    env.ctl.start()
    assert env.state.gfx.active == "ultimate"
    assert env.state.gfx.pending is None
    assert env.state.gfx.mux_direct is True


def test_gfx_power_prefers_sensors(env):
    env.ctl.start()
    assert env.state.gfx.power == "sleep"
    env.sensors.updated.emit(SensorSnapshot(gpu_state="active"))
    assert env.state.gfx.power == "active"


def test_request_eco_success(env):
    env.ctl.start()
    env.ctl.request_gpu_mode("eco")
    assert env.gfx.requests == [GfxMode.INTEGRATED]
    assert env.state.gfx.pending == "eco"
    assert ("info", "Eco yeniden başlatınca etkin olacak.") in env.msgs
    assert env.busy == [("gpu", True), ("gpu", False)]


def test_eco_exit_success_requires_immediate_reboot(env):
    env.gfx.mode = GfxMode.INTEGRATED
    env.gfx.boot = GfxMode.INTEGRATED
    env.gfx.dgpu = True
    env.gfx.reply = (True, '{"ok": true, "eco_exit": true}')
    env.ctl.start()
    fired = []
    env.ctl.gpuRebootRequired.connect(lambda: fired.append(1))
    env.ctl.request_gpu_mode("standard")
    assert env.gfx.requests == [GfxMode.HYBRID]
    assert fired == [1]
    assert env.state.gfx.pending == "standard"
    lvl, text = env.msgs[-1]
    assert lvl == "info" and "ŞİMDİ" in text and "yeniden başlat" in text


def test_hybrid_to_eco_does_not_fire_reboot_signal(env):
    env.ctl.start()
    fired = []
    env.ctl.gpuRebootRequired.connect(lambda: fired.append(1))
    env.ctl.request_gpu_mode("eco")
    assert fired == []


@pytest.mark.parametrize("code,needle", [(7, "supergfxd durdurulamadı"), (8, "dGPU açılamadı")])
def test_eco_exit_error_codes(env, code, needle):
    env.gfx.mode = GfxMode.INTEGRATED
    env.gfx.boot = GfxMode.INTEGRATED
    env.gfx.reply = (False, "stderr")
    env.gfx.last_exit_code = code
    env.ctl.start()
    fired = []
    env.ctl.gpuRebootRequired.connect(lambda: fired.append(1))
    env.ctl.request_gpu_mode("standard")
    assert env.msgs[-1][0] == "error" and needle in env.msgs[-1][1]
    assert fired == []


def test_exit_code_fallback_from_text():
    from rog_control.core.controller import _helper_exit_code
    assert _helper_exit_code("x supergfxd durdurulamadı y") == 7
    assert _helper_exit_code("Eco'dan çıkış tamamlanamadı: z") == 8
    assert _helper_exit_code("helper exited with code 3") == 3


def test_request_exit4(env):
    env.gfx.reply = (False, "Ultimate (dGPU doğrudan) MUX modunda Eco kullanılamaz")
    env.ctl.start()
    env.ctl.request_gpu_mode("eco")
    assert env.msgs[-1][0] == "warn" and "MUX" in env.msgs[-1][1]


def test_request_other_error_has_stderr(env):
    env.gfx.reply = (False, "yazma hatası xyz")
    env.ctl.start()
    env.ctl.request_gpu_mode("eco")
    assert env.msgs[-1][0] == "error" and "yazma hatası xyz" in env.msgs[-1][1]


@pytest.mark.parametrize("mode", ["ultimate", "optimize"])
def test_unsupported_modes_make_no_call(env, mode):
    env.ctl.start()
    env.ctl.request_gpu_mode(mode)
    assert env.gfx.requests == []
    assert env.msgs[-1][0] == "warn" and "henüz desteklenmiyor" in env.msgs[-1][1]


def test_cancel_pending_requests_active_mode(env):
    env.gfx.mode = GfxMode.INTEGRATED
    env.gfx.boot = GfxMode.HYBRID
    env.ctl.start()
    assert env.state.gfx.pending == "standard"
    env.ctl.cancel_gpu_pending()
    assert env.gfx.requests == [GfxMode.INTEGRATED]
    assert env.state.gfx.pending is None


def test_reboot_now_calls_logind(env):
    env.ctl.reboot_now()
    args = env.dbus.call_args.args
    assert args[1:6] == ("org.freedesktop.login1", "/org/freedesktop/login1",
                         "org.freedesktop.login1.Manager", "Reboot", [Typed("b", False)])


# -------------------------------------------------------------------- refresh
def test_auto_refresh_follows_ac(env):
    env.ctl.start()
    env.ctl.set_refresh(None)
    assert env.state.display.auto is True
    env.sensors.updated.emit(SensorSnapshot(on_ac=True))
    assert env.display.sets == [240]
    env.sensors.updated.emit(SensorSnapshot(on_ac=True))
    assert env.display.sets == [240]       # no repeat
    env.sensors.updated.emit(SensorSnapshot(on_ac=False))
    assert env.display.sets == [240, 60]
    assert env.state.display.current_hz == 60


def test_auto_refresh_skips_when_already_current_and_missing_rate(env):
    env.display.st = DS(current_hz=240)
    env.ctl.start()
    env.ctl.set_refresh(None)
    env.sensors.updated.emit(SensorSnapshot(on_ac=True))
    assert env.display.sets == []
    env.display.st = DS(current_hz=144, rates=[48, 144])
    env.display.refresh()
    env.sensors.updated.emit(SensorSnapshot(on_ac=False))  # no 60 rate
    assert env.display.sets == []


def test_explicit_hz_disables_auto(env):
    env.ctl.start()
    env.ctl.set_refresh(None)
    env.ctl.set_refresh(144)
    assert env.display.sets == [144]
    assert env.state.display.auto is False
    assert env.settings.value("display/auto_refresh", True, type=bool) is False
    env.sensors.updated.emit(SensorSnapshot(on_ac=True))
    assert env.display.sets == [144]


def test_display_error_message_and_busy(env):
    env.ctl.start()
    env.ctl.set_refresh(144)
    env.display.error.emit("boom")
    # busy already ended on the changed signal of the fake; error still reported
    assert env.msgs[-1][0] == "error" and "boom" in env.msgs[-1][1]


# ------------------------------------------------------------------ fan curves
def points(pcts, start=30, step=10):
    return [(start + i * step, p) for i, p in enumerate(pcts)]


def test_apply_fan_curve_percent_to_pwm(env):
    env.ctl.start()
    env.ctl.apply_fan_curve("custom", "cpu", points([0, 10, 20, 40, 50, 70, 90, 100]))
    _, profile, curve = env.asusd.calls[-1]
    assert profile == Profile.PERFORMANCE
    assert curve.fan == "CPU" and curve.enabled is True
    assert curve.pwm == (0, 26, 51, 102, 128, 178, 230, 255)
    assert curve.temps == (30, 40, 50, 60, 70, 80, 90, 100)


@pytest.mark.parametrize("pts", [
    [(30, 10)] * 8,
    points([10] * 7),
    [(30, 10), (40, 20), (50, 30), (45, 40), (60, 50), (70, 60), (80, 70), (90, 80)],
    points([10, 20, 30, 40, 50, 60, 70, 120]),
])
def test_invalid_fan_curve_rejected(env, pts):
    env.ctl.start()
    env.ctl.apply_fan_curve("quiet", "GPU", pts)
    assert env.msgs[-1][0] == "error"
    assert not any(c[0] == "set_curve" for c in env.asusd.calls if isinstance(c, tuple))


def test_load_fan_curves_and_profile_map(env):
    env.asusd.curves = [FanCurve("CPU", (30,) * 8, (0,) * 8, True)]
    env.ctl.start()
    got = []
    env.state.fanCurvesChanged.connect(lambda m, c: got.append((m, c)))
    env.ctl.load_fan_curves("custom")
    assert ("fetch", Profile.PERFORMANCE) in env.asusd.calls
    assert got[0][0] == "custom" and got[0][1] == env.asusd.curves
    env.ctl.load_fan_curves("quiet")
    assert ("fetch", Profile.QUIET) in env.asusd.calls


# ------------------------------------------------------------------------- EPP
@pytest.mark.parametrize("mode,prop", [
    ("quiet", "ThrottleQuietEpp"), ("balanced", "ThrottleBalancedEpp"),
    ("turbo", "ThrottlePerformanceEpp"), ("custom", "ThrottlePerformanceEpp")])
def test_epp_routing(env, mode, prop):
    env.ctl.start()
    env.ctl.set_epp(mode, 3)
    assert env.asusd.sets == [(prop, 3)]


def test_auto_profile(env):
    env.ctl.start()
    env.ctl.set_auto_profile("turbo", "quiet")
    assert env.asusd.sets == [("ThrottlePolicyOnAc", 1), ("ThrottlePolicyOnBattery", 2),
                              ("ChangeThrottlePolicyOnAc", True),
                              ("ChangeThrottlePolicyOnBattery", True)]


def test_battery_limit_clamped(env):
    env.ctl.start()
    env.ctl.set_battery_limit(5)
    assert env.asusd.sets == [("ChargeControlEndThreshold", 20)]


# ------------------------------------------------------------------ busy/error
def test_busy_pairing(env):
    env.ctl.start()
    env.ctl.set_panel_od(True)
    env.ctl.set_perf_mode("quiet")
    env.ctl.set_kbd_brightness(2)
    env.spin()
    for key in ("panel_od", "perf", "kbd"):
        seq = [b for k, b in env.busy if k == key]
        assert seq == [True, False], key


def test_asusd_error_becomes_turkish_message(env):
    env.ctl.start()
    env.asusd.error.emit("set_platform:PanelOd", "denied")
    level, text = env.msgs[-1]
    assert level == "error" and "denied" in text and "asusd" in text


def test_sensors_forwarded(env):
    env.ctl.start()
    snap = SensorSnapshot(battery_power_w=12.5, on_ac=False)
    env.sensors.updated.emit(snap)
    assert env.state.sensors is snap
    assert env.state.sensors.battery_power_w == 12.5


def test_aura_state(env):
    env.ctl.start()
    env.asusd.auraChanged.emit("Brightness", 2)
    env.asusd.auraChanged.emit("LedModeData", (0, 0, (1, 2, 3), (0, 0, 0), 235, 0))
    assert env.state.aura.brightness == 2 and env.state.aura.color == (1, 2, 3)


# ------------------------------------------------- helper exit code (orchestrator fix)
@pytest.mark.parametrize("code,level,needle", [
    (126, "info", "iptal"),            # user dismissed the pkexec dialog
    (127, "error", "install.sh"),      # not authorised / helper missing
    (7, "error", "supergfxd"),
    (8, "error", "Eco'dan çıkış tamamlanamadı"),
    (4, "warn", "MUX"),
])
def test_gpu_exit_code_from_last_exit_code(env, code, level, needle):
    # The message text is deliberately unrelated: the code must come from
    # gfx.last_exit_code, not from parsing the text.
    env.gfx.reply = (False, "some unrelated stderr text")
    env.gfx.last_exit_code = code
    env.ctl.start()
    env.ctl.request_gpu_mode("eco")
    lvl, text = env.msgs[-1]
    assert lvl == level and needle in text


# ======================================================== review regressions
def test_bug4a_leaving_custom_for_turbo_bounces_through_balanced(tmp_path):
    e = Env(tmp_path, policy=Profile.PERFORMANCE, custom_flag=True)
    _cache_ppt(e)
    e.ctl.start()
    assert e.state.perf_mode == "custom"
    e.ctl.set_perf_mode("turbo")
    assert e.asusd.sets == [("ThrottleThermalPolicy", 0), ("ThrottleThermalPolicy", 1)]
    assert e.state.perf_mode == "turbo"
    assert e.settings.value("perf/custom_active", False, type=bool) is False


def test_bug4a_leaving_custom_for_balanced_writes_only_target(tmp_path):
    e = Env(tmp_path, policy=Profile.PERFORMANCE, custom_flag=True)
    _cache_ppt(e)
    e.ctl.start()
    e.ctl.set_perf_mode("balanced")
    assert e.asusd.sets == [("ThrottleThermalPolicy", 0)]


def test_bug4b_startup_custom_requires_matching_ppt(tmp_path):
    e = Env(tmp_path, policy=Profile.PERFORMANCE, custom_flag=True)
    _cache_ppt(e, (5, 5, 5))             # firmware changed them behind our back
    e.ctl.start()
    assert e.state.perf_mode == "turbo"
    assert e.settings.value("perf/custom_active", False, type=bool) is False


def test_bug4b_startup_custom_waits_for_ppt_values(tmp_path):
    e = Env(tmp_path, policy=Profile.PERFORMANCE, custom_flag=True)
    e.ctl.start()
    assert e.state.perf_mode == "turbo"          # not confirmed yet
    for n, v in zip(("PptPl1Spl", "PptPl2Sppt", "PptFppt"), (60, 90, 110)):
        e.asusd.platformChanged.emit(n, v)
    assert e.state.perf_mode == "custom"


def test_bug4c_flag_not_set_when_policy_write_raises(env, monkeypatch):
    env.ctl.start()

    def boom(name, value):
        raise RuntimeError("dbus down")
    monkeypatch.setattr(env.asusd, "set_platform", boom)
    env.ctl.set_perf_mode("custom")
    assert env.settings.value("perf/custom_active", False, type=bool) is False
    assert env.state.perf_mode == "balanced"


def test_bug4c_asusd_error_clears_custom_flag(env):
    env.ctl.start()
    env.ctl.set_perf_mode("custom")
    assert env.state.perf_mode == "custom"
    env.asusd.error.emit("set_platform:ThrottleThermalPolicy", "denied")
    assert env.settings.value("perf/custom_active", False, type=bool) is False
    assert env.state.perf_mode == "turbo"        # policy is PERFORMANCE, custom no longer claimed


def test_bug5_persisted_auto_refresh_does_not_write_at_startup(tmp_path):
    e = Env(tmp_path, policy=Profile.BALANCED)
    e.settings.setValue("display/auto_refresh", True)
    e = Env(tmp_path, policy=Profile.BALANCED)
    e.ctl.start()
    e.sensors.updated.emit(SensorSnapshot(on_ac=True))     # first snapshot only records
    assert e.display.sets == []
    e.sensors.updated.emit(SensorSnapshot(on_ac=True))
    assert e.display.sets == []
    e.sensors.updated.emit(SensorSnapshot(on_ac=False))    # real transition
    assert e.display.sets == [60] or e.display.sets == []  # 60 is current in DS -> nothing to write
    e.display.st = DS(current_hz=144)
    e.sensors.updated.emit(SensorSnapshot(on_ac=True))
    assert e.display.sets[-1] == 240


def test_bug5_auto_uses_fresh_display_state(env, monkeypatch):
    env.ctl.start()                                   # cached display state: 60 Hz
    env.ctl.set_refresh(None)
    env.sensors.updated.emit(SensorSnapshot(on_ac=False))
    env.display.sets.clear()
    fresh = DS(current_hz=240)                        # panel changed behind our back, no signal yet
    monkeypatch.setattr(env.display, "refresh", lambda: env.display.changed.emit(fresh))
    env.sensors.updated.emit(SensorSnapshot(on_ac=True))   # target 240 == fresh current -> no write
    assert env.display.sets == []


def test_bug6_shared_performance_curves_cache(env):
    env.asusd.curves = [FanCurve("CPU", (30,) * 8, (0,) * 8, True)]
    env.ctl.start()
    got = []
    env.state.fanCurvesChanged.connect(lambda m, c: got.append(m))
    env.ctl.load_fan_curves("custom")
    assert set(got) == {"custom", "turbo"}
    assert env.state.fan_curves["turbo"] == env.state.fan_curves["custom"]
    got.clear()
    env.ctl.apply_fan_curve("turbo", "CPU", points([0, 10, 20, 40, 50, 70, 90, 100]))
    assert set(got) == {"custom", "turbo"}
    assert env.state.fan_curves["custom"][0].pwm == env.state.fan_curves["turbo"][0].pwm
    got.clear()
    env.ctl.load_fan_curves("quiet")
    assert got == ["quiet"]


def test_bug3_untouched_points_keep_raw_pwm(env):
    pwm = (2, 25, 38, 51, 63, 81, 99, 117)
    temps = (30, 40, 50, 60, 70, 80, 90, 100)
    env.asusd.curves = [FanCurve("CPU", temps, pwm, False)]
    env.ctl.start()
    env.ctl.load_fan_curves("balanced")
    pts = list(zip(temps, FanCurve("CPU", temps, pwm, False).percent()))
    env.ctl.apply_fan_curve("balanced", "CPU", pts)
    curve = env.asusd.calls[-1][2]
    assert curve.pwm == pwm and curve.temps == temps
    assert curve.enabled is True                    # applying intentionally enables the curve
    # edit one point only
    pts2 = list(pts)
    pts2[3] = (pts2[3][0], 60)
    env.ctl.apply_fan_curve("balanced", "CPU", pts2)
    c2 = env.asusd.calls[-1][2]
    assert c2.pwm[:3] == pwm[:3] and c2.pwm[4:] == pwm[4:] and c2.pwm[3] == round(60 * 255 / 100)


def test_bug7_set_custom_limits_clamps_and_reports(env):
    env.ctl.start()
    env.ctl.set_custom_limits(100, 80, 90)
    assert env.ctl.custom_limits() == (100, 100, 100)


# --------------------------------------------- battery profile at startup (power fix)
def _platform(env, **props):
    for k, v in props.items():
        env.asusd.platformChanged.emit(k, v)


def test_started_on_battery_applies_battery_profile_once(tmp_path):
    e = Env(tmp_path, policy=Profile.BALANCED)
    e.ctl.start()
    _platform(e, ThrottleThermalPolicy=int(Profile.BALANCED), ThrottlePolicyOnBattery=int(Profile.QUIET),
              ChangeThrottlePolicyOnBattery=True)
    e.sensors.updated.emit(SensorSnapshot(on_ac=False))
    assert ("ThrottleThermalPolicy", int(Profile.QUIET)) in e.asusd.sets
    n = len(e.asusd.sets)
    e.sensors.updated.emit(SensorSnapshot(on_ac=False))      # later snapshots: no more writes
    _platform(e, ThrottleThermalPolicy=int(Profile.PERFORMANCE))  # user picks Turbo manually
    e.sensors.updated.emit(SensorSnapshot(on_ac=False))
    assert len(e.asusd.sets) == n


@pytest.mark.parametrize("on_ac,change,cur", [
    (True, True, Profile.BALANCED),     # started on AC: nothing
    (False, False, Profile.BALANCED),   # auto-switch disabled by the user: nothing
    (False, True, Profile.QUIET),       # already in the battery profile: nothing
])
def test_battery_profile_not_applied(tmp_path, on_ac, change, cur):
    e = Env(tmp_path, policy=cur)
    e.ctl.start()
    _platform(e, ThrottleThermalPolicy=int(cur), ThrottlePolicyOnBattery=int(Profile.QUIET),
              ChangeThrottlePolicyOnBattery=change)
    e.sensors.updated.emit(SensorSnapshot(on_ac=on_ac))
    assert not any(k == "ThrottleThermalPolicy" for k, _ in e.asusd.sets)
