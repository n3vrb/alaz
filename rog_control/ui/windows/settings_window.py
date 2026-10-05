"""SettingsWindow: autostart (systemd user unit, XDG .desktop fallback), minimise to tray, profile-change notifications (QSettings)."""
from __future__ import annotations

import logging
import os
import shlex
import shutil
from pathlib import Path

from PyQt6.QtCore import QProcess, QSettings, Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from rog_control import i18n
from rog_control.i18n import tr
from rog_control.ui import theme
from rog_control.ui.widgets import Segmented, ToggleSwitch
from rog_control.ui.windows._base import FramelessWindow, Panel, hline, label

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUTOSTART = Path(os.path.expanduser("~/.config/autostart/rog-control.desktop"))
UNIT_NAME = "rog-control.service"
DEFAULT_UNIT = Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")) / "systemd" / "user" / UNIT_NAME
KEY_TRAY = "ui/minimize_to_tray"
KEY_NOTIFY = "ui/notify_profile"
KEY_TRAY_WATTS = "ui/tray_watts"


def install_command(root: Path = PROJECT_ROOT) -> str:
    return "sudo " + shlex.quote(str(Path(root) / "helper" / "install.sh"))


def _launcher() -> str | None:
    """Path of an installed `rog-control` launcher (~/.local/bin or PATH), if any."""
    local = Path(os.path.expanduser("~/.local/bin/rog-control"))
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which("rog-control")


def desktop_entry(root: Path = PROJECT_ROOT, launcher: str | None = None) -> str:
    launcher = launcher if launcher is not None else _launcher()
    head = "[Desktop Entry]\nType=Application\nName=ROG Control\nComment=ASUS ROG laptop control\n"
    tail = "Terminal=false\nX-GNOME-Autostart-enabled=true\n"
    if launcher:
        return head + "Exec=rog-control --minimized\n" + tail
    return head + "Exec=python3 -m rog_control --minimized\n" + f"Path={root}\n" + tail


def autostart_enabled(path: Path) -> bool:
    return Path(path).is_file()


def set_autostart(path: Path, on: bool, root: Path = PROJECT_ROOT, launcher: str | None = None) -> None:
    path = Path(path)
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(root, launcher), encoding="utf-8")
        log.info("autostart enabled: %s", path)
    else:
        try:
            path.unlink()
            log.info("autostart disabled: %s", path)
        except FileNotFoundError:
            pass


_procs: set = set()


def run_systemctl(args: list[str], callback) -> None:
    """Run `systemctl --user <args>` asynchronously; callback(exit_code, stdout).

    exit_code is -1 if systemctl could not be started. Never blocks the GUI thread.
    """
    proc = QProcess()
    _procs.add(proc)

    def done(*_a) -> None:
        if proc not in _procs:
            return
        _procs.discard(proc)
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace").strip()
        code = proc.exitCode() if proc.exitStatus() == QProcess.ExitStatus.NormalExit else -1
        proc.deleteLater()
        callback(code, out)

    def failed(_err) -> None:
        if proc.state() == QProcess.ProcessState.NotRunning and proc in _procs and \
                proc.error() == QProcess.ProcessError.FailedToStart:
            _procs.discard(proc)
            proc.deleteLater()
            callback(-1, "")

    proc.finished.connect(done)
    proc.errorOccurred.connect(failed)
    proc.start("systemctl", ["--user", *args])


