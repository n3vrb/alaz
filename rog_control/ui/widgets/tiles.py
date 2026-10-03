"""ModeTile / ModeTileRow — the 76px mode selector tiles (performance and GPU)."""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QSizePolicy, QWidget

from rog_control.i18n import tr
from rog_control.ui import theme
from rog_control.ui.widgets._common import AccentMixin, lerp_color, lighten
from rog_control.ui.widgets.icons import draw_icon

BADGE_OVERHANG = 8  # px the "BEKLİYOR" badge sticks out above the tile body
BODY_H = 76


class ModeTile(QAbstractButton):
    """One tile. The widget is BADGE_OVERHANG px taller than the 76px body so the pending badge is never clipped."""

    def __init__(self, key: str, label: str, icon: str, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.key, self._label, self._icon, self._color = key, label, icon, color
        self._selected = False
        self._pending = False
        self._hover = False
        self._t = 0.0  # selection fade progress
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(BODY_H + BADGE_OVERHANG)
        self.setAccessibleName(label)

    # state -------------------------------------------------------------
    def is_selected(self) -> bool:
        return self._selected

    def is_pending(self) -> bool:
        return self._pending

    def set_selected(self, on: bool, animate: bool = True) -> None:
        if on == self._selected:
            return
        self._selected = on
        target = 1.0 if on else 0.0
        self._anim.stop()
        if animate and self.isVisible():
            self._anim.setStartValue(self._t)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._t = target
            QWidget.update(self)

    def set_pending(self, on: bool) -> None:
        if on != self._pending:
            self._pending = on
            QWidget.update(self)

    def set_color(self, color: str) -> None:
        self._color = color
        QWidget.update(self)

    def set_tile_enabled(self, enabled: bool, tooltip: str = "") -> None:
        self.setEnabled(enabled)
        self.setToolTip("" if enabled else tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ForbiddenCursor)

    def _on_anim(self, v) -> None:
        self._t = float(v)
        QWidget.update(self)

    def sizeHint(self) -> QSize:
        return QSize(100, BODY_H + BADGE_OVERHANG)

    def enterEvent(self, e):
        self._hover = True
        QWidget.update(self)

    def leaveEvent(self, e):
        self._hover = False
        QWidget.update(self)

    # paint -------------------------------------------------------------
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        col = QColor(self._color)
        body = QRectF(0, BADGE_OVERHANG, self.width(), BODY_H)
        t = self._t
        pending = self._pending and t < 0.5
        bg = lerp_color(theme.CONTROL, col, t)
        border = lerp_color(theme.BORDER, col, t)
        fg = lerp_color(col if pending else theme.TEXT_TILE, theme.INK, t)
        if self._hover and self.isEnabled():
            bg, border = lighten(bg, 112), lighten(border, 112)
        weight = 600 if (t > 0.5 or pending) else 500
        # body
        if pending:
            pen = QPen(col, 2, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 3])
            p.setPen(pen)
            p.setBrush(bg)
            p.drawRoundedRect(body.adjusted(1, 1, -1, -1), 11, 11)
        else:
            p.setPen(QPen(border, 1))
            p.setBrush(bg)
            p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), 11.5, 11.5)
        # icon + label (24px icon, 7px gap, label)
        f = theme.ui_font(13, weight)
        p.setFont(f)
        fm = p.fontMetrics()
        total = 24 + 7 + fm.height()
        top = body.top() + (BODY_H - total) / 2
        draw_icon(p, self._icon, QRectF((self.width() - 24) / 2, top, 24, 24), fg, 1.9)
        p.setPen(fg)
        p.drawText(QRectF(0, top + 24 + 7, self.width(), fm.height()), Qt.AlignmentFlag.AlignCenter, self._label)
        # check mark
        if t > 0.02:
            p.setOpacity(p.opacity() * min(1.0, t))
            draw_icon(p, "check", QRectF(self.width() - 7 - 14, body.top() + 7, 14, 14), theme.INK, 3.0)
            p.setOpacity(0.4 if not self.isEnabled() else 1.0)
        # pending badge
        if self._pending and not self._selected:
            bf = theme.ui_font(10, 700, 0.4)
            p.setFont(bf)
            txt = tr("BEKLİYOR")
            w = p.fontMetrics().horizontalAdvance(txt) + 12
            r = QRectF((self.width() - w) / 2, 0, w, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor(theme.INK))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)
        # focus ring
        if self.hasFocus():
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(theme.TEXT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(body.adjusted(-1, -1, 1, 1), 13, 13)


class ModeTileRow(QWidget, AccentMixin):
    """Row of exclusive mode tiles. options: [(key, label, icon_name, color_hex), ...]."""

    clicked = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str, str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._tiles: dict[str, ModeTile] = {}
        for key, label, icon, color in options:
            t = ModeTile(key, label, icon, color, self)
            t.clicked.connect(lambda _=False, k=key: self.clicked.emit(k))
            lay.addWidget(t, 1)
            self._tiles[key] = t
        self._selected: str | None = None
        self._pending: str | None = None
        self.setFixedHeight(BODY_H + BADGE_OVERHANG)

    def keys(self) -> list[str]:
        return list(self._tiles)

    def tile(self, key: str) -> ModeTile:
        return self._tiles[key]

    def selected(self) -> str | None:
        return self._selected

    def pending(self) -> str | None:
        return self._pending

    def set_selected(self, key: str | None) -> None:
        self._selected = key
        for k, t in self._tiles.items():
            t.set_selected(k == key)
        if self._pending == key:
            self.set_pending(None)

    def set_pending(self, key: str | None) -> None:
        self._pending = key if key in self._tiles else None
        for k, t in self._tiles.items():
            t.set_pending(k == self._pending and k != self._selected)

    def set_enabled(self, key: str, enabled: bool, tooltip: str = "") -> None:  # type: ignore[override]
        if key in self._tiles:
            self._tiles[key].set_tile_enabled(enabled, tooltip)

    def is_enabled(self, key: str) -> bool:
        return self._tiles[key].isEnabled()
