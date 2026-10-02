"""KeyboardWindow: backlight brightness, static colour (16 swatches + hex)."""
from __future__ import annotations

import logging
import re

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from rog_control.ui import theme
from rog_control.ui.widgets import Segmented, make_button
from rog_control.ui.widgets._common import button_qss
from rog_control.ui.windows._base import FramelessWindow, Panel, label, section_title

log = logging.getLogger(__name__)

SWATCHES = ["#FF5A5F", "#FF8A3D", "#F2A93B", "#FFD84D", "#B6E04A", "#34C08A", "#2BD4C0", "#3DB9FF",
            "#4C8DFF", "#7A6CFF", "#B26CFF", "#E066FF", "#FF66B8", "#FFFFFF", "#C9CED8", "#8F96A3"]
BRIGHTNESS = (("0", "Kapalı"), ("1", "Düşük"), ("2", "Orta"), ("3", "Yüksek"))
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_hex(text: str) -> tuple[int, int, int] | None:
    m = HEX_RE.match(text.strip())
    if not m:
        return None
    v = m.group(1)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


class Swatch(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.color = color
        self._sel = False
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(color)
        self.setToolTip(color)

    def set_selected(self, on: bool) -> None:
        if on != self._sel:
            self._sel = on
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.color)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.color)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(r, 8, 8)
        if self._sel or self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 9, 9)


class KeyboardWindow(FramelessWindow):
    def __init__(self, state, controller, parent: QWidget | None = None):
        super().__init__(state, controller, "ROG Control — Klavye", 480, 350, back=True, parent=parent)
        tb = self.titlebar.lay
        tb.addWidget(self.title_label("Klavye"))
        tb.addStretch(1)
        self.add_window_buttons(minimize=False)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(14)

        lay.addWidget(section_title("Parlaklık"))
        bp = Panel(12)
        self.bright = Segmented([(k, t) for k, t in BRIGHTNESS], height=32, stretch=True)
        self.bright.changed.connect(lambda k: self.ctl.set_kbd_brightness(int(k)))
        bp.lay.addWidget(self.bright)
        lay.addWidget(bp)

        lay.addWidget(section_title("Renk"))
        cp = Panel(12)
        cp.lay.setSpacing(12)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.swatches: list[Swatch] = []
        for i, c in enumerate(SWATCHES):
            s = Swatch(c)
            s.clicked.connect(self._pick)
            grid.addWidget(s, i // 8, i % 8)
            self.swatches.append(s)
        cp.lay.addLayout(grid)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.preview = QWidget()
        self.preview.setFixedSize(34, 34)
        row.addWidget(self.preview)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setPlaceholderText("#RRGGBB")
        self.hex.setFixedHeight(34)
        self.hex.setAccessibleName("Renk (hex)")
        self.hex.textChanged.connect(self._hex_changed)
        self.hex.returnPressed.connect(self._apply)
        row.addWidget(self.hex, 1)
        self.apply_btn = make_button("Uygula", "primary", self._accent, pad=16)
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn)
        cp.lay.addLayout(row)
        lay.addWidget(cp)
        lay.addStretch(1)

        self.track_accent(self.bright)
        state.auraChanged.connect(lambda _v: self._refresh())
        self._refresh()

    def accent_applied(self, accent: str) -> None:
        self.apply_btn.setStyleSheet(button_qss(accent, theme.INK, None, weight=600, pad=16))

    def _refresh(self) -> None:
        a = self.state.aura
        self.bright.set_current(str(a.brightness) if a.brightness is not None else None)
        if a.color is not None:
            hx = to_hex(a.color)
            if not self.hex.hasFocus():
                self.hex.setText(hx)
        self._mark(a.color)
        self.apply_enabled()

    def _mark(self, rgb) -> None:
        cur = to_hex(rgb) if rgb else None
        for s in self.swatches:
            s.set_selected(cur is not None and s.color.upper() == cur)

    def _pick(self, color: str) -> None:
        self.hex.setText(color)
        self._apply()

    def _hex_changed(self, text: str) -> None:
        rgb = parse_hex(text)
        ok = rgb is not None
        self.hex.setStyleSheet(
            f"QLineEdit {{ background:{theme.CONTROL}; border:1px solid {theme.BORDER if ok or not text else '#FF5A5F'};"
            f" border-radius:8px; padding:0 10px; color:{theme.TEXT}; font-size:13px; }}"
            f"QLineEdit:focus {{ border-color:{self._accent}; }}")
        self.preview.setStyleSheet(f"background:{to_hex(rgb) if ok else theme.CONTROL}; border-radius:8px;"
                                   f" border:1px solid {theme.BORDER};")
        self.apply_enabled()

    def _apply(self) -> None:
        rgb = parse_hex(self.hex.text())
        if rgb is not None and not self.is_busy("kbd"):
            self.ctl.set_kbd_color(rgb)

    def apply_enabled(self) -> None:
        busy = self.is_busy("kbd")
        self.bright.setEnabled(not busy)
        self.apply_btn.setEnabled(not busy and parse_hex(self.hex.text()) is not None)
        for s in self.swatches:
            s.setEnabled(not busy)
        self.hex.setEnabled(not busy)