class SettingsWindow(FramelessWindow):
    def __init__(self, state, controller, settings: QSettings, autostart_path: Path | None = None,
                 project_root: Path = PROJECT_ROOT, parent: QWidget | None = None,
                 unit_path: Path | None = None, systemctl_runner=None):
        super().__init__(state, controller, tr("ROG Control — Ayarlar"), 480, 470, back=True, parent=parent)
        self.settings = settings
        self.autostart_path = Path(autostart_path) if autostart_path else DEFAULT_AUTOSTART
        self.project_root = project_root
        self.unit_path = Path(unit_path) if unit_path else DEFAULT_UNIT
        self._systemctl = systemctl_runner or run_systemctl
        tb = self.titlebar.lay
        tb.addWidget(self.title_label(tr("Ayarlar")))
        tb.addStretch(1)
        self.add_window_buttons(minimize=False)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(14)
        p = Panel(14)
        p.lay.setContentsMargins(14, 6, 14, 6)
        p.lay.setSpacing(6)
        self.sw_autostart = ToggleSwitch(tr("Oturum açılışında başlat"), tr("Giriş yapınca tepside küçültülmüş açılır"))
        self.sw_tray = ToggleSwitch(tr("Kapatınca tepsiye küçült"), tr("Pencereyi kapatmak uygulamayı çalışır halde bırakır"))
        self.sw_notify = ToggleSwitch(tr("Profil değişince bildirim göster"), tr("Fn tuşu gibi dış değişikliklerde"))
        self.sw_watts = ToggleSwitch(tr("Tepside watt göster"), tr("Tepsi simgesinde toplam güç (W) yazar"))
        for i, sw in enumerate((self.sw_autostart, self.sw_tray, self.sw_notify, self.sw_watts)):
            sw.setMinimumHeight(48)
            p.lay.addWidget(sw)
            if i < 3:
                p.lay.addWidget(hline())
        p.lay.addWidget(hline())
        lang_row = QHBoxLayout()
        lang_row.setContentsMargins(0, 0, 0, 0)
        lang_row.setSpacing(10)
        lang_row.addWidget(label("Dil / Language", 13, 500), 1)
        self.lang_seg = Segmented([("auto", tr("Otomatik")), ("en", "English"), ("tr", "Türkçe")], 30, 12.5, 12)
        pref = str(settings.value(i18n.KEY_LANGUAGE, "auto") or "auto")
        self.lang_seg.set_current(pref if pref in i18n.LANGUAGES else "auto")
        self.lang_seg.changed.connect(self._language_changed)
        lang_row.addWidget(self.lang_seg)
        lang_w = QWidget()
        lang_w.setMinimumHeight(48)
        lang_w.setLayout(lang_row)
        p.lay.addWidget(lang_w)
        lay.addWidget(p)
        self.lang_note = label("", 11.5, 400, theme.TEXT2)
        self.lang_note.setWordWrap(True)
        lay.addWidget(self.lang_note)
        self.psys_info = label("", 11.5, 400, theme.TEXT2)
        self.psys_info.setWordWrap(True)
        self.psys_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.psys_info)
        self.note = label("", 11.5, 400, theme.TEXT3)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.track_accent(self.sw_autostart, self.sw_tray, self.sw_notify, self.sw_watts, self.lang_seg)

        self._init_autostart_state()
        self.sw_tray.setChecked(settings.value(KEY_TRAY, True, type=bool))
        self.sw_notify.setChecked(settings.value(KEY_NOTIFY, True, type=bool))
        self.sw_watts.setChecked(settings.value(KEY_TRAY_WATTS, False, type=bool))
        self.sw_watts.toggled.connect(lambda on: self._save(KEY_TRAY_WATTS, on))
        state.sensorsChanged.connect(lambda s: self._refresh_psys(s))
        self._refresh_psys(state.sensors)
        self.sw_autostart.toggled.connect(self._autostart)
        self.sw_tray.toggled.connect(lambda on: self._save(KEY_TRAY, on))
        self.sw_notify.toggled.connect(lambda on: self._save(KEY_NOTIFY, on))

    def _refresh_psys(self, snap) -> None:
        avail = getattr(snap, "psys_available", None)
        if avail is True:
            self.psys_info.setText(tr("Toplam güç: RAPL psys"))
        elif avail is False:
            self.psys_info.setText(tr("Toplam güç ölçümü için izin gerekli. Terminalde çalıştırın:") + "\n"
                                   + install_command(self.project_root))
        else:
            self.psys_info.setText("")

    def _language_changed(self, key: str) -> None:
        """Stored now, applied at the next start (no live re-translation)."""
        self.settings.setValue(i18n.KEY_LANGUAGE, key)
        self.settings.sync()
        effective = i18n.resolve(key)
        if effective == i18n.current_language() and key == i18n.language_preference():
            self.lang_note.setText("")
        else:
            # shown in both languages: the user may be switching away from one they cannot read
            self.lang_note.setText("Değişiklik yeniden başlatınca uygulanır / Applies after restart")

    def _save(self, key: str, on: bool) -> None:
        self.settings.setValue(key, bool(on))
        self.settings.sync()

    def _use_systemd(self) -> bool:
        return self.unit_path.is_file()

    def _init_autostart_state(self) -> None:
        if not self._use_systemd():
            self.sw_autostart.setChecked(autostart_enabled(self.autostart_path))
            return

        def got(code: int, out: str) -> None:
            self.sw_autostart.setChecked(code == 0 and out.strip() == "enabled")

        self._systemctl(["is-enabled", UNIT_NAME], got)

    def _autostart(self, on: bool) -> None:
        on = bool(on)
        if self._use_systemd():
            self._autostart_systemd(on)
            return
        try:
            set_autostart(self.autostart_path, on, self.project_root)
            self.note.setText("")
        except OSError as e:
            log.error("autostart write failed: %s", e)
            self.sw_autostart.setChecked(autostart_enabled(self.autostart_path))
            self.note.setText(tr("Otomatik başlatma ayarlanamadı: {err}", err=e))

    def _autostart_systemd(self, on: bool) -> None:
        def done(code: int, _out: str) -> None:
            if code != 0:
                log.error("systemctl --user %s failed (exit %s)", "enable" if on else "disable", code)
                self.sw_autostart.setChecked(not on)
                self.note.setText(tr("Otomatik başlatma ayarlanamadı (systemctl --user başarısız)."))
                return
            self.note.setText("")
            if on:
                try:   # avoid a double start next to the old XDG entry
                    self.autostart_path.unlink()
                    log.info("removed legacy autostart entry %s", self.autostart_path)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    log.warning("could not remove %s: %s", self.autostart_path, e)

        self._systemctl(["enable" if on else "disable", UNIT_NAME], done)
