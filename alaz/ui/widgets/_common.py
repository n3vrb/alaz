"""Shared helpers for the widget library (no backend imports)."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractButton, QPushButton, QSizePolicy, QWidget

from alaz.ui import theme
from alaz.ui.widgets.icons import draw_icon


def lerp_color(a: str | QColor, b: str | QColor, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
        round(ca.alpha() + (cb.alpha() - ca.alpha()) * t),
    )


def lighten(c: str | QColor, pct: int = 112) -> QColor:
    return QColor(c).lighter(pct)


def strong(text: str, color: str = theme.TEXT) -> str:
    """Rich-text bold span, as used in the mockups' right-hand header values."""
    return f'<b style="color:{color}; font-weight:600">{text}</b>'


class AccentMixin:
    """Gives a widget `set_accent(hex)` / `accent`; subclasses override `_accent_changed`."""

    _accent: str = theme.DEFAULT_ACCENT

    @property
    def accent(self) -> str:
        return self._accent

    def set_accent(self, hex_color: str) -> None:
        if hex_color and hex_color != self._accent:
            self._accent = hex_color
            self._accent_changed()
            QWidget.update(self)  # type: ignore[arg-type]

    def _accent_changed(self) -> None:  # hook
        pass


def button_qss(bg: str, fg: str, border: str | None = None, radius: int = 8, weight: int = 500,
               size: float = 13, hover_bg: str | None = None, pad: int = 14) -> str:
    hb = hover_bg or lighten(bg).name()
    b = f"1px solid {border}" if border else "0"
    return (f"QPushButton {{ background: {bg}; color: {fg}; border: {b}; border-radius: {radius}px; "
            f"font-size: {size}px; font-weight: {weight}; padding: 0 {pad}px; }}"
            f"QPushButton:hover {{ background: {hb}; }}"
            f"QPushButton:focus {{ border: 2px solid {theme.TEXT}; }}")


def make_button(text: str, kind: str = "secondary", color: str = theme.DEFAULT_ACCENT, height: int = 34,
                pad: int = 14, parent: QWidget | None = None) -> QPushButton:
    """kind: primary (filled with `color`, ink text) | secondary (control bg, border) | ghost (outlined, transparent)."""
    b = QPushButton(text, parent)
    b.setFixedHeight(height)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if kind == "primary":
        b.setStyleSheet(button_qss(color, theme.INK, None, weight=600, pad=pad))
    elif kind == "ghost":
        b.setStyleSheet(button_qss("transparent", theme.TEXT, theme.BORDER, hover_bg=theme.CONTROL, pad=pad))
    else:
        b.setStyleSheet(button_qss(theme.CONTROL, theme.TEXT, theme.BORDER, pad=pad))
    return b


class IconButton(QAbstractButton):
    """Borderless icon button (title-bar buttons, banner close)."""

    def __init__(self, icon: str, size: tuple[int, int] = (34, 32), icon_px: int = 14, color: str = theme.TEXT2,
                 stroke: float = 2.0, tooltip: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._icon, self._px, self._color, self._stroke = icon, icon_px, color, stroke
        self._hover = False
        self.setFixedSize(*size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)

    def set_icon_color(self, color: str) -> None:
        self._color = color
        super().update()

    def enterEvent(self, e):
        self._hover = True
        super().update()

    def leaveEvent(self, e):
        self._hover = False
        super().update()

    def sizeHint(self) -> QSize:
        return self.size()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover or self.isDown():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.CONTROL))
            p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        if self.hasFocus():
            p.setPen(QColor(theme.TEXT))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        r = QRectF(0, 0, self._px, self._px)
        r.moveCenter(QRectF(self.rect()).center())
        draw_icon(p, self._icon, r, self._color, self._stroke)
