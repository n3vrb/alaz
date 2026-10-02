from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QSettings, QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import backend, theme
from .dialogs import LogoutCountdownDialog
from .mini_window import MiniWindow
from .profiles import ProfileManager
from .sensors import SensorReader, SensorSnapshot
from .tabs.aura_tab import AuraTab
from .tabs.fans_tab import FansTab
from .tabs.main_tab import MainTab
from .widgets.sensor_bar import SensorBar
from .widgets.titlebar import TitleBar

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def _load_icon() -> QIcon:
    svg = ASSETS_DIR / "icon.svg"
    if svg.exists():
        return QIcon(str(svg))
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    from PyQt5.QtGui import QPainter
    p = QPainter(pix)
    p.fillRect(8, 8, 48, 48, Qt.cyan)
    p.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self, capabilities: backend.Capabilities) -> None:
        super().__init__()
        # ── Frameless window ──────────────────────────────────────────────
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setWindowTitle("Asus Helper")
        self.setMinimumSize(480, 640)
        self.resize(540, 740)

        self._caps = capabilities

        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # Title bar
        col.addWidget(TitleBar(self, "Asus Helper"))

        # Sensor strip
        self.sensor_bar = SensorBar()
        col.addWidget(self.sensor_bar)

        # Tabs
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        self.main_tab  = MainTab(capabilities)
        self.fans_tab  = FansTab(capabilities)
        self.aura_tab  = AuraTab(capabilities)
        tabs.addTab(self.main_tab,  "Main")
        tabs.addTab(self.fans_tab,  "Fans")
        tabs.addTab(self.aura_tab,  "Aura")

        mini_btn = QPushButton("Mini")
        mini_btn.setObjectName("MiniBtn")
        mini_btn.setToolTip("Switch to compact Mini mode")
        from PyQt5.QtCore import pyqtSignal
        mini_btn.clicked.connect(lambda: self._request_mini())
        self._mini_callback = None
        self._mini_btn_ref  = mini_btn
        tabs.setCornerWidget(mini_btn, Qt.TopRightCorner)

        col.addWidget(tabs, 1)
        self.setCentralWidget(central)

        # Daemon warnings in the tab bar area (subtle)
        problems = []
        if not capabilities.asusd_available:
            problems.append("asusd not running")
        if not capabilities.supergfxd_available:
            problems.append("supergfxd not running")
        if problems:
            self.statusBar().showMessage("⚠  " + ", ".join(problems))
            self.statusBar().setStyleSheet(
                "background:#1c1c26; color:#f5a623; font-size:11px; padding:2px 14px;"
            )

        self._close_to_tray = True

    def set_mini_callback(self, fn) -> None:
        self._mini_callback = fn

    def _request_mini(self) -> None:
        if self._mini_callback:
            self._mini_callback()

    def update_snapshot(self, snap: SensorSnapshot) -> None:
        self.sensor_bar.update_snapshot(snap)
        self.main_tab.update_snapshot(snap)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._close_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            event.accept()

    def request_quit(self) -> None:
        self._close_to_tray = False
        self.close()


