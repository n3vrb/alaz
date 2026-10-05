"""Shared building blocks for the top-level windows (frameless shell, title bar, toast, small buttons).

Windows never import backend modules; they read AppState and call Controller only.
"""
from __future__ import annotations

import logging
import re
import time

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget)

from rog_control.i18n import TrMap, tr
from rog_control.ui import theme
from rog_control.ui.widgets._common import IconButton
from rog_control.ui.widgets.icons import draw_icon

log = logging.getLogger(__name__)

# ---- perf-mode vocabulary (PerfMode str <-> label; the Turkish source text is translated on access) ----------------
PERF_KEYS = ("quiet", "balanced", "turbo", "custom")
_PERF_SRC = {"quiet": "Sessiz", "balanced": "Dengeli", "turbo": "Turbo", "custom": "Özel"}
PERF_LABEL = TrMap(_PERF_SRC)
PERF_COLOR = {k: theme.MODE_COLORS[v] for k, v in _PERF_SRC.items()}
# asusd ThrottleThermalPolicy int (backend.types.Profile) -> PerfMode
POLICY_KEY = {0: "balanced", 1: "turbo", 2: "quiet"}
GPU_LABEL = TrMap({"eco": "Eco", "standard": "Standart", "ultimate": "Ultimate", "optimize": "Optimize"})

# Busy keys the controller is expected to emit via AppState.busyChanged(key, bool):
#   "perf" perf-mode tiles + custom power limits   "gpu" GPU tiles / pending card   "refresh" refresh-rate segmented
#   "panel_od" panel overdrive toggle              "battery" charge limit            "fan" fan curve apply/reset
#   "epp" EPP segmented                            "nv" NVIDIA sliders               "auto" AC/battery auto profile chips
#   "kbd" keyboard brightness/colour
BUSY_KEYS = ("perf", "gpu", "refresh", "panel_od", "battery", "fan", "epp", "nv", "auto", "kbd")

def is_quitting() -> bool:
    app = QApplication.instance()
    return bool(app is not None and app.property("rog_quitting"))


def request_quit() -> None:
    """The one way to end the app: mark quitting so every window accepts close, then quit."""
    app = QApplication.instance()
    if app is not None:
        app.setProperty("rog_quitting", True)
        QApplication.quit()


# Keys the real core.Controller emits that the windows group under a UI key.
BUSY_ALIASES = {
    "battery_limit": "battery",
    "auto_profile": "auto",
    "custom": "perf",
    "fan_load": "fan",
    "reboot": "gpu",
}

_LAST_LOCAL_PERF = 0.0


def request_perf(controller, mode: str) -> None:
    """UI-initiated perf change; stamps the time so the tray can tell external (Fn key) changes apart."""
    global _LAST_LOCAL_PERF
    _LAST_LOCAL_PERF = time.monotonic()
    controller.set_perf_mode(mode)


def seconds_since_local_perf() -> float:
    return time.monotonic() - _LAST_LOCAL_PERF


