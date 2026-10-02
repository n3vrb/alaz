#!/usr/bin/env python3
"""Render every window offscreen to PNG using the fakes.

    QT_QPA_PLATFORM=offscreen .venv/bin/python tools/screenshot_windows.py [OUT_DIR]
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from rog_control.ui import theme  # noqa: E402
from rog_control.ui.windows._fake import FakeController, FakeState, fake_curves, fake_sensors  # noqa: E402
from rog_control.ui.windows.fans_window import FansWindow  # noqa: E402
from rog_control.ui.windows.keyboard_window import KeyboardWindow  # noqa: E402
from rog_control.ui.windows.main_window import MainWindow  # noqa: E402
from rog_control.ui.windows.mini_window import MiniWindow  # noqa: E402
from rog_control.ui.windows.settings_window import SettingsWindow  # noqa: E402
from rog_control.ui.windows.tray import Tray  # noqa: E402


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
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="rog-shots-"))
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    theme.apply(app)
    settings = QSettings(str(out / "shots.ini"), QSettings.Format.IniFormat)

    st, ctl = make("balanced")
    snap(app, MainWindow(st, ctl, settings), out / "main_dengeli.png")

    st, ctl = make("turbo")
    st.set_sensors(fake_sensors(cpu_temp=81, cpu_load=74, gpu_state="active", gpu_temp=67, gpu_load=55, gpu_power_w=48,
                                fans_rpm={"cpu": 4900, "gpu": 4700, "mid": 5200}, ram_pct=61, battery_pct=44,
                                battery_status="Discharging", on_ac=False))
    st.set_gfx(power="active")
    theme.apply(app, st.accent)
    snap(app, MainWindow(st, ctl, settings), out / "main_turbo.png")

    st, ctl = make("quiet")
    st.set_gfx(boot="eco", pending="eco")
    theme.apply(app, st.accent)
    snap(app, MainWindow(st, ctl, settings), out / "main_eco_pending.png")

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
    snap(app, SettingsWindow(st, ctl, settings, autostart_path=out / "autostart.desktop"), out / "settings.png")
    snap(app, MiniWindow(st, ctl), out / "mini.png")

    tray = Tray(st, ctl, settings)
    tray.menu.adjustSize()
    tray.menu.grab().save(str(out / "tray_menu.png"))
    print("saved", out / "tray_menu.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
