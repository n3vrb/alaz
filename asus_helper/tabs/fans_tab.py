from __future__ import annotations

from typing import Sequence

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import backend
from ..widgets.card import Card
from ..widgets.segmented import SegmentedControl


CURVE_COLOR       = "#5080f0"          # matches HTML accent
CURVE_COLOR_OFF   = "#333348"          # when curve disabled
FILL_COLOR        = "rgba(80,128,240,0.09)"
FILL_COLOR_OFF    = "rgba(255,255,255,0.02)"
POINT_COLOR       = "#ffffff"
POINT_COLOR_OFF   = "#444455"

TEMP_MIN, TEMP_MAX = 0, 110
PWM_MIN, PWM_MAX = 0, 100


class DraggableCurve(pg.GraphItem):
    """A pg.GraphItem whose nodes are draggable and stay sorted by X."""

    def __init__(self, on_change=None) -> None:
        self._drag_index: int | None = None
        self._drag_offset = None
        self._on_change = on_change
        super().__init__()
        # Style: small white dots, blue line.
        self.scatter.setSymbol("o")

    # PyQt signals can't live on non-QObject GraphItem reliably across versions;
    # use a plain callback instead.
    def set_on_change(self, callback) -> None:
        self._on_change = callback

    def set_points(
        self, points: Sequence[tuple[int, int]], enabled: bool = True
    ) -> None:
        """Replace all 8 points. points is a list of (temp, pwm)."""
        pts = sorted(((int(t), int(p)) for t, p in points), key=lambda xy: xy[0])
        pos = np.array(pts, dtype=float)
        n   = len(pos)
        adj = (
            np.column_stack([np.arange(n - 1), np.arange(1, n)])
            if n > 1 else np.empty((0, 2), int)
        )
        line  = CURVE_COLOR if enabled else CURVE_COLOR_OFF
        point = POINT_COLOR if enabled else POINT_COLOR_OFF
        symbol_brush = pg.mkBrush(point)
        symbol_pen   = pg.mkPen("#0d0d11", width=1)
        line_pen     = pg.mkPen(line, width=2.5)
        super().setData(
            pos=pos, adj=adj,
            size=12, symbol="o", pxMode=True,
            pen=line_pen,
            symbolBrush=symbol_brush,
            symbolPen=symbol_pen,
            data=np.arange(n),
        )

    def points(self) -> list[tuple[int, int]]:
        if self.data is None or "pos" not in self.data or self.data["pos"] is None:
            return []
        return [(int(round(t)), int(round(p))) for t, p in self.data["pos"]]

    # ---- dragging ----
    def mouseDragEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            ev.ignore()
            return
        if ev.isStart():
            pos = ev.buttonDownPos()
            pts = self.scatter.pointsAt(pos)
            if not pts:
                ev.ignore()
                return
            try:
                idx = int(pts[0].data())
            except Exception:
                ev.ignore()
                return
            self._drag_index = idx
            self._drag_offset = self.data["pos"][idx] - np.array([pos.x(), pos.y()])
        elif ev.isFinish():
            self._drag_index = None
            self._drag_offset = None
            if self._on_change is not None:
                self._on_change()
            return
        else:
            if self._drag_index is None:
                ev.ignore()
                return
            new = np.array([ev.pos().x(), ev.pos().y()]) + self._drag_offset
            x = float(np.clip(new[0], TEMP_MIN, TEMP_MAX))
            y = float(np.clip(new[1], PWM_MIN, PWM_MAX))
            idx = self._drag_index
            # Constrain X between neighbors so the curve stays monotonic.
            if idx > 0:
                x = max(x, float(self.data["pos"][idx - 1][0]) + 1)
            if idx < len(self.data["pos"]) - 1:
                x = min(x, float(self.data["pos"][idx + 1][0]) - 1)
            self.data["pos"][idx] = [round(x), round(y)]
            self.updateGraph()
        ev.accept()


