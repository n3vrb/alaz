"""Window tests run against the fakes (no hardware, no real system writes)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QApplication

from rog_control.app import SingleInstance, parse_args
from rog_control.backend.types import FanCurve
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


def test_settings_autostart_file(env, tmp_path):
    st, ctl, settings = env
    path = tmp_path / "autostart" / "rog-control.desktop"
    root = tmp_path / "proj"
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
