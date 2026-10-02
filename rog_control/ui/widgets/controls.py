"""Segmented, ToggleSwitch, ValueSlider."""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QVBoxLayout, QWidget

from rog_control.ui import theme
from rog_control.ui.widgets._common import AccentMixin, lerp_color


class Segmented(QWidget, AccentMixin):
    """Exclusive segmented control. items: [(key, label)] or [(key, label, suffix)] (suffix drawn lighter, e.g. rpm)."""

    changed = pyqtSignal(str)

    def __init__(self, items: list[tuple], height: int = 30, font_px: float = 12.5, pad: int = 12,
                 stretch: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._items = [(i[0], i[1], i[2] if len(i) > 2 else "") for i in items]
        self._h, self._font_px, self._pad, self._stretch = height, font_px, pad, stretch
        self._current: str | None = None
        self._hover: int = -1
        self._enabled_keys: set[str] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        pol = QSizePolicy.Policy.Expanding if stretch else QSizePolicy.Policy.Fixed
        self.setSizePolicy(pol, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(height + 8)  # 3px padding + 1px border each side

    # API
    def current(self) -> str | None:
        return self._current

    def set_current(self, key: str | None, emit: bool = False) -> None:
        if key != self._current:
            self._current = key
            super().update()
            if emit and key is not None:
                self.changed.emit(key)

    def set_item_suffix(self, key: str, suffix: str) -> None:
        self._items = [(k, l, suffix if k == key else s) for k, l, s in self._items]
        self.updateGeometry()
        super().update()

    def set_item_enabled(self, key: str, on: bool) -> None:
        keys = self._enabled_keys if self._enabled_keys is not None else {k for k, _, _ in self._items}
        keys.add(key) if on else keys.discard(key)
        self._enabled_keys = keys
        super().update()

    # geometry
    def _widths(self) -> list[float]:
        fm = QFontMetrics(theme.ui_font(self._font_px, 600))
        sfm = QFontMetrics(theme.ui_font(self._font_px - 1, 400))
        out = []
        for _, label, suffix in self._items:
            w = fm.horizontalAdvance(label) + 2 * self._pad
            if suffix:
                w += sfm.horizontalAdvance(" " + suffix)
            out.append(float(w))
        return out

    def _rects(self) -> list[QRectF]:
        inner = QRectF(4, 4, self.width() - 8, self._h)
        widths = self._widths()
        n = len(widths)
        if self._stretch and n:
            w = (inner.width() - 2 * (n - 1)) / n
            widths = [w] * n
        x, rects = inner.left(), []
        for w in widths:
            rects.append(QRectF(x, inner.top(), w, inner.height()))
            x += w + 2
        return rects

    def sizeHint(self) -> QSize:
        w = sum(self._widths()) + 2 * max(0, len(self._items) - 1) + 8
        return QSize(int(w), self._h + 8)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _ok(self, key: str) -> bool:
        return self._enabled_keys is None or key in self._enabled_keys

    def _index_at(self, pos) -> int:
        for i, r in enumerate(self._rects()):
            if r.contains(pos.x(), pos.y()):
                return i
        return -1

    # events
    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        if i != self._hover:
            self._hover = i
            super().update()

    def leaveEvent(self, e):
        self._hover = -1
        super().update()

    def mousePressEvent(self, e):
        i = self._index_at(e.position())
        if i >= 0 and self._ok(self._items[i][0]):
            self.set_current(self._items[i][0], emit=True)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            keys = [k for k, _, _ in self._items if self._ok(k)]
            if not keys:
                return
            cur = keys.index(self._current) if self._current in keys else -1
            nxt = keys[max(0, min(len(keys) - 1, cur + (1 if e.key() == Qt.Key.Key_Right else -1)))]
            self.set_current(nxt, emit=True)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.DIVIDER), 1))
        p.setBrush(QColor(theme.BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        for i, ((key, label, suffix), r) in enumerate(zip(self._items, self._rects())):
            sel = key == self._current
            ok = self._ok(key)
            p.setOpacity(1.0 if ok else 0.4)
            if sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(self._accent))
                p.drawRoundedRect(r, 7, 7)
            elif i == self._hover and ok:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.CONTROL))
                p.drawRoundedRect(r, 7, 7)
            fg = QColor(theme.INK if sel else theme.TEXT2)
            main_f = theme.ui_font(self._font_px, 600 if sel else 500)
            p.setFont(main_f)
            p.setPen(fg)
            if suffix:
                sf = theme.ui_font(self._font_px - 1, 400)
                mw = QFontMetrics(main_f).horizontalAdvance(label)
                sw = QFontMetrics(sf).horizontalAdvance(" " + suffix)
                x = r.left() + (r.width() - mw - sw) / 2
                p.drawText(QRectF(x, r.top(), mw, r.height()), Qt.AlignmentFlag.AlignVCenter, label)
                p.setFont(sf)
                p.setOpacity(p.opacity() * 0.75)
                p.drawText(QRectF(x + mw, r.top(), sw, r.height()), Qt.AlignmentFlag.AlignVCenter, " " + suffix)
            else:
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)


