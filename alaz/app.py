"""Application entry: single instance, backend wiring, windows and tray."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from alaz import i18n
from alaz.ui import theme

log = logging.getLogger("alaz")

INSTANCE_NAME = "alaz"
FAKE_INSTANCE_NAME = "alaz-fake"


def legacy_settings_file() -> Path:
    """Settings file of the app's former name (ROG Control)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "rog-control" / "rog-control.conf"


def migrate_legacy_settings(settings: QSettings, legacy_file: Path | None = None) -> bool:
    """First start after the rename: copy every key of the old ROG Control settings file into
    ``settings`` if the new file does not exist yet. Returns True if keys were copied."""
    new_file = settings.fileName()
    if not new_file or os.path.exists(new_file):
        return False
    old = Path(legacy_file) if legacy_file is not None else legacy_settings_file()
    if not old.is_file():
        return False
    src = QSettings(str(old), QSettings.Format.IniFormat)
    keys = src.allKeys()
    for k in keys:
        settings.setValue(k, src.value(k))
    settings.sync()
    log.info("migrated %d settings from %s to %s", len(keys), old, new_file)
    return True


class SingleInstance(QObject):
    """QLocalServer based guard. A second launch calls `notify_existing()` and exits."""

    activated = pyqtSignal()

    def __init__(self, name: str = INSTANCE_NAME, parent: QObject | None = None):
        super().__init__(parent)
        self.name = name
        self._server: QLocalServer | None = None

    def notify_existing(self, timeout_ms: int = 500) -> bool:
        """True if another instance is listening (it is asked to raise its window)."""
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        return True

    def listen(self) -> bool:
        QLocalServer.removeServer(self.name)  # stale socket from a crashed run
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        ok = self._server.listen(self.name)
        if not ok:
            log.error("single-instance server failed: %s", self._server.errorString())
        return ok

    def close(self) -> None:
        if self._server is not None:
            self._server.close()

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: (s.readAll(), self.activated.emit()))
            sock.disconnected.connect(sock.deleteLater)


class Shell(QObject):
    """Owns all windows + the tray and wires navigation between them."""

    TRAY_POLL_MS = 1000          # startup: wait for the AppIndicator host...
    TRAY_POLL_TIMEOUT_S = 20     # ...this long before giving up and showing the window
    TRAY_WATCH_MS = 5000         # afterwards: notice the host (re)appearing, e.g. shell restart

    def __init__(self, state, controller, settings: QSettings, parent: QObject | None = None,
                 tray_available_fn=None):
        super().__init__(parent)
        self._tray_ok = tray_available_fn or tray_available
        self._poll_timer: QTimer | None = None
        self._watch_timer: QTimer | None = None
        self._polls = 0
        self._was_available = False
        from alaz.ui.windows.fans_window import FansWindow
        from alaz.ui.windows.keyboard_window import KeyboardWindow
        from alaz.ui.windows.main_window import MainWindow
        from alaz.ui.windows.mini_window import MiniWindow
        from alaz.ui.windows.settings_window import SettingsWindow
        from alaz.ui.windows.tray import Tray

        self.state, self.ctl, self.settings = state, controller, settings
        self.tray = Tray(state, controller, settings, self, available_fn=self._tray_ok)
        self.main = MainWindow(state, controller, settings, tray_available=self._tray_ok)
        self.fans = FansWindow(state, controller)
        self.keyboard = KeyboardWindow(state, controller)
        self.settings_win = SettingsWindow(state, controller, settings)
        self.mini = MiniWindow(state, controller)

        self.main.openFans.connect(lambda: self._open_sub(self.fans))
        self.main.openKeyboard.connect(lambda: self._open_sub(self.keyboard))
        self.main.openSettings.connect(lambda: self._open_sub(self.settings_win))
        self.main.openMini.connect(self.show_mini)
        for w in (self.fans, self.keyboard, self.settings_win):
            w.backRequested.connect(self.show_main)
        self.mini.expandRequested.connect(self.show_main)
        self.tray.openMainRequested.connect(self.show_main)
        self.tray.miniRequested.connect(self.show_mini)
        self.tray.quitRequested.connect(self.quit)

    def _open_sub(self, w) -> None:
        w.move(self.main.pos())
        w.show()
        w.raise_()
        w.activateWindow()
        self.main.hide()

    def show_main(self) -> None:
        self.mini.hide()
        self.main.showNormal()
        self.main.raise_()
        self.main.activateWindow()

    def show_mini(self) -> None:
        self.main.hide()
        self.mini.show()
        self.mini.raise_()

    def start(self, minimized: bool = False) -> None:
        self._was_available = bool(self._tray_ok())
        self.tray.show()
        self._start_watch()
        if not minimized:
            self.main.show()
        elif self._was_available:
            log.info("started minimised to tray")
        else:
            log.info("tray not available yet; waiting up to %d s", self.TRAY_POLL_TIMEOUT_S)
            self._polls = 0
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(self.TRAY_POLL_MS)
            self._poll_timer.timeout.connect(self._poll_tray)
            self._poll_timer.start()

    def _stop_poll(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer.deleteLater()
            self._poll_timer = None

    def _poll_tray(self) -> None:
        self._polls += 1
        if self._tray_ok():
            self._stop_poll()
            self._was_available = True
            self.tray.show()
            log.info("tray became available after %d s; staying hidden", self._polls)
        elif self._polls * self.TRAY_POLL_MS >= self.TRAY_POLL_TIMEOUT_S * 1000:
            self._stop_poll()
            log.warning("tray never became available; showing the main window")
            self.main.show()

    def _start_watch(self) -> None:
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(self.TRAY_WATCH_MS)
        self._watch_timer.timeout.connect(self._watch_tray)
        self._watch_timer.start()

    def _watch_tray(self) -> None:
        ok = bool(self._tray_ok())
        if ok and not self._was_available:
            log.info("tray became available; showing the icon")
            self.tray.show()
        self._was_available = ok

    def quit(self) -> None:
        from alaz.ui.windows._base import request_quit
        for t in (self._poll_timer, self._watch_timer):
            if t is not None:
                t.stop()
        self.tray.hide()
        request_quit()


def tray_available() -> bool:
    from alaz.ui.windows.tray import Tray
    return Tray.available()


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="alaz", description="Alaz")
    ap.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    ap.add_argument("--fake", action="store_true", help="demo mode with fake data (never touches the system)")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def _build_fake():
    from alaz.ui.windows._fake import FakeController, FakeState
    state = FakeState()
    return state, FakeController(state), []