def cpu_model_short(path: str = "/proc/cpuinfo") -> str:
    """'Intel(R) Core(TM) Ultra 9 285H' -> '285H' (read-only /proc access); '' if unknown."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("model name"):
                    name = line.split(":", 1)[1]
                    m = re.findall(r"\b\d{3,5}[A-Z]{0,3}\b", name)
                    return m[-1] if m else ""
    except OSError:
        pass
    return ""


def fmt_num(v, digits: int = 0, dash: str = "—") -> str:
    return dash if v is None else f"{v:.{digits}f}"


class IconLabel(QWidget):
    def __init__(self, name: str, color: str, px: int = 15, stroke: float = 2.2, parent: QWidget | None = None):
        super().__init__(parent)
        self._n, self._c, self._px, self._s = name, color, px, stroke
        self.setFixedSize(px, px)

    def set_color(self, color: str) -> None:
        self._c = color
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_icon(p, self._n, QRectF(0, 0, self._px, self._px), self._c, self._s)


class Dot(QWidget):
    def __init__(self, color: str, d: int = 8, parent: QWidget | None = None):
        super().__init__(parent)
        self._c = color
        self.setFixedSize(d, d)

    def set_color(self, color: str) -> None:
        self._c = color
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._c))
        p.drawEllipse(QRectF(self.rect()))


class Pill(QWidget):
    """Rounded label with a colour dot (title-bar perf indicator)."""

    def __init__(self, text: str = "", color: str = theme.DEFAULT_ACCENT, parent: QWidget | None = None):
        super().__init__(parent)
        self._text, self._color = text, color
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set(self, text: str, color: str) -> None:
        self._text, self._color = text, color
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:
        from PyQt6.QtGui import QFontMetrics
        w = QFontMetrics(theme.ui_font(12, 600)).horizontalAdvance(self._text)
        return QSize(11 + 8 + 7 + w + 11, 26)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.CONTROL))
        p.drawRoundedRect(r, 13, 13)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(QRectF(12, 9, 8, 8))
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.ui_font(12, 600))
        p.drawText(QRectF(27, 0, self.width() - 27, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)


class Panel(QFrame):
    """Card container (PANEL bg, BORDER, radius)."""

    def __init__(self, radius: int = 12, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"Panel {{ background:{theme.PANEL}; border:1px solid {theme.BORDER}; border-radius:{radius}px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.lay.setSpacing(8)


def hline(margin: int = 10) -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{theme.DIVIDER}; border:0")
    return f


def label(text: str = "", px: float = 13, weight: int = 400, color: str = theme.TEXT, rich: bool = False) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"font-size:{px}px; font-weight:{weight}; color:{color}; background:transparent")
    if rich:
        l.setTextFormat(Qt.TextFormat.RichText)
    return l


def section_title(text: str) -> QLabel:
    l = QLabel(text.upper())
    l.setFont(theme.ui_font(11.5, 600, 1.15))
    l.setStyleSheet(f"color:{theme.TEXT2}; background:transparent")
    return l


class ChoiceButton(QAbstractButton):
    """Selectable button: selected = filled with `color`, else CONTROL with border. Optional colour dot (profile tiles)."""

    def __init__(self, text: str, color: str, height: int = 44, radius: int = 10, dot: bool = False,
                 font_px: float = 13, parent: QWidget | None = None):
        super().__init__(parent)
        self._color, self._r, self._dot, self._px = color, radius, dot, font_px
        self._sel = False
        self._hover = False
        self.setText(text)
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def is_selected(self) -> bool:
        return self._sel

    def set_selected(self, on: bool) -> None:
        if on != self._sel:
            self._sel = on
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(80, self.height())

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        col = QColor(self._color)
        if self._sel:
            bg, border, fg, w = col, col, QColor(theme.INK), 600
        else:
            bg = QColor("#272B35") if (self._hover and self.isEnabled()) else QColor(theme.CONTROL)
            border, fg, w = QColor(theme.BORDER), QColor(theme.TEXT_TILE), 500
        if not self.isEnabled():
            p.setOpacity(0.5)
        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, self._r, self._r)
        f = theme.ui_font(self._px, w)
        p.setFont(f)
        from PyQt6.QtGui import QFontMetrics
        tw = QFontMetrics(f).horizontalAdvance(self.text())
        total = tw + (16 if self._dot else 0)
        x = (self.width() - total) / 2
        if self._dot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.INK) if self._sel else col)
            p.drawEllipse(QRectF(x, self.height() / 2 - 4, 8, 8))
            x += 16
        p.setPen(fg)
        p.drawText(QRectF(x, 0, tw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), self._r, self._r)


class NavButton(QAbstractButton):
    """44px bottom-bar button: icon + text (or icon only)."""

    def __init__(self, icon: str, text: str = "", tooltip: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._icon = icon
        self._hover = False
        self._active: str | None = None   # accent colour when the button is "on" (filled)
        self.setText(text)
        self.setToolTip(tooltip)
        self.setAccessibleName(text or tooltip)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if text:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(44)

    def sizeHint(self) -> QSize:
        return QSize(44 if not self.text() else 100, 44)

    def set_active(self, accent: str | None) -> None:
        if accent != self._active:
            self._active = accent
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        from PyQt6.QtGui import QFontMetrics
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._active and self.isEnabled():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self._active).lighter(110) if self._hover else QColor(self._active))
        else:
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.setBrush(QColor("#272B35") if self._hover else QColor(theme.CONTROL))
        p.drawRoundedRect(r, 10, 10)
        f = theme.ui_font(13, 500)
        p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance(self.text()) if self.text() else 0
        total = 16 + (8 + tw if tw else 0)
        x = (self.width() - total) / 2
        fg = theme.INK if (self._active and self.isEnabled()) else theme.TEXT
        draw_icon(p, self._icon, QRectF(x, self.height() / 2 - 8, 16, 16), fg, 1.9)
        if tw:
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(x + 24, 0, tw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 10, 10)


class TitleBar(QWidget):
    """44px bar; dragging it moves the window (compositor-driven)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(16, 0, 8, 0)
        self.lay.setSpacing(10)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self.window().windowHandle()
            if h is not None:
                h.startSystemMove()
                return
        super().mousePressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QColor("#1E2129"))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class Toast(QFrame):
    """Non-modal message strip. info auto-hides after 4 s; warn/error stay until clicked."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self._lab = QLabel(self)
        self._lab.setWordWrap(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.addWidget(self._lab)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def show_message(self, level: str, text: str) -> None:
        col = {"info": theme.TEXT2, "warn": theme.WARN_ACCENT, "error": "#FF5A5F"}.get(level, theme.TEXT2)
        self.setStyleSheet(f"QFrame#toast {{ background:{theme.CONTROL}; border:1px solid {col}; border-radius:10px; }}")
        self._lab.setStyleSheet(f"color:{theme.TEXT}; font-size:12.5px; background:transparent")
        self._lab.setText(text)
        self.level = level
        w = self.parentWidget()
        self.setFixedWidth(w.width() - 32)
        self.adjustSize()
        self.move(16, w.height() - self.height() - 16)
        self.show()
        self.raise_()
        if level == "info":
            self._timer.start(4000)
        else:
            self._timer.stop()

    def reposition(self) -> None:
        w = self.parentWidget()
        if self.isVisible() and w is not None:
            self.setFixedWidth(w.width() - 32)
            self.adjustSize()
            self.move(16, w.height() - self.height() - 16)

    def mousePressEvent(self, e):
        self._timer.stop()
        self.hide()


class FramelessWindow(QWidget):
    """Rounded frameless window: 3px accent strip, optional title bar, content area; follows state.accentChanged."""

    backRequested = pyqtSignal()

    def __init__(self, state, controller, title: str = "", width: int = 480, height: int = 0, back: bool = False,
                 show_title: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.state, self.ctl = state, controller
        self.setObjectName("root")
        self.setWindowTitle(title or "ROG Control")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._accent = state.accent
        self._accent_widgets: list = []
        self._busy: set[str] = set()
        self._radius = 12
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 4, 1, 1)  # 1px border, 3px strip
        outer.setSpacing(0)
        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)
        self.back_btn = None
        if back:
            self.titlebar.lay.setContentsMargins(8, 0, 8, 0)
            self.titlebar.lay.setSpacing(8)
            self.back_btn = IconButton("back", (34, 32), 16, theme.TEXT, 2.2, tr("Ana pencereye dön"))
            self.back_btn.clicked.connect(self._back)
            self.titlebar.lay.addWidget(self.back_btn)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.body = QWidget(self)
        outer.addWidget(self.body, 1)
        self.toast = Toast(self)
        if width and height:
            self.setFixedSize(width, height)
        elif width:
            self.setFixedWidth(width)
        state.accentChanged.connect(self._on_accent)
        state.message.connect(self._on_message)
        state.busyChanged.connect(self._on_busy)

    # ---- title bar helpers
    def add_window_buttons(self, minimize: bool = True) -> None:
        if minimize:
            b = IconButton("minimize", (34, 32), 14, theme.TEXT2, 2.0, tr("Küçült"))
            b.clicked.connect(self.showMinimized)
            self.titlebar.lay.addWidget(b)
        c = IconButton("close", (34, 32), 14, theme.TEXT2, 2.0, tr("Kapat"))
        c.clicked.connect(self.close)
        self.titlebar.lay.addWidget(c)
        self.close_btn = c

    def title_label(self, text: str) -> QLabel:
        l = label(text, 15, 700)
        return l

    def _back(self) -> None:
        self.hide()
        self.backRequested.emit()

    def closeEvent(self, e):
        # secondary windows (with a back button) never end the app: closing returns to the main window.
        # Exception: while the app is quitting, accept — Qt 6 aborts QApplication.quit() if any
        # window ignores its close event, which left the process running after "Çıkış".
        if self.back_btn is not None and not is_quitting():
            e.ignore()
            self._back()
            return
        super().closeEvent(e)

    # ---- accent
    def track_accent(self, *widgets) -> None:
        for w in widgets:
            if hasattr(w, "set_accent"):
                w.set_accent(self._accent)
            self._accent_widgets.append(w)

    def _on_accent(self, accent: str) -> None:
        self._accent = accent
        for w in self._accent_widgets:
            w.set_accent(accent)
        self.accent_applied(accent)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.qss(accent))
        self.update()

    def accent_applied(self, accent: str) -> None:  # hook
        pass

    # ---- busy / messages
    def _on_busy(self, key: str, on: bool) -> None:
        key = BUSY_ALIASES.get(key, key)
        (self._busy.add if on else self._busy.discard)(key)
        self.apply_enabled()

    def apply_enabled(self) -> None:  # hook: recompute widget enabled states from self._busy
        pass

    def is_busy(self, key: str) -> bool:
        return key in self._busy

    def _on_message(self, level: str, text: str) -> None:
        if self.isVisible():
            self.toast.show_message(level, text)

    def showEvent(self, e):
        super().showEvent(e)
        fw = self.focusWidget()
        if fw is not None:  # no initial focus ring on the first title-bar button
            fw.clearFocus()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def resizeEvent(self, e):
        self.toast.reposition()
        super().resizeEvent(e)

    # ---- painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.fillPath(path, QColor(theme.BG))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # strip covers border at top: redraw the accent over the first 3px inside the rounded clip
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, self.width(), 3), QColor(self._accent))
        p.restore()
