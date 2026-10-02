"""SettingsWindow: autostart (.desktop file), minimise to tray, profile-change notifications (QSettings)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from rog_control.ui import theme
from rog_control.ui.widgets import ToggleSwitch
from rog_control.ui.windows._base import FramelessWindow, Panel, hline, label

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUTOSTART = Path(os.path.expanduser("~/.config/autostart/rog-control.desktop"))
KEY_TRAY = "ui/minimize_to_tray"
KEY_NOTIFY = "ui/notify_profile"


def desktop_entry(root: Path = PROJECT_ROOT) -> str:
    return ("[Desktop Entry]\nType=Application\nName=ROG Control\nComment=ASUS ROG laptop control\n"
            "Exec=python3 -m rog_control --minimized\n"
            f"Path={root}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")


def autostart_enabled(path: Path) -> bool:
    return Path(path).is_file()


def set_autostart(path: Path, on: bool, root: Path = PROJECT_ROOT) -> None:
    path = Path(path)
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(root), encoding="utf-8")
        log.info("autostart enabled: %s", path)
    else:
        try:
            path.unlink()
            log.info("autostart disabled: %s", path)
        except FileNotFoundError:
            pass


class SettingsWindow(FramelessWindow):
    def __init__(self, state, controller, settings: QSettings, autostart_path: Path | None = None,
                 project_root: Path = PROJECT_ROOT, parent: QWidget | None = None):
        super().__init__(state, controller, "ROG Control — Ayarlar", 480, 270, back=True, parent=parent)
        self.settings = settings
        self.autostart_path = Path(autostart_path) if autostart_path else DEFAULT_AUTOSTART
        self.project_root = project_root
        tb = self.titlebar.lay
        tb.addWidget(self.title_label("Ayarlar"))
        tb.addStretch(1)
        self.add_window_buttons(minimize=False)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(14)
        p = Panel(14)
        p.lay.setContentsMargins(14, 6, 14, 6)
        p.lay.setSpacing(6)
        self.sw_autostart = ToggleSwitch("Oturum açılışında başlat", "Giriş yapınca tepside küçültülmüş açılır")
        self.sw_tray = ToggleSwitch("Kapatınca tepsiye küçült", "Pencereyi kapatmak uygulamayı çalışır halde bırakır")
        self.sw_notify = ToggleSwitch("Profil değişince bildirim göster", "Fn tuşu gibi dış değişikliklerde")
        for i, sw in enumerate((self.sw_autostart, self.sw_tray, self.sw_notify)):
            sw.setMinimumHeight(48)
            p.lay.addWidget(sw)
            if i < 2:
                p.lay.addWidget(hline())
        lay.addWidget(p)
        self.note = label("", 11.5, 400, theme.TEXT3)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.track_accent(self.sw_autostart, self.sw_tray, self.sw_notify)

        self.sw_autostart.setChecked(autostart_enabled(self.autostart_path))
        self.sw_tray.setChecked(settings.value(KEY_TRAY, True, type=bool))
        self.sw_notify.setChecked(settings.value(KEY_NOTIFY, True, type=bool))
        self.sw_autostart.toggled.connect(self._autostart)
        self.sw_tray.toggled.connect(lambda on: self._save(KEY_TRAY, on))
        self.sw_notify.toggled.connect(lambda on: self._save(KEY_NOTIFY, on))

    def _save(self, key: str, on: bool) -> None:
        self.settings.setValue(key, bool(on))
        self.settings.sync()

    def _autostart(self, on: bool) -> None:
        try:
            set_autostart(self.autostart_path, bool(on), self.project_root)
            self.note.setText("")
        except OSError as e:
            log.error("autostart write failed: %s", e)
            self.sw_autostart.setChecked(autostart_enabled(self.autostart_path))
            self.note.setText(f"Otomatik başlatma ayarlanamadı: {e}")