class FansTab(QWidget):
    def __init__(self, capabilities: backend.Capabilities, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caps = capabilities
        self._current_profile_label = "Balanced"
        self._current_fan = "cpu"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 0)
        outer.setSpacing(10)

        outer.addWidget(self._build_selector_card())
        outer.addWidget(self._build_plot_card(), 1)

        # Action bar — styled like the HTML .abar
        abar = QWidget()
        abar.setStyleSheet(
            "QWidget { background:#14141b; border-top:1px solid #272736; }"
        )
        abar_lay = QHBoxLayout(abar)
        abar_lay.setContentsMargins(14, 12, 14, 12)
        abar_lay.setSpacing(8)
        abar_lay.addStretch()
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.clicked.connect(self.reload)
        self._reset_btn  = QPushButton("Reset to default")
        self._reset_btn.clicked.connect(self._on_reset)
        self._apply_btn  = QPushButton("Apply")
        self._apply_btn.setObjectName("Primary")
        self._apply_btn.clicked.connect(self._on_apply)
        for btn in (self._reload_btn, self._reset_btn, self._apply_btn):
            abar_lay.addWidget(btn)
        outer.addWidget(abar)

        if not self._caps.asusd_available:
            self.setDisabled(True)

        self.reload()

    def _build_selector_card(self) -> Card:
        card = Card("Curve")

        prof_row = QHBoxLayout()
        prof_row.setSpacing(10)
        prof_label = QLabel("Profile")
        prof_label.setFixedWidth(48)
        prof_row.addWidget(prof_label)
        self._profile_seg = SegmentedControl(["Silent", "Balanced", "Turbo"])
        self._profile_seg.set_value("Balanced")
        self._profile_seg.selected.connect(self._on_profile_changed)
        prof_row.addWidget(self._profile_seg, 1)
        card.add_layout(prof_row)

        fan_row = QHBoxLayout()
        fan_row.setSpacing(10)
        fan_label = QLabel("Fan")
        fan_label.setFixedWidth(48)
        fan_row.addWidget(fan_label)
        self._fan_seg = SegmentedControl(["CPU", "GPU", "MID"])
        self._fan_seg.set_value("CPU")
        self._fan_seg.selected.connect(self._on_fan_changed)
        fan_row.addWidget(self._fan_seg)
        fan_row.addStretch()
        self._enabled_cb = QCheckBox("Curve enabled")
        self._enabled_cb.stateChanged.connect(self._on_enable_toggle)
        fan_row.addWidget(self._enabled_cb)
        card.add_layout(fan_row)
        return card

    def _build_plot_card(self) -> Card:
        card = Card("Fan Curve")

        # "— enable to edit" hint next to the title (matches HTML)
        self._edit_hint = QLabel("— enable to edit")
        self._edit_hint.setStyleSheet(
            "font-size:9px; color:#5080f0; background:transparent; "
            "font-weight:400; letter-spacing:0;"
        )
        self._edit_hint.setVisible(True)
        card.add_header_widget(self._edit_hint)

        pg.setConfigOptions(antialias=True, foreground="#4a4a62")
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#14141b")   # BG_CARD
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.hideButtons()
        self._plot.setMenuEnabled(False)
        self._plot.setXRange(TEMP_MIN, TEMP_MAX, padding=0)
        self._plot.setYRange(PWM_MIN, PWM_MAX, padding=0)
        self._plot.setLabel("bottom", "Temperature (°C)")
        self._plot.setLabel("left", "Fan (%)")
        self._plot.showGrid(x=True, y=True, alpha=0.05)

        self._fill_item = pg.FillBetweenItem(None, None)
        self._curve = DraggableCurve()
        self._curve.set_on_change(lambda: None)
        self._plot.addItem(self._curve)
        card.add(self._plot, stretch=1)
        return card


    # ----- callbacks -----
    def _on_profile_changed(self, label: str) -> None:
        self._current_profile_label = label
        self.reload()

    def _on_fan_changed(self, label: str) -> None:
        self._current_fan = label.lower()
        self.reload()

    def _on_enable_toggle(self, _state: int) -> None:
        en = self._enabled_cb.isChecked()
        # Update "— enable to edit" hint visibility
        self._edit_hint.setVisible(not en)
        # Redraw curve in the right colour
        pts = self._curve.points()
        if pts:
            self._curve.set_points(pts, enabled=en)
        asusctl_name = backend.PROFILE_LABEL_TO_ASUSCTL[self._current_profile_label]
        try:
            backend.enable_fan_curve(asusctl_name, self._current_fan, en)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Enable fan curve failed", str(exc))

    def _on_reset(self) -> None:
        asusctl_name = backend.PROFILE_LABEL_TO_ASUSCTL[self._current_profile_label]
        try:
            backend.reset_fan_curves(asusctl_name)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Reset failed", str(exc))
            return
        self.reload()

    def _on_apply(self) -> None:
        asusctl_name = backend.PROFILE_LABEL_TO_ASUSCTL[self._current_profile_label]
        pts = self._curve.points()
        if len(pts) < 2:
            return
        try:
            backend.set_fan_curve(asusctl_name, self._current_fan, pts)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Apply fan curve failed", str(exc))
            return

    def reload(self) -> None:
        if not self._caps.asusd_available:
            return
        asusctl_name = backend.PROFILE_LABEL_TO_ASUSCTL[self._current_profile_label]
        try:
            curve = backend.get_fan_curve(asusctl_name, self._current_fan)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Could not read fan curve", str(exc))
            return
        self._curve.set_points(curve.points, enabled=curve.enabled)
        self._enabled_cb.blockSignals(True)
        self._enabled_cb.setChecked(curve.enabled)
        self._enabled_cb.blockSignals(False)
        self._edit_hint.setVisible(not curve.enabled)
