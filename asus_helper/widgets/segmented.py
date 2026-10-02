"""Segmented control with an animated sliding thumb (matches HTML .seg / .seg-thumb)."""

from __future__ import annotations

from typing import Iterable

from PyQt5.QtCore import (
    QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, pyqtSignal,
)
from PyQt5.QtWidgets import QButtonGroup, QFrame, QPushButton, QWidget


_PAD = 3   # inner padding (matches CSS padding:3px)
_H   = 38  # fixed widget height


class SegmentedControl(QFrame):
    """Exclusive pill control with a sliding accent-coloured thumb.

    Public API is identical to the old QButtonGroup-based version so that
    all existing tab code works without changes:
      • selected(str) signal
      • set_value(opt)
      • value() → str | None
      • set_enabled_values(enabled, names=None)
    """

    selected = pyqtSignal(str)

    def __init__(
        self,
        options: Iterable[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Seg")

        self._options: list[str] = list(options)
        self._value:   str | None = self._options[0] if self._options else None
        self._suppress = False

        # ── thumb (created FIRST → lowest z-order → visually behind buttons) ──
        self._thumb = QFrame(self)
        self._thumb.setObjectName("SegThumb")

        # ── buttons (higher z-order → receive mouse events) ───────────────────
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for opt in self._options:
            btn = QPushButton(opt, self)
            btn.setObjectName("SegOpt")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("selected", opt == self._value)
            self._group.addButton(btn)
            self._buttons[opt] = btn
            btn.clicked.connect(lambda _chk, o=opt: self._on_click(o))

        # ── slide animation on the thumb geometry ─────────────────────────────
        self._anim = QPropertyAnimation(self._thumb, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.setFixedHeight(_H)

    # ── geometry helpers ─────────────────────────────────────────────────────

    def _thumb_rect(self, idx: int) -> QRect:
        n = len(self._options)
        if n == 0:
            return QRect()
        w = self.width()
        usable = w - 2 * _PAD
        btn_w  = max(1, usable // n)
        remainder = usable - btn_w * n
        # distribute remainder: first few buttons get +1 px
        x = _PAD + sum(btn_w + (1 if i < remainder else 0) for i in range(idx))
        bw = btn_w + (1 if idx < remainder else 0)
        return QRect(x, _PAD, bw, _H - 2 * _PAD)

    def _layout_children(self, snap_thumb: bool = True) -> None:
        n = len(self._options)
        if n == 0 or self.width() == 0:
            return
        for i, opt in enumerate(self._options):
            r = self._thumb_rect(i)
            self._buttons[opt].setGeometry(r)

        if snap_thumb and self._value in self._options:
            idx = self._options.index(self._value)
            if self._anim.state() != QPropertyAnimation.Running:
                self._thumb.setGeometry(self._thumb_rect(idx))

    # ── Qt overrides ─────────────────────────────────────────────────────────

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._layout_children()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._layout_children()

    def sizeHint(self) -> QSize:
        n = max(1, len(self._options))
        return QSize(n * 88, _H)

    def minimumSizeHint(self) -> QSize:
        n = max(1, len(self._options))
        return QSize(n * 55, _H)

    # ── interaction ──────────────────────────────────────────────────────────

    def _on_click(self, opt: str) -> None:
        if self._suppress or opt == self._value:
            return
        prev_idx = self._options.index(self._value) if self._value in self._options else 0
        self._value = opt
        self._animate_thumb(opt)
        self._refresh_button_states()
        self.selected.emit(opt)

    def _animate_thumb(self, opt: str, animated: bool = True) -> None:
        if opt not in self._options:
            return
        idx    = self._options.index(opt)
        target = self._thumb_rect(idx)
        if animated and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._thumb.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._thumb.setGeometry(target)

    def _refresh_button_states(self) -> None:
        for opt, btn in self._buttons.items():
            is_sel = opt == self._value
            btn.setProperty("selected", is_sel)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── public API ────────────────────────────────────────────────────────────

    def set_value(self, opt: str | None) -> None:
        if opt not in self._buttons:
            return
        self._suppress = True
        self._value = opt
        self._animate_thumb(opt, animated=False)
        self._refresh_button_states()
        self._suppress = False

    def value(self) -> str | None:
        return self._value

    def set_enabled_values(
        self, enabled: bool, names: Iterable[str] | None = None
    ) -> None:
        target = set(names) if names is not None else set(self._buttons)
        for name, btn in self._buttons.items():
            if name in target:
                btn.setEnabled(enabled)