class ToggleSwitch(QWidget, AccentMixin):
    """Row with optional label + sublabel and a 40x22 switch. The whole row (label, knob, track) toggles."""

    toggled = pyqtSignal(bool)
    TRACK_W, TRACK_H = 40, 22

    def __init__(self, label: str = "", sublabel: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._label, self._sub = label, sublabel
        self._checked = False
        self._pos = 0.0
        self._hover = False
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(self._on_anim)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(36 if sublabel else 28)
        self.setAccessibleName(label)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool, emit: bool = False) -> None:
        on = bool(on)
        if on == self._checked:
            return
        self._checked = on
        self._anim.stop()
        if self.isVisible():
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(1.0 if on else 0.0)
            self._anim.start()
        else:
            self._pos = 1.0 if on else 0.0
        QWidget.update(self)
        if emit:
            self.toggled.emit(on)

    def toggle(self) -> None:
        self.setChecked(not self._checked, emit=True)

    def set_texts(self, label: str, sublabel: str = "") -> None:
        self._label, self._sub = label, sublabel
        self.setAccessibleName(label)
        QWidget.update(self)

    def _on_anim(self, v):
        self._pos = float(v)
        QWidget.update(self)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(theme.ui_font(13, 500))
        return QSize(fm.horizontalAdvance(self._label) + self.TRACK_W + 16, self.height())

    def _track_rect(self) -> QRectF:
        return QRectF(self.width() - self.TRACK_W, (self.height() - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H)

    # Any click inside the widget (label, track or knob) toggles.
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled() and self.rect().contains(e.position().toPoint()):
            self.toggle()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
        else:
            super().keyPressEvent(e)

    def enterEvent(self, e):
        self._hover = True
        QWidget.update(self)

    def leaveEvent(self, e):
        self._hover = False
        QWidget.update(self)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        # texts
        if self._label:
            right = self.width() - self.TRACK_W - 10
            if self._sub:
                p.setFont(theme.ui_font(13, 500))
                p.setPen(QColor(theme.TEXT))
                p.drawText(QRectF(0, 1, right, 18), Qt.AlignmentFlag.AlignVCenter, self._label)
                p.setFont(theme.ui_font(11.5, 400))
                p.setPen(QColor(theme.TEXT3))
                p.drawText(QRectF(0, 18, right, 16), Qt.AlignmentFlag.AlignVCenter, self._sub)
            else:
                p.setFont(theme.ui_font(13, 500))
                p.setPen(QColor(theme.TEXT))
                p.drawText(QRectF(0, 0, right, self.height()), Qt.AlignmentFlag.AlignVCenter, self._label)
        tr = self._track_rect()
        t = self._pos
        track = lerp_color(theme.BORDER, self._accent, t)
        if self._hover:
            track = track.lighter(112)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(tr, 11, 11)
        knob_x = tr.left() + 3 + 18 * t
        p.setBrush(lerp_color(theme.TEXT2, theme.INK, t))
        p.drawEllipse(QRectF(knob_x, tr.top() + 3, 16, 16))
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(tr.adjusted(-2, -2, 2, 2), 13, 13)


class _NoWheelSlider(QSlider):
    """QSlider that never reacts to the mouse wheel: the event goes to the parent (e.g. a scroll area)."""

    def wheelEvent(self, e):
        e.ignore()


class ValueSlider(QWidget, AccentMixin):
    """label + sublabel | slider | value text with unit. `valueChanged` while dragging, `committed` on release/keys."""

    valueChanged = pyqtSignal(int)
    committed = pyqtSignal(int)

    def __init__(self, label: str = "", sublabel: str = "", minimum: int = 0, maximum: int = 100, step: int = 1,
                 unit: str = "", label_width: int = 92, value_width: int = 54, value_px: float = 15,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._min, self._max, self._step, self._unit = minimum, maximum, step, unit
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._label = QLabel(label)
        self._sub = QLabel(sublabel)
        self._label.setStyleSheet(f"font-size:13px; font-weight:500; color:{theme.TEXT}; background:transparent")
        self._sub.setStyleSheet(f"font-size:11px; color:{theme.TEXT3}; background:transparent")
        self._sub.setVisible(bool(sublabel))
        self._label_box = QWidget()
        col = QVBoxLayout(self._label_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._label)
        col.addWidget(self._sub)
        if label_width:
            self._label_box.setFixedWidth(label_width)
        lay.addWidget(self._label_box)
        self._slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self._slider.setFocusPolicy(Qt.FocusPolicy.ClickFocus)   # no wheel focus; keys work once clicked/tabbed
        self._slider.setRange(0, (maximum - minimum) // step)
        self._slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self._slider.setAccessibleName(label)
        lay.addWidget(self._slider, 1)
        self._value = QLabel()
        self._value.setFixedWidth(value_width)
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._value.setStyleSheet(f"font-size:{value_px}px; font-weight:600; color:{theme.TEXT}; background:transparent")
        lay.addWidget(self._value)
        self._slider.valueChanged.connect(self._on_changed)
        self._slider.sliderReleased.connect(lambda: self.committed.emit(self.value()))
        self._slider.actionTriggered.connect(self._on_action)
        self._block = False
        self._accent_changed()
        self._refresh_text()

    def value(self) -> int:
        return self._min + self._slider.value() * self._step

    def setValue(self, v: int, emit: bool = False) -> None:
        v = max(self._min, min(self._max, int(v)))
        idx = round((v - self._min) / self._step)
        self._block = not emit
        try:
            self._slider.setValue(idx)
        finally:
            self._block = False
        self._refresh_text()

    def is_dragging(self) -> bool:
        return self._slider.isSliderDown()

    def set_value_if_idle(self, v: int) -> bool:
        """Programmatic update that never fights an in-progress drag. Returns True if applied."""
        if self._slider.isSliderDown():
            return False
        self.setValue(v)
        return True

    def set_range(self, minimum: int, maximum: int, sublabel: str | None = None) -> None:
        cur = self.value()
        self._min, self._max = minimum, maximum
        self._slider.setRange(0, (maximum - minimum) // self._step)
        if sublabel is not None:
            self._sub.setText(sublabel)
            self._sub.setVisible(bool(sublabel))
        self.setValue(cur)

    def slider(self) -> QSlider:
        return self._slider

    def _refresh_text(self) -> None:
        self._value.setText(f"{self.value()}{self._unit}")

    def _on_changed(self, _):
        self._refresh_text()
        if not self._block:
            self.valueChanged.emit(self.value())

    def _on_action(self, action):
        # keyboard / page steps are discrete: commit right after the value changes (wheel is ignored entirely)
        if not self._slider.isSliderDown():
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.committed.emit(self.value()))

    def _accent_changed(self) -> None:
        a = self._accent
        self._slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ height:4px; background:{theme.BORDER}; border-radius:2px; }}"
            f"QSlider::sub-page:horizontal {{ background:{a}; border-radius:2px; }}"
            f"QSlider::handle:horizontal {{ background:{a}; width:14px; height:14px; margin:-5px 0; border-radius:7px;"
            f" border:2px solid {theme.BG}; }}"
            f"QSlider::handle:horizontal:hover {{ background:{QColor(a).lighter(115).name()}; }}"
            f"QSlider:disabled {{ }} QSlider::handle:horizontal:disabled {{ background:{theme.TEXT3}; }}")