class AsusHelperApp:
    def __init__(self) -> None:
        os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")

        self.qt_app = QApplication(sys.argv)
        self.qt_app.setApplicationName("Asus Helper")
        self.qt_app.setOrganizationName("asus-helper")
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.qt_app.setWindowIcon(_load_icon())
        self.qt_app.setStyle("Fusion")
        theme.apply(self.qt_app)

        self.settings         = QSettings("asus-helper", "asus-helper")
        self._notify_enabled  = self.settings.value("notifications", True, type=bool)

        self.capabilities = backend.probe_capabilities()
        self.window       = MainWindow(self.capabilities)
        self.window.set_mini_callback(self._enter_mini)

        self.mini = MiniWindow(self.capabilities)
        self.mini.closed.connect(self._exit_mini)
        geo = self.settings.value("mini_geometry")
        if geo is not None:
            self.mini.restoreGeometry(geo)

        self.tray = self._build_tray()

        # Sensor stream
        interval = int(self.settings.value("poll_ms", 1000, type=int))
        self.reader = SensorReader(interval_ms=interval)
        self.reader.updated.connect(self._on_snapshot)
        self.reader.start()

        # Slow-poll: detect external profile changes
        self._last_profile  = None
        self._state_timer   = QTimer()
        self._state_timer.setInterval(3000)
        self._state_timer.timeout.connect(self._poll_state)
        self._state_timer.start()
        self._poll_state()

        if not (self.capabilities.asusd_available or self.capabilities.supergfxd_available):
            QMessageBox.warning(
                self.window,
                "Daemons unavailable",
                "Neither asusd nor supergfxd appear to be running.\n"
                "Most controls will be disabled.",
            )

    # ── Tray ─────────────────────────────────────────────────────────────

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(_load_icon(), self.qt_app)
        tray.setToolTip("Asus Helper")
        menu = QMenu()
        self._tray_menu = menu

        self._profile_menu       = menu.addMenu("Profile")
        self._gpu_menu           = menu.addMenu("GPU mode")
        self._user_profiles_menu = menu.addMenu("Load profile")
        menu.addSeparator()

        mini_action = QAction("Mini mode", menu)
        mini_action.triggered.connect(self._enter_mini)
        menu.addAction(mini_action)

        self._notify_action = QAction("Notify on profile change", menu)
        self._notify_action.setCheckable(True)
        self._notify_action.setChecked(self._notify_enabled)
        self._notify_action.toggled.connect(self._on_notify_toggled)
        menu.addAction(self._notify_action)

        menu.addSeparator()
        show_action = QAction("Show window", menu)
        show_action.triggered.connect(self._on_show)
        menu.addAction(show_action)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)

        menu.aboutToShow.connect(self._rebuild_tray_submenus)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_notify_toggled(self, on: bool) -> None:
        self._notify_enabled = on
        self.settings.setValue("notifications", on)

    def _rebuild_tray_submenus(self) -> None:
        self._profile_menu.clear()
        try:
            current = backend.get_profile() if self.capabilities.asusd_available else None
        except backend.BackendError:
            current = None
        for label in ("Silent", "Balanced", "Turbo"):
            action = QAction(label, self._profile_menu)
            action.setCheckable(True)
            asusctl = backend.PROFILE_LABEL_TO_ASUSCTL[label]
            action.setChecked(asusctl == current)
            action.setEnabled(self.capabilities.asusd_available)
            action.triggered.connect(lambda _c, n=asusctl: self._set_profile(n))
            self._profile_menu.addAction(action)

        self._gpu_menu.clear()
        supported: list[str] = []
        current_gpu = None
        if self.capabilities.supergfxd_available:
            try:
                supported    = backend.get_supported_gpu_modes()
                current_gpu  = backend.get_gpu_mode()
            except backend.BackendError:
                supported = []
        if not supported:
            empty = QAction("(supergfxd unavailable)", self._gpu_menu)
            empty.setEnabled(False)
            self._gpu_menu.addAction(empty)
        else:
            for mode in supported:
                label  = backend.SUPERGFX_TO_GPU_LABEL.get(mode, mode)
                action = QAction(label, self._gpu_menu)
                action.setCheckable(True)
                action.setChecked(mode == current_gpu)
                action.triggered.connect(lambda _c, m=mode: self._set_gpu(m))
                self._gpu_menu.addAction(action)

        # User profiles submenu
        self._user_profiles_menu.clear()
        pm = ProfileManager()
        names = pm.list_names()
        if names:
            for pname in names:
                p = pm.get(pname)
                if p is None:
                    continue
                tip = ProfileManager.summary(p)
                action = QAction(pname, self._user_profiles_menu)
                action.setToolTip(tip)
                action.triggered.connect(
                    lambda _c, _p=p: self._load_user_profile(_p)
                )
                self._user_profiles_menu.addAction(action)
        else:
            empty = QAction("(no saved profiles)", self._user_profiles_menu)
            empty.setEnabled(False)
            self._user_profiles_menu.addAction(empty)

    def _set_profile(self, asusctl_name: str) -> None:
        try:
            backend.set_profile(asusctl_name)
        except backend.BackendError as exc:
            QMessageBox.warning(self.window, "Profile change failed", str(exc))
        self.window.main_tab.refresh_profile()
        self.mini.refresh_states()

    def _set_gpu(self, mode: str) -> None:
        try:
            prev_raw   = backend.get_gpu_mode()
            from_label = backend.SUPERGFX_TO_GPU_LABEL.get(prev_raw, prev_raw)
        except backend.BackendError:
            from_label = "current mode"
        to_label = backend.SUPERGFX_TO_GPU_LABEL.get(mode, mode)

        try:
            result = backend.set_gpu_mode(mode)
        except backend.BackendError as exc:
            QMessageBox.warning(self.window, "GPU mode switch failed", str(exc))
            return

        self.window.main_tab.refresh_gpu()
        self.mini.refresh_states()

        lowered = result.lower()
        if "reboot" in lowered:
            QMessageBox.information(
                self.window, "Reboot required",
                f"Reboot required to finish switching to <b>{to_label}</b>.",
            )
        else:
            LogoutCountdownDialog.maybe_show(result, from_label, to_label, self.window)

    def _load_user_profile(self, p) -> None:
        """Load a named user profile from the tray menu."""
        self.window.main_tab._apply_user_profile(p)
        self.mini.refresh_states()

    # ── Sensor / state callbacks ─────────────────────────────────────────

    def _on_snapshot(self, snap: SensorSnapshot) -> None:
        self.window.update_snapshot(snap)
        self.mini.update_snapshot(snap)
        self.tray.setToolTip(SensorBar.tooltip_text(snap))

    def _poll_state(self) -> None:
        if not self.capabilities.asusd_available:
            return
        try:
            current = backend.get_profile()
        except backend.BackendError:
            return
        if self._last_profile is not None and current != self._last_profile:
            self.window.main_tab.refresh_profile()
            self.mini.refresh_states()
            if self._notify_enabled:
                label = backend.ASUSCTL_TO_PROFILE_LABEL.get(current, current)
                self.tray.showMessage("Profile changed", f"Now: {label}", _load_icon(), 3000)
        self._last_profile = current

    # ── Mini mode ─────────────────────────────────────────────────────────

    def _enter_mini(self) -> None:
        self.window.hide()
        self.mini.refresh_states()
        self.mini.show()
        self.mini.raise_()
        self.mini.activateWindow()

    def _exit_mini(self) -> None:
        self.settings.setValue("mini_geometry", self.mini.saveGeometry())
        self.mini.hide()
        self._on_show()

    # ── Window plumbing ───────────────────────────────────────────────────

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_window()

    def _on_show(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _on_quit(self) -> None:
        if self.mini.isVisible():
            self.settings.setValue("mini_geometry", self.mini.saveGeometry())
        self.reader.stop()
        self.tray.hide()
        self.window.request_quit()
        self.qt_app.quit()

    def _toggle_window(self) -> None:
        if self.mini.isVisible():
            self._exit_mini()
            return
        if self.window.isVisible():
            self.window.hide()
        else:
            self._on_show()

    def run(self) -> int:
        self.window.show()
        return self.qt_app.exec_()


def main() -> int:
    return AsusHelperApp().run()
