"""Window tests run against the fakes (no hardware, no real system writes)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication

from rog_control.app import SingleInstance, parse_args
from rog_control.backend.types import FanCurve
from rog_control.ui import theme
from rog_control.ui.windows import dialogs
from rog_control.ui.windows._fake import FakeController, FakeState, fake_sensors
from rog_control.ui.windows.fans_window import FansWindow
from rog_control.ui.windows.keyboard_window import KeyboardWindow
from rog_control.ui.windows.main_window import MainWindow
from rog_control.ui.windows.mini_window import MiniWindow
from rog_control.ui.windows.settings_window import SettingsWindow, autostart_enabled, set_autostart
from rog_control.ui.windows.tray import Tray


@pytest.fixture
def env(tmp_path):
    st = FakeState("balanced")
    ctl = FakeController(st)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    return st, ctl, settings


def pump():
    QApplication.processEvents()


def test_main_window_fits_without_scroll(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    w.show()
    pump()
    assert (w.width(), w.height()) == (480, 920)
    assert w.layout().sizeHint().height() <= 920
    st.set_gfx(boot="eco", pending="eco", active="standard")  # tallest state
    pump()
    assert w.layout().sizeHint().height() <= 920


def test_perf_click_and_state_signals(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    w.show()
    w.perf_row.clicked.emit("turbo")
    assert ("set_perf_mode", ("turbo",)) in ctl.calls
    assert w.perf_row.selected() == "turbo"           # fake controller updated state -> window reacted
    assert w.pill.text() == "Turbo"
    assert w._accent == "#FF5A5F"
    assert "agresif" in w.perf_desc.text()
    st.set_perf_mode("quiet")                          # external change
    assert w.perf_row.selected() == "quiet" and w.pill.text() == "Sessiz"


def test_header_auto_policy_labels(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    assert "Turbo" in w.perf_header._value.text() and "Sessiz" in w.perf_header._value.text()
    st.set_platform_value("ThrottlePolicyOnBattery", 0)
    assert "Dengeli" in w.perf_header._value.text()


def test_accent_propagates(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    st.set_perf_mode("custom")
    for child in (w.perf_row, w.od, w.bat_slider, w.sensor):
        assert child.accent == "#F2A93B"


def test_gfx_pending_card_and_banner(env, monkeypatch):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    w.show()
    assert w.pending.isHidden() and w.banner.isHidden()
    st.set_gfx(boot="eco", pending="eco")
    assert not w.pending.isHidden()
    assert w.gpu_row.pending() == "eco" and w.gpu_row.selected() == "standard"
    # reboot -> confirm -> controller
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    w.pending.rebootClicked.emit()
    assert ctl.rebooted
    w.pending.cancelClicked.emit()
    assert "cancel_gpu_pending" in ctl.names()
    assert w.pending.isHidden()
    # dual-boot leftover banner
    st.set_gfx(active="eco", boot="standard", dgpu_disabled=True, pending=None)
    assert not w.banner.isHidden()
    st.set_gfx(boot="eco")
    assert w.banner.isHidden()


def test_gpu_click_confirms_then_requests(env, monkeypatch):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    asked = []
    monkeypatch.setattr(dialogs, "ask", lambda parent, title, text, *a, **k: asked.append((title, text)) or False)
    w.gpu_row.clicked.emit("eco")
    assert asked and "yeniden başlat" in asked[0][1]
    assert "request_gpu_mode" not in ctl.names()        # declined
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    w.gpu_row.clicked.emit("eco")
    assert ("request_gpu_mode", ("eco",)) in ctl.calls


def test_ultimate_optimize_disabled(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    for k in ("ultimate", "optimize"):
        assert not w.gpu_row.is_enabled(k)
        assert w.gpu_row.tile(k).toolTip() == "Henüz desteklenmiyor"


def test_busy_disables_controls(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    st.emit_busy("perf", True)
    assert not w.perf_row.isEnabled()
    st.emit_busy("perf", False)
    assert w.perf_row.isEnabled()
    for key, widget in (("refresh", w.hz_seg), ("panel_od", w.od), ("battery", w.bat_slider), ("gpu", w.gpu_row)):
        st.emit_busy(key, True)
        assert not widget.isEnabled(), key
        st.emit_busy(key, False)
        assert widget.isEnabled(), key
    assert not w.gpu_row.is_enabled("ultimate")          # still unsupported after busy cycle


def test_display_battery_od_controls(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    assert w.hz_seg.current() == "auto"
    w.hz_seg.set_current("120", emit=True)
    assert ("set_refresh", (120,)) in ctl.calls and w.hz_seg.current() == "120"
    w.hz_seg.set_current("auto", emit=True)
    assert ("set_refresh", (None,)) in ctl.calls
    w.od.setChecked(False, emit=True)
    assert ("set_panel_od", (False,)) in ctl.calls
    w.bat_seg.set_current("60", emit=True)
    assert ("set_battery_limit", (60,)) in ctl.calls and w.bat_slider.value() == 60
    w.bat_slider.committed.emit(75)
    assert ("set_battery_limit", (75,)) in ctl.calls


def test_toast_levels(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    w.show()
    st.emit_message("info", "Kaydedildi")
    assert w.toast.isVisible() and w.toast._timer.isActive()
    st.emit_message("error", "Hata oldu")
    assert w.toast.isVisible() and not w.toast._timer.isActive()   # errors stay until clicked
    w.toast.hide()
    st.emit_message("warn", "Dikkat")
    assert w.toast.isVisible() and "Dikkat" in w.toast._lab.text()


def test_close_hides_to_tray_or_quits(env, monkeypatch):
    st, ctl, settings = env
    quits = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quits.append(1)))
    w = MainWindow(st, ctl, settings, tray_available=lambda: True)
    w.show()
    w.close()
    assert not w.isVisible() and not quits
    w2 = MainWindow(st, ctl, settings, tray_available=lambda: False)
    w2.show()
    w2.close()
    assert quits


def test_fans_profile_switch_requests_curves(env):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    w.show()
    pump()
    assert ("load_fan_curves", ("balanced",)) in ctl.calls
    w.profile_btns["turbo"].click()
    assert ("load_fan_curves", ("turbo",)) in ctl.calls
    assert w.edit_mode == "turbo" and w.profile_btns["turbo"].is_selected()
    pts = w.chart.points()
    assert len(pts) == 8 and pts[-1][0] == 81            # turbo CPU curve
    # independent of the active mode
    assert st.perf_mode == "balanced"


def test_fans_curve_apply_default_and_tabs(env):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    w.show()
    w.fan_seg.set_current("GPU", emit=True)
    assert w.chart.points()[1][0] == 60
    w.btn_apply.click()
    name, args = ctl.calls[-1]
    assert name == "apply_fan_curve" and args[0] == "balanced" and args[1] == "GPU" and len(args[2]) == 8
    w.btn_default.click()
    assert ("reset_fan_curves", ("balanced",)) in ctl.calls
    # live data from the controller replaces the chart
    new = FanCurve("GPU", (30, 40, 50, 60, 70, 80, 90, 100), (0, 10, 20, 30, 40, 50, 60, 255), True)
    st.fanCurvesChanged.emit("balanced", [new])
    assert w.chart.points()[0] == (30, 0) and w.chart.points()[-1] == (100, 100)


def test_fans_power_limits_only_on_custom(env):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    assert w.limit_stack.currentIndex() == 1 and w.limit_badge.text() == "Firmware"
    assert all(not s.isEnabled() for s in w.pl_sliders)
    w.btn_goto_custom.click()
    assert w.limit_stack.currentIndex() == 0 and w.limit_badge.text() == "Özel"
    assert all(s.isEnabled() for s in w.pl_sliders)
    w.pl_sliders[0].setValue(70)
    w.pl_sliders[0].committed.emit(70)
    assert ("set_custom_limits", (70, 90, 110)) in ctl.calls
    st.emit_busy("perf", True)
    assert all(not s.isEnabled() for s in w.pl_sliders)


def test_fans_epp_nv_auto(env):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    assert w.epp_seg.current() == "balance_power"        # balanced EPP = 3
    w.epp_seg.set_current("power", emit=True)
    assert ("set_epp", ("balanced", 4)) in ctl.calls
    w.nv_boost.committed.emit(12)
    w.nv_temp.committed.emit(80)
    assert ("set_nv_boost", (12,)) in ctl.calls and ("set_nv_temp_target", (80,)) in ctl.calls
    w.chip_ac.click()                                    # turbo -> quiet (cycle)
    assert ctl.calls[-1] == ("set_auto_profile", ("quiet", "quiet"))
    w.chip_bat.click()                                   # quiet -> balanced
    assert ctl.calls[-1] == ("set_auto_profile", ("quiet", "balanced"))
    st.emit_busy("epp", True)
    assert not w.epp_seg.isEnabled()
    st.emit_busy("auto", True)
    assert not w.chip_ac.isEnabled()
    st.emit_busy("fan", True)
    assert not w.btn_apply.isEnabled()


def test_fans_temp_line_and_rpm_suffix(env):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    st.set_sensors(fake_sensors(cpu_temp=66.0, fans_rpm={"cpu": 3100, "gpu": 2000, "mid": 4000}))
    assert w.chart._cur_temp == 66.0
    assert "3100" in w.temp_lbl.text()


def test_keyboard_window(env):
    st, ctl, settings = env
    w = KeyboardWindow(st, ctl)
    assert w.bright.current() == "2"
    w.bright.set_current("3", emit=True)
    assert ("set_kbd_brightness", (3,)) in ctl.calls
    w.hex.setText("#ff0000")
    w.apply_btn.click()
    assert ctl.calls[-1] == ("set_kbd_color", ((255, 0, 0),))
    w.hex.setText("zzz")
    assert not w.apply_btn.isEnabled()
    w.swatches[5].clicked.emit(w.swatches[5].color)
    assert ctl.calls[-1][0] == "set_kbd_color"
    st.emit_busy("kbd", True)
    assert not w.bright.isEnabled()


def test_settings_autostart_file(env, tmp_path, monkeypatch):
    st, ctl, settings = env
    path = tmp_path / "autostart" / "rog-control.desktop"
    root = tmp_path / "proj"
    monkeypatch.setattr("rog_control.ui.windows.settings_window._launcher", lambda: None)
    w = SettingsWindow(st, ctl, settings, autostart_path=path, project_root=root)
    assert not path.exists()
    w.sw_autostart.setChecked(True, emit=True)
    text = path.read_text()
    assert "Exec=python3 -m rog_control --minimized" in text and f"Path={root}" in text
    w.sw_autostart.setChecked(False, emit=True)
    assert not path.exists()
    w.sw_tray.setChecked(False, emit=True)
    w.sw_notify.setChecked(False, emit=True)
    assert settings.value("ui/minimize_to_tray", True, type=bool) is False
    assert settings.value("ui/notify_profile", True, type=bool) is False
    set_autostart(path, False)                          # removing a missing file is fine
    assert not autostart_enabled(path)


def test_autostart_uses_launcher_when_installed(tmp_path):
    path = tmp_path / "a.desktop"
    set_autostart(path, True, tmp_path / "proj", launcher="/x/rog-control")
    text = path.read_text()
    assert "Exec=rog-control --minimized" in text and "Path=" not in text and "python3" not in text


def test_mini_window(env):
    st, ctl, settings = env
    w = MiniWindow(st, ctl)
    assert w.perf_lbl.text() == "Dengeli" and "Standart" in w.gpu_lbl.text()
    assert w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    w.buttons["turbo"].click()
    assert ("set_perf_mode", ("turbo",)) in ctl.calls and w.perf_lbl.text() == "Turbo"
    assert "48" in w.vals["CPU"].text() and w.vals["GPU"].text() == "Uyku"


def test_tray_menu_and_notification(env, monkeypatch):
    st, ctl, settings = env
    t = Tray(st, ctl, settings)
    assert t.perf_actions["balanced"].isChecked()
    t.perf_actions["turbo"].trigger()
    assert ("set_perf_mode", ("turbo",)) in ctl.calls and t.perf_actions["turbo"].isChecked()
    assert "CPU 48" in t.info.text() and "CPU 48" in t.icon.toolTip()
    shown = []
    monkeypatch.setattr(t.icon, "isVisible", lambda: True)
    monkeypatch.setattr(t.icon, "showMessage", lambda *a, **k: shown.append(a))
    import rog_control.ui.windows.tray as tray_mod
    monkeypatch.setattr(tray_mod, "seconds_since_local_perf", lambda: 99.0)   # as if the Fn key changed it
    st.set_perf_mode("quiet")
    assert shown and "Sessiz" in shown[0][1]
    settings.setValue("ui/notify_profile", False)
    st.set_perf_mode("balanced")
    assert len(shown) == 1
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    t.gpu_actions["eco"].trigger()
    assert ("request_gpu_mode", ("eco",)) in ctl.calls


def test_single_instance_roundtrip():
    name = f"rog-control-test-{__import__('os').getpid()}"
    first = SingleInstance(name)
    assert not first.notify_existing(100)                 # nobody listening yet
    assert first.listen()
    hits = []
    first.activated.connect(lambda: hits.append(1))
    second = SingleInstance(name)
    assert second.notify_existing(1000)
    for _ in range(50):
        pump()
        if hits:
            break
    assert hits
    first.close()


def test_parse_args():
    a = parse_args(["--minimized", "--fake"])
    assert a.minimized and a.fake and not a.verbose
    assert not parse_args([]).minimized


def test_app_exits_1_without_core(monkeypatch):
    import builtins
    import rog_control.app as app_mod
    real = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "rog_control.core.controller":
            raise ImportError("missing")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert app_mod._build_real(None) is None


def test_busy_aliases_map_controller_keys():
    # The real Controller emits these keys; windows group them under UI keys.
    from rog_control.ui.windows._base import BUSY_ALIASES, BUSY_KEYS
    for real, ui in BUSY_ALIASES.items():
        assert ui in BUSY_KEYS


def test_secondary_window_accepts_close_while_quitting(qtbot):
    # Qt 6 aborts QApplication.quit() if any window ignores its close event;
    # secondary windows must accept close once the app is quitting.
    from PyQt6.QtGui import QCloseEvent
    from PyQt6.QtWidgets import QApplication
    from rog_control.ui.windows._fake import FakeController, FakeState
    from rog_control.ui.windows.fans_window import FansWindow
    st = FakeState(); w = FansWindow(st, FakeController(st)); qtbot.addWidget(w)
    app = QApplication.instance()
    app.setProperty("rog_quitting", False)
    ev = QCloseEvent(); w.closeEvent(ev)
    assert not ev.isAccepted()            # normal: close = go back to main window
    app.setProperty("rog_quitting", True)
    try:
        ev = QCloseEvent(); w.closeEvent(ev)
        assert ev.isAccepted()            # quitting: must not block quit
    finally:
        app.setProperty("rog_quitting", False)


# ---- review regressions -------------------------------------------------------
def test_battery_slider_not_touched_by_sensor_tick_or_drag(env, qtbot):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    qtbot.addWidget(w)
    w.show()
    assert w.bat_slider.value() == 80
    w.bat_slider.setValue(60)                    # user position (not yet committed)
    st.set_sensors(fake_sensors())               # 1 Hz tick must not reset it
    assert w.bat_slider.value() == 60
    w.bat_slider.slider().setSliderDown(True)
    st.set_battery_limit(90)                     # hardware event during a drag is not applied
    assert w.bat_slider.value() == 60
    w.bat_slider.slider().setSliderDown(False)
    st.set_battery_limit(95)
    assert w.bat_slider.value() == 95


def test_nv_sliders_only_follow_their_own_property(env, qtbot):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    qtbot.addWidget(w)
    w.nv_boost.setValue(20)                      # user dragging, not committed
    st.set_platform_value("PanelOd", False)      # unrelated change
    st.set_platform_value("ThrottlePolicyOnAc", 0)
    assert w.nv_boost.value() == 20
    st.set_platform_value("NvTempTarget", 80)
    assert w.nv_boost.value() == 20 and w.nv_temp.value() == 80
    w.nv_boost.slider().setSliderDown(True)
    st.set_platform_value("NvDynamicBoost", 8)
    assert w.nv_boost.value() == 20
    w.nv_boost.slider().setSliderDown(False)
    st.set_platform_value("NvDynamicBoost", 8)
    assert w.nv_boost.value() == 8


def test_unapplied_edits_survive_reload_and_show(env, qtbot):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    qtbot.addWidget(w)
    w.show()
    pump()
    orig = w.chart.points()
    edited = list(orig)
    edited[2] = (edited[2][0], 90)
    w.chart.set_points(edited)
    w.hide()
    w.show()                                     # showEvent reloads curves
    pump()
    st.fanCurvesChanged.emit("balanced", [FanCurve("CPU", (0, 59, 62, 65, 68, 71, 74, 76),
                                                    (2, 25, 38, 51, 63, 81, 99, 117), True)])
    assert w.chart.points() == edited
    w.fan_seg.set_current("GPU", emit=True)      # fan switch keeps the CPU edit too
    w.fan_seg.set_current("CPU", emit=True)
    assert w.chart.points() == edited
    w.btn_default.click()                        # Varsayılan discards
    assert w.chart.points() == orig


def test_edits_cleared_once_applied_curve_comes_back(env, qtbot):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    qtbot.addWidget(w)
    w.show()
    pts = w.chart.points()
    edited = list(pts)
    edited[2] = (edited[2][0], 90)
    w.chart.set_points(edited)
    cpu = FanCurve("CPU", tuple(t for t, _ in edited), tuple(round(p * 255 / 100) for _, p in edited), True)
    st.fanCurvesChanged.emit("balanced", [cpu])
    assert w.chart.points() == edited and not w._work


def test_custom_sliders_show_clamped_values(env, qtbot):
    st, ctl, settings = env
    w = FansWindow(st, ctl)
    qtbot.addWidget(w)
    w.btn_goto_custom.click()
    w.pl_sliders[0].setValue(100)                # PL1 above PL2(90)
    w.pl_sliders[0].committed.emit(100)
    assert ctl.custom_limits() == (100, 100, 110)
    assert [s.value() for s in w.pl_sliders] == [100, 100, 110]


def test_chart_uses_edited_profile_colour_not_active_accent(env, qtbot):
    from rog_control.ui.windows._base import PERF_COLOR
    st, ctl, settings = env                      # active mode: balanced
    w = FansWindow(st, ctl)
    qtbot.addWidget(w)
    w.profile_btns["turbo"].click()
    assert w.chart._accent == PERF_COLOR["turbo"] and w._accent == st.accent
    w.profile_btns["custom"].click()
    assert w.chart._accent == PERF_COLOR["custom"]
    st.set_perf_mode("quiet")                    # active accent change must not recolour the chart
    assert w.chart._accent == PERF_COLOR["custom"] and w._accent == st.accent


def test_settings_tray_watts_toggle_and_psys_info(env, tmp_path):
    st, ctl, settings = env
    w = SettingsWindow(st, ctl, settings, autostart_path=tmp_path / "a.desktop", project_root=tmp_path / "p q")
    assert not w.sw_watts.isChecked()                        # logo by default
    w.sw_watts.setChecked(True, emit=True)
    assert settings.value("ui/tray_watts", False, type=bool) is True
    w2 = SettingsWindow(st, ctl, settings, autostart_path=tmp_path / "a.desktop")
    assert w2.sw_watts.isChecked()
    st.set_sensors(fake_sensors(psys_available=False))
    assert "izin gerekli" in w.psys_info.text() and "install.sh" in w.psys_info.text()
    assert "'" in w.psys_info.text()                    # path with a space is quoted
    st.set_sensors(fake_sensors(psys_available=True))
    assert w.psys_info.text() == "Toplam güç: RAPL psys"


def test_tray_icon_watts_updates_only_on_integer_change(env):
    from rog_control.ui.windows.tray import watts_pixmap
    st, ctl, settings = env
    clk = [1000.0]
    t = Tray(st, ctl, settings, clock=lambda: clk[0])
    for _ in range(3):                                   # default: logo only, watts only in the tooltip
        clk[0] += 1.0
        st.set_sensors(fake_sensors(system_power_w=34.0))
    assert t._icon_watts is None and t.icon_updates == 0 and "34" in t.icon.toolTip()
    settings.setValue("ui/tray_watts", True)
    for _ in range(5):                                   # steady 34 W
        clk[0] += 1.0
        st.set_sensors(fake_sensors(system_power_w=34.0))
    assert t._icon_watts == 34 and t.icon_updates == 1
    st.set_sensors(fake_sensors(system_power_w=34.2))    # smoothed value still rounds to 34
    assert t.icon_updates == 1
    t._icon_at = clk[0]                                  # pretend we just redrew
    clk[0] += 0.3                                        # integer changes but <1 s since last redraw
    for _ in range(5):
        st.set_sensors(fake_sensors(system_power_w=40.0))
    assert t.icon_updates == 1
    for _ in range(60):                                  # AC value is an EMA: let it converge
        clk[0] += 1.0
        st.set_sensors(fake_sensors(system_power_w=40.0))
    assert t._icon_watts == 40 and 2 <= t.icon_updates <= 7   # one redraw per integer step at most
    st.set_sensors(fake_sensors(system_power_w=None, battery_status="Full", battery_power_w=None))
    assert t._icon_watts is None                         # back to the logo
    assert watts_pixmap(34, 22).toImage() != watts_pixmap(35, 22).toImage()
    settings.setValue("ui/tray_watts", False)
    st.set_sensors(fake_sensors(system_power_w=50.0))
    clk[0] += 5
    for _ in range(6):
        st.set_sensors(fake_sensors(system_power_w=50.0))
    assert t._icon_watts is None


def test_eco_exit_flow(env, monkeypatch):
    st, ctl, settings = env
    st.set_gfx(active="eco", boot="eco", dgpu_disabled=True)
    w = MainWindow(st, ctl, settings)
    w.show()
    asked = []
    answers = iter([True, False])           # confirm leaving Eco, then "Sonra" on the reboot prompt
    monkeypatch.setattr(dialogs, "ask", lambda parent, title, text, ok="Tamam", cancel="Vazgeç", *a, **k:
                        asked.append((title, text, ok, cancel)) or next(answers))
    w.gpu_row.clicked.emit("standard")
    assert ("request_gpu_mode", ("standard",)) in ctl.calls
    assert "yeniden başlat" in asked[0][1].lower() and "dGPU" in asked[0][1]
    # immediate reboot prompt, user says later
    assert asked[1][2:] == ("Yeniden başlat", "Sonra") and not ctl.rebooted
    assert not w.pending.isHidden()
    assert w._pending_color() == theme.WARN_ACCENT
    assert w.pending._cancel.isHidden()
    # "Yeniden başlat" path
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    ctl.gpuRebootRequired.emit()
    assert ctl.rebooted


def test_enter_eco_stays_pending_without_prompt(env, monkeypatch):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    w.show()
    asked = []
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: asked.append(a) or True)
    w.gpu_row.clicked.emit("eco")
    assert len(asked) == 1 and not ctl.rebooted
    assert not w.pending.isHidden() and not w.pending._cancel.isHidden()


def test_kbd_light_tray_action_and_main_button(env):
    st, ctl, settings = env
    t = Tray(st, ctl, settings)
    w = MainWindow(st, ctl, settings)
    assert t.act_light.isChecked() and w.btn_light.isEnabled() and w.btn_light._active
    w.btn_light.click()
    assert ("toggle_kbd_light", ()) in ctl.calls
    assert not t.act_light.isChecked() and not w.btn_light._active
    t.act_light.trigger()
    assert t.act_light.isChecked()
    st.emit_busy("kbd", True)
    assert not w.btn_light.isEnabled()
    st.emit_busy("kbd", False)
    st.set_aura(brightness=None)
    assert not w.btn_light.isEnabled() and not t.act_light.isEnabled()