def _build_real(settings: QSettings):
    """Import core lazily so the UI can be developed against fakes; exits 1 if core is missing."""
    try:
        from alaz.core.controller import Controller
        from alaz.core.state import AppState
    except Exception:  # noqa: BLE001 - any import failure must produce a clear message
        log.exception("alaz.core.controller could not be imported; use --fake for a demo")
        return None
    from alaz.backend.asusd import AsusdClient
    from alaz.backend.display import DisplayClient
    from alaz.backend.gfx import GfxClient
    from alaz.backend.sensors import SensorReader

    state = AppState()
    asusd, gfx, sensors, display = AsusdClient(), GfxClient(), SensorReader(), DisplayClient()
    ctl = Controller(state, asusd, gfx, sensors, display, settings)
    return state, ctl, [asusd, gfx, sensors, display]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("alaz")
    app.setOrganizationName("alaz")
    # Wayland app_id = desktop file name: lets GNOME match alaz.desktop, so the
    # dock / alt-tab show "Alaz" with its icon instead of "python3".
    app.setDesktopFileName("alaz")
    app.setApplicationDisplayName("Alaz")
    from alaz.ui.app_icon import app_icon
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstance(FAKE_INSTANCE_NAME if args.fake else INSTANCE_NAME)
    if guard.notify_existing():
        log.info("another instance is running; asked it to show its window")
        return 0
    guard.listen()

    settings = QSettings("alaz", "alaz")
    if not args.fake:
        migrate_legacy_settings(settings)
    log.debug("UI language: %s", i18n.init_from_settings(settings))   # must precede any window
    built = _build_fake() if args.fake else _build_real(settings)
    if built is None:
        return 1
    state, controller, _keep = built
    theme.apply(app, state.accent)
    shell = Shell(state, controller, settings)
    guard.activated.connect(shell.show_main)
    controller.start()
    # Follow external refresh-rate changes (GNOME settings, other tools) so
    # current_hz never goes stale. Real DisplayClient only; fakes don't have it.
    for obj in _keep:
        watch = getattr(obj, "start_watching", None)
        if callable(watch):
            watch()
    shell.start(minimized=args.minimized)
    code = app.exec()
    for obj in _keep:
        stop = getattr(obj, "stop_watching", None)
        if callable(stop):
            stop()
    guard.close()
    return code
