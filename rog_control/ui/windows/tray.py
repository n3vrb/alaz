"""System tray icon + menu (docs/design/V2MiniTray.dc.html, right)."""
from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath,
                         QPen, QPixmap, QTransform)
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from rog_control.ui import theme
from rog_control.ui.power_text import PowerView, compose_power
from rog_control.ui.widgets.icons import draw_icon
from rog_control.ui.windows import dialogs
from rog_control.ui.windows._base import (GPU_LABEL, PERF_KEYS, PERF_LABEL, fmt_num, request_perf,
                                          seconds_since_local_perf)

log = logging.getLogger(__name__)

BAT_STATUS = {"Charging": "Şarj oluyor", "Discharging": "Boşalıyor", "Full": "Dolu", "Not charging": "Şarj olmuyor"}


def make_icon(accent: str) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.BG))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    draw_icon(p, "logo", QRectF(12, 12, 40, 40), accent, 3.2)
    p.end()
    return QIcon(pm)


KEY_TRAY_WATTS = "ui/tray_watts"
ICON_SIZES = (22, 32, 44, 64)


def watts_pixmap(watts: int, size: int) -> QPixmap:
    """Bold white digits with a dark outline on a transparent square, filling the icon."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    text = str(max(0, int(watts)))
    font = QFont("Sans Serif")
    font.setBold(True)
    font.setWeight(QFont.Weight.Black)
    font.setPixelSize(100)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    br = path.boundingRect()
    margin = max(1.0, size / 16)
    outline = max(1.2, size / 11)
    box = size - 2 * margin - outline
    sx = box / br.width()
    sy = min(box / br.height(), sx * 1.4)   # stretch tall digits a little so 2-3 digits stay legible
    t = QTransform()
    t.translate(size / 2, size / 2)
    t.scale(sx, sy)
    t.translate(-br.center().x(), -br.center().y())
    path = t.map(path)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(0, 0, 0, 215), outline)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(250, 250, 250))
    p.drawPath(path)
    p.end()
    return pm


def make_watts_icon(watts: int) -> QIcon:
    icon = QIcon()
    for sz in ICON_SIZES:
        icon.addPixmap(watts_pixmap(watts, sz))
    return icon


class Tray(QObject):
    openMainRequested = pyqtSignal()
    miniRequested = pyqtSignal()
    quitRequested = pyqtSignal()

    def __init__(self, state, controller, settings, parent: QObject | None = None, clock=time.monotonic):
        super().__init__(parent)
        self.state, self.ctl, self.settings = state, controller, settings
        self._clock = clock
        self._power = PowerView(5)
        self._power_w: tuple[float | None, float | None] = (None, None)
        self._icon_watts: int | None = None   # integer currently drawn in the tray icon
        self._icon_at = -1e9
        self.icon_updates = 0
        self.icon = QSystemTrayIcon(make_icon(state.accent), self)
        self.menu = QMenu()
        self.menu.setStyleSheet(
            f"QMenu {{ background:{theme.PANEL}; border:1px solid {theme.BORDER}; border-radius:10px; padding:6px; }}"
            f"QMenu::item {{ padding:7px 12px; border-radius:7px; color:{theme.TEXT}; }}"
            f"QMenu::item:selected {{ background:{theme.DIVIDER}; }}"
            f"QMenu::item:disabled {{ color:{theme.TEXT3}; }}"
            f"QMenu::separator {{ height:1px; background:{theme.DIVIDER}; margin:4px 0; }}")
        self._build_menu()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        state.perfModeChanged.connect(self._on_perf)
        state.accentChanged.connect(self._on_accent)
        state.sensorsChanged.connect(self._on_sensors)
        state.gfxChanged.connect(lambda _v: self._refresh_gfx())
        self._refresh_perf()
        self._refresh_gfx()
        self._refresh_info()

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        if self.available():
            self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    # ----------------------------------------------------------------- menu
    def _heading(self, text: str, bold: bool = False) -> QAction:
        a = self.menu.addAction(text)
        a.setEnabled(False)
        return a

    def _build_menu(self) -> None:
        self.head = self._heading("ROG Control")
        self.info = self._heading("")
        self.menu.addSeparator()
        self._heading("PERFORMANS")
        self.perf_group = QActionGroup(self.menu)
        self.perf_actions: dict[str, QAction] = {}
        for k in PERF_KEYS:
            a = self.menu.addAction(PERF_LABEL[k])
            a.setCheckable(True)
            a.setActionGroup(self.perf_group)
            a.triggered.connect(lambda _=False, key=k: request_perf(self.ctl, key))
            self.perf_actions[k] = a
        self.menu.addSeparator()
        self._heading("GPU MODU")
        self.gpu_group = QActionGroup(self.menu)
        self.gpu_actions: dict[str, QAction] = {}
        for k, text in (("standard", "Standart"), ("eco", "Eco   (yeniden başlatma)")):
            a = self.menu.addAction(text)
            a.setCheckable(True)
            a.setActionGroup(self.gpu_group)
            a.triggered.connect(lambda _=False, key=k: self._gpu(key))
            self.gpu_actions[k] = a
        self.menu.addSeparator()
        self.act_open = self.menu.addAction("Pencereyi aç")
        self.act_mini = self.menu.addAction("Mini mod")
        self.act_quit = self.menu.addAction("Çıkış")
        self.act_open.triggered.connect(self.openMainRequested)
        self.act_mini.triggered.connect(self.miniRequested)
        self.act_quit.triggered.connect(self.quitRequested)

    def _gpu(self, key: str) -> None:
        if key != self.state.gfx.active:
            dialogs.request_gpu_mode(None, self.ctl, key, self.state.accent,
                                     leaving_eco=(key == "standard" and self.state.gfx.active == "eco"))
        self._refresh_gfx()  # restore the radio state; the real change only happens after reboot

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.openMainRequested.emit()

    # -------------------------------------------------------------- refresh
    def _refresh_perf(self) -> None:
        m = self.state.perf_mode
        for k, a in self.perf_actions.items():
            a.setChecked(k == m)
        self._refresh_info()

    def _refresh_gfx(self) -> None:
        g = self.state.gfx.active
        for k, a in self.gpu_actions.items():
            a.setChecked(k == g)

    def _on_accent(self, accent: str) -> None:
        if self._icon_watts is None:
            self.icon.setIcon(make_icon(accent))

    def _on_sensors(self, s) -> None:
        if s is not None:
            self._power_w = self._power.push(getattr(s, "system_power_w", None),
                                             getattr(s, "battery_power_w", None), s.battery_status)
        self._update_icon()
        self._refresh_info()

    def _update_icon(self) -> None:
        """Draw the system watts in the tray icon: at most 1x/s and only when the integer changes."""
        sys_w = self._power_w[0]
        want = None
        if sys_w is not None and self.settings.value(KEY_TRAY_WATTS, True, type=bool):
            want = int(round(sys_w))
        if want == self._icon_watts:
            return
        now = self._clock()
        if want is None:
            self._icon_watts = None
            self.icon.setIcon(make_icon(self.state.accent))
        elif now - self._icon_at >= 1.0:
            self._icon_watts, self._icon_at = want, now
            self.icon.setIcon(make_watts_icon(want))
        else:
            return
        self.icon_updates += 1

    def _refresh_info(self) -> None:
        s = self.state.sensors
        mode = PERF_LABEL.get(self.state.perf_mode, "")
        if s is None:
            self.info.setText("Veri yok")
            self.icon.setToolTip(f"ROG Control — {mode}")
            return
        rpm = (s.fans_rpm or {}).get("cpu")
        bat = ""
        if s.battery_pct is not None:
            bat = f" · Pil {s.battery_pct:.0f} %" + (f" {BAT_STATUS.get(s.battery_status or '', '')}" if s.battery_status else "")
        self.info.setText(f"CPU {fmt_num(s.cpu_temp)} °C · Fan {fmt_num(rpm)} rpm{bat}")
        gpu = {"sleep": "Uyku", "off": "Kapalı"}.get(s.gpu_state, f"{fmt_num(s.gpu_temp)} °C")
        tip = f"ROG Control — {mode}\nCPU {fmt_num(s.cpu_temp)} °C · GPU {gpu} · Fan {fmt_num(rpm)} rpm"
        ptxt = compose_power(*self._power_w)
        self.icon.setToolTip(tip + (f"\nGüç: {ptxt}" if ptxt else ""))

    def _on_perf(self, mode: str) -> None:
        self._refresh_perf()
        if (seconds_since_local_perf() > 2.5 and self.settings.value("ui/notify_profile", True, type=bool)
                and self.icon.isVisible()):
            self.icon.showMessage("ROG Control", f"Profil: {PERF_LABEL.get(mode, mode)}",
                                  QSystemTrayIcon.MessageIcon.Information, 3000)
