#!/usr/bin/env python3
"""Render every window offscreen to PNG using the fakes.

    QT_QPA_PLATFORM=offscreen .venv/bin/python tools/screenshot_windows.py [OUT_DIR] [--lang en|tr]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from alaz import i18n  # noqa: E402
from alaz.i18n import tr  # noqa: E402
from alaz.ui import theme  # noqa: E402
from alaz.ui.windows._fake import FakeController, FakeState, fake_curves, fake_sensors  # noqa: E402
from alaz.ui.windows import dialogs  # noqa: E402
from alaz.ui.windows.main_window import PERF_COLOR_GPU  # noqa: E402
from alaz.ui.windows.devices_window import DevicesWindow  # noqa: E402
from alaz.ui.windows.fans_window import FansWindow  # noqa: E402
from alaz.ui.windows.keyboard_window import KeyboardWindow  # noqa: E402
from alaz.ui.windows.main_window import MainWindow  # noqa: E402
from alaz.ui.windows.mini_window import MiniWindow  # noqa: E402
from alaz.ui.windows.settings_window import SettingsWindow  # noqa: E402
from alaz.ui.windows.tray import Tray  # noqa: E402


def snap(app, w, path: Path) -> None:
    w.show()
    for _ in range(4):
        app.processEvents()
    ok = w.grab().save(str(path))
    print(("saved " if ok else "FAILED ") + str(path))
    w.hide()
    w.deleteLater()


def make(perf: str = "balanced"):
    st = FakeState(perf)
    return st, FakeController(st)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out", nargs="?", help="output directory (default: a temp dir)")
    ap.add_argument("--lang", choices=("en", "tr"), default="tr", help="UI language to render (default: tr)")
    args = ap.parse_args()
    i18n.set_language(args.lang)
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="rog-shots-"))
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    theme.apply(app)
    settings = QSettings(str(out / "shots.ini"), QSettings.Format.IniFormat)

    st, ctl = make("balanced")
    snap(app, MainWindow(st, ctl, settings), out / "main_dengeli.png")

    st, ctl = make("turbo")
    st.set_sensors(fake_sensors(cpu_temp=81, cpu_load=74, gpu_state="active", gpu_temp=67, gpu_load=55, gpu_power_w=48,
                                fans_rpm={"cpu": 4900, "gpu": 4700, "mid": 5200}, ram_pct=61, battery_pct=44,
                                battery_status="Discharging", on_ac=False, battery_power_w=58.7, system_power_w=58.7))
    st.set_gfx(power="active")
    theme.apply(app, st.accent)
    snap(app, MainWindow(st, ctl, settings), out / "main_turbo.png")

    st, ctl = make("balanced")
    st.set_sensors(fake_sensors(battery_pct=62, battery_status="Charging", on_ac=True, battery_power_w=65.2,
                                system_power_w=104.0))
    snap(app, MainWindow(st, ctl, settings), out / "main_ac_charging.png")
    snap(app, MiniWindow(st, ctl), out / "mini_ac_charging.png")
    st.set_sensors(fake_sensors(battery_pct=71, battery_status="Discharging", on_ac=False, battery_power_w=26.4,
                                system_power_w=26.4))
    snap(app, MainWindow(st, ctl, settings), out / "main_battery.png")
    snap(app, MiniWindow(st, ctl), out / "mini_battery.png")

    st, ctl = make("quiet")
    st.set_gfx(boot="eco", pending="eco")
    theme.apply(app, st.accent)
    snap(app, MainWindow(st, ctl, settings), out / "main_eco_pending.png")

    # Eco exit: eco active -> confirm dialog -> pending (reboot required, warning tone)
    st, ctl = make("quiet")
    st.set_gfx(active="eco", boot="eco", dgpu_disabled=True)
    theme.apply(app, st.accent)
    w = MainWindow(st, ctl, settings)
    w.show()
    app.processEvents()
    dlg = dialogs.ConfirmDialog(w, tr("Eco modundan çık"), tr(dialogs.ECO_EXIT_TEXT), tr("Devam"), tr("Vazgeç"),
                                PERF_COLOR_GPU["standard"])
    dlg.show()
    app.processEvents()
    dlg.grab().save(str(out / "eco_exit_confirm.png"))
    dlg.deleteLater()
    w.hide()
    w.deleteLater()
    st.set_gfx(boot="standard", pending="standard", dgpu_disabled=False)
    snap(app, MainWindow(st, ctl, settings), out / "eco_exit_pending.png")

    # live GPU switching states (P4)
    from alaz.ui.windows._fake import FakeHolder
    live_states = {
        "gpu_live_standard": dict(live_ready=True),
        "gpu_live_optimize": dict(live_ready=True, optimize=True, selected="optimize", active="eco", boot="eco"),
        "gpu_live_switching": dict(live_ready=True, switching=True, selected="eco"),
        "gpu_live_waiting": dict(live_ready=True, waiting="eco", selected="eco",
                                 holders=[FakeHolder(), FakeHolder(pid=7, comm="steam", exe="/usr/bin/steam")]),
        "gpu_live_ultimate_mux": dict(live_ready=True, active="ultimate", boot="ultimate", selected="ultimate",
                                      mux_direct=True),
    }
    for name, kw in live_states.items():
        st, ctl = make("balanced")
        st.set_gfx(**kw)
        theme.apply(app, st.accent)
        snap(app, MainWindow(st, ctl, settings), out / f"{name}.png")
    st, ctl = make("balanced")
    st.set_gfx(live_ready=True)
    theme.apply(app, st.accent)
    w = MainWindow(st, ctl, settings)
    w.show()
    app.processEvents()
    ctl.gpuSwitchFailed.emit("GPU geçişi yarıda kaldı (zaman aşımı). Yeniden başlatmak geçişi güvenle tamamlar.", True)
    app.processEvents()
    w.grab().save(str(out / "gpu_failure_toast.png"))
    w.hide()
    w.deleteLater()
    for name, dlg in (("gpu_busy_dialog", dialogs.BusyDialog(None, ["blender", "steam", "firefox"],
                                                              PERF_COLOR_GPU["eco"])),
                      ("gpu_ultimate_dialog", dialogs.ConfirmDialog(None, tr(dialogs.ULTIMATE_TITLE),
                                                                    tr(dialogs.ULTIMATE_TEXT), tr("Devam"),
                                                                    tr("Vazgeç"), PERF_COLOR_GPU["ultimate"]))):
        dlg.show()
        app.processEvents()
        dlg.grab().save(str(out / f"{name}.png"))
        print("saved", out / f"{name}.png")
        dlg.deleteLater()

    st, ctl = make("balanced")
    st.set_gfx(active="eco", boot="standard", dgpu_disabled=True)
    st.set_display(auto=False, current_hz=120)
    theme.apply(app, st.accent)
    snap(app, MainWindow(st, ctl, settings), out / "main_banner_dualboot.png")

    st, ctl = make("balanced")
    theme.apply(app, st.accent)
    fw = FansWindow(st, ctl)
    snap(app, fw, out / "fans_dengeli.png")

    st, ctl = make("turbo")
    theme.apply(app, st.accent)
    fw = FansWindow(st, ctl)
    fw._select_profile("custom")
    fw.fan_seg.set_current("GPU", emit=True)
    snap(app, fw, out / "fans_ozel.png")

    st, ctl = make("balanced")
    theme.apply(app, st.accent)
    snap(app, KeyboardWindow(st, ctl), out / "keyboard.png")
    for tab in ("aura", "mouse", "headset", "monitor"):
        st, ctl = make("balanced")
        if tab == "aura":
            from alaz.core.state import AuraSyncView
            st.set_aura_sync(AuraSyncView(True, "breathing", (0xEA, 0xB2, 0x15), 80, {"keyboard", "mouse", "headset"}))
        theme.apply(app, st.accent)
        dw = DevicesWindow(st, ctl)
        dw.tabs.set_current(tab, emit=True)
        snap(app, dw, out / f"devices_{tab}.png")
    # unavailable / locked variants
    from alaz.ui.windows._fake import fake_headset, fake_monitor, fake_mouse
    st, ctl = make("balanced")
    st.set_peripheral("mouse", fake_mouse(present=True, permission=False))
    st.set_peripheral("headset", fake_headset(connected=False))
    dw = DevicesWindow(st, ctl)
    dw.tabs.set_current("mouse", emit=True)
    snap(app, dw, out / "devices_mouse_noperm.png")
    st, ctl = make("balanced")
    st.set_peripheral("monitor", fake_monitor(locked={"blue_light", "shadow_boost"},
                                              values={**fake_monitor().values, "blue_light": None,
                                                      "shadow_boost": None}))
    dw = DevicesWindow(st, ctl)
    dw.tabs.set_current("monitor", emit=True)
    snap(app, dw, out / "devices_monitor_locked.png")
    snap(app, SettingsWindow(st, ctl, settings, autostart_path=out / "autostart.desktop"), out / "settings.png")
    snap(app, MiniWindow(st, ctl), out / "mini.png")

    st.set_gfx(live_ready=True, optimize=True, selected="optimize", active="eco", boot="eco", dgpu_disabled=True)
    tray = Tray(st, ctl, settings)
    # feed one snapshot so the header + live power line are filled (on battery, measured-like value)
    st.set_sensors(fake_sensors(battery_status="Discharging", on_ac=False, battery_power_w=12.4,
                                system_power_w=13.6))
    tray.menu.adjustSize()
    tray.menu.grab().save(str(out / "tray_menu.png"))
    print("saved", out / "tray_menu.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
