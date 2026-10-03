"""Application entry: single instance, backend wiring, windows and tray."""
from __future__ import annotations

import argparse
import logging
import sys

from PyQt6.QtCore import QObject, QSettings, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from rog_control import i18n
from rog_control.ui import theme

log = logging.getLogger("rog_control")

INSTANCE_NAME = "rog-control"
FAKE_INSTANCE_NAME = "rog-control-fake"


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
        from rog_control.ui.windows.fans_window import FansWindow
        from rog_control.ui.windows.keyboard_window import KeyboardWindow
        from rog_control.ui.windows.main_window import MainWindow
        from rog_control.ui.windows.mini_window import MiniWindow
        from rog_control.ui.windows.settings_window import SettingsWindow
        from rog_control.ui.windows.tray import Tray

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
        from rog_control.ui.windows._base import request_quit
        for t in (self._poll_timer, self._watch_timer):
            if t is not None:
                t.stop()
        self.tray.hide()
        request_quit()


def tray_available() -> bool:
    from rog_control.ui.windows.tray import Tray
    return Tray.available()


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="rog_control", description="ROG Control")
    ap.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    ap.add_argument("--fake", action="store_true", help="demo mode with fake data (never touches the system)")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def _build_fake():
    from rog_control.ui.windows._fake import FakeController, FakeState
    state = FakeState()
    return state, FakeController(state), []


def _build_real(settings: QSettings):
    """Import core lazily so the UI can be developed against fakes; exits 1 if core is missing."""
    try:
        from rog_control.core.controller import Controller
        from rog_control.core.state import AppState
    except Exception:  # noqa: BLE001 - any import failure must produce a clear message
        log.exception("rog_control.core.controller could not be imported; use --fake for a demo")
        return None
    from rog_control.backend.asusd import AsusdClient
    from rog_control.backend.display import DisplayClient
    from rog_control.backend.gfx import GfxClient
    from rog_control.backend.sensors import SensorReader

    state = AppState()
    asusd, gfx, sensors, display = AsusdClient(), GfxClient(), SensorReader(), DisplayClient()
    ctl = Controller(state, asusd, gfx, sensors, display, settings)
    return state, ctl, [asusd, gfx, sensors, display]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("rog-control")
    app.setOrganizationName("rog-control")
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstance(FAKE_INSTANCE_NAME if args.fake else INSTANCE_NAME)
    if guard.notify_existing():
        log.info("another instance is running; asked it to show its window")
        return 0
    guard.listen()

    settings = QSettings("rog-control", "rog-control")
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
