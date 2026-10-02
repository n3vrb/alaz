"""Animated pill toggle switch + label row."""

from __future__ import annotations

from PyQt5.QtCore import (
    QEasingCurve, QEvent, QPropertyAnimation, QRectF,
    Qt, pyqtProperty, pyqtSignal,
)
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..theme import ACCENT, BG_IN, BORDER, TX2


class ToggleSwitch(QWidget):
    """34×18 px animated pill switch — matches the HTML .tog element."""

    _W, _H, _PAD = 34, 18, 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self.__pos = 0.0          # 0.0 = off  /  1.0 = on

        self._anim = QPropertyAnimation(self, b"knobPos")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.PointingHandCursor)

    # ── animatable property ──────────────────────────────────────────────
    def _get_pos(self) -> float:
        return self.__pos

    def _set_pos(self, v: float) -> None:
        self.__pos = v
        self.update()

    knobPos = pyqtProperty(float, _get_pos, _set_pos)

    # ── public API ───────────────────────────────────────────────────────
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool, animated: bool = False) -> None:
        self._checked = on
        target = 1.0 if on else 0.0
        if animated and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self.__pos)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.__pos = target
            self.update()

    # ── events ───────────────────────────────────────────────────────────
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.setChecked(not self._checked, animated=True)

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self._W, self._H
        r = h / 2.0

        # Track
        if self._checked:
            track_col  = QColor(ACCENT)
            border_col = QColor(ACCENT)
        else:
            track_col  = QColor(BG_IN)
            border_col = QColor(BORDER)

        p.setPen(QPen(border_col, 1.5))
        p.setBrush(QBrush(track_col))
        p.drawRoundedRect(QRectF(0.75, 0.75, w - 1.5, h - 1.5), r, r)

        # Knob
        kd = h - 2 * self._PAD - 2
        kr = kd / 2.0
        travel = w - 2 - kd - 2 * self._PAD
        kx = 1 + self._PAD + kr + self.__pos * travel
        ky = h / 2.0

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(kx - kr, ky - kr, kd, kd))


class ToggleRow(QWidget):
    """ToggleSwitch + text label — entire row is clickable like the HTML tog-row."""

    toggled = pyqtSignal(bool)

    def __init__(self, label: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self._sw = ToggleSwitch()
        lbl = QLabel(label)
        lbl.setObjectName("TogLabel")
        lbl.installEventFilter(self)   # forward label clicks

        lay.addWidget(self._sw)
        lay.addWidget(lbl)
        lay.addStretch()

    # ── event filter on the label ────────────────────────────────────────
    def eventFilter(self, obj, e) -> bool:
        if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            self._click()
            return True
        return super().eventFilter(obj, e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._click()

    def _click(self) -> None:
        new = not self._sw.isChecked()
        self._sw.setChecked(new, animated=True)
        if not self.signalsBlocked():
            self.toggled.emit(new)

    # ── public API ───────────────────────────────────────────────────────
    def isChecked(self) -> bool:
        return self._sw.isChecked()

    def setChecked(self, on: bool, animated: bool = False) -> None:
        self._sw.setChecked(on, animated)
