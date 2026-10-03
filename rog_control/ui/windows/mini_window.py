"""MiniWindow (docs/design/V2MiniTray.dc.html, left): small always-on-top live view with perf-mode buttons."""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from rog_control.ui import theme
from rog_control.ui.power_text import PowerView, compose_power
from rog_control.ui.widgets._common import IconButton
from rog_control.ui.windows._base import (GPU_LABEL, PERF_COLOR, PERF_KEYS, PERF_LABEL, ChoiceButton, Dot,
                                          FramelessWindow, fmt_num, label, request_perf)

log = logging.getLogger(__name__)


class MiniWindow(FramelessWindow):
    expandRequested = pyqtSignal()

    def __init__(self, state, controller, parent: QWidget | None = None):
        super().__init__(state, controller, "ROG Control — Mini", 340, 0, parent=parent)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        tb = self.titlebar
        tb.setFixedHeight(36)
        tb.lay.setContentsMargins(12, 0, 6, 0)
        tb.lay.setSpacing(8)
        self.dot = Dot(self._accent, 8)
        self.perf_lbl = label("", 13, 700)
        self.gpu_lbl = label("", 12, 400, theme.TEXT3)
        self.pwr_lbl = label("", 12, 600, theme.TEXT2)
        self._smoother = PowerView(5)
        tb.lay.addWidget(self.dot)
        tb.lay.addWidget(self.perf_lbl)
        tb.lay.addWidget(self.gpu_lbl)
        tb.lay.addStretch(1)
        tb.lay.addWidget(self.pwr_lbl)
        ex = IconButton("expand", (30, 28), 14, theme.TEXT2, 2.0, "Tam pencereye dön")
        ex.clicked.connect(self.expandRequested)
        tb.lay.addWidget(ex)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(12, 2, 12, 12)
        lay.setSpacing(8)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        self.vals = {}
        for i, key in enumerate(("CPU", "GPU", "FAN")):
            t = label(key, 10.5, 600, theme.TEXT3)
            t.setFont(theme.ui_font(10.5, 600, 1.05))
            t.setStyleSheet(f"color:{theme.TEXT3}; background:transparent")
            v = label("—", 20, 600, theme.TEXT, rich=True)
            grid.addWidget(t, 0, i)
            grid.addWidget(v, 1, i)
            self.vals[key] = v
        lay.addLayout(grid)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.buttons: dict[str, ChoiceButton] = {}
        for k in PERF_KEYS:
            b = ChoiceButton(PERF_LABEL[k], PERF_COLOR[k], 34, 8, dot=False, font_px=12.5)
            b.clicked.connect(lambda _=False, key=k: request_perf(self.ctl, key))
            row.addWidget(b)
            self.buttons[k] = b
        lay.addLayout(row)
        self.layout().activate()
        self.setFixedHeight(self.layout().sizeHint().height())

        state.perfModeChanged.connect(lambda _m: self._refresh_perf())
        state.sensorsChanged.connect(self._refresh_sensors)
        state.gfxChanged.connect(lambda _v: self._refresh_perf())
        self._refresh_perf()
        self._refresh_sensors(state.sensors)

    def accent_applied(self, accent: str) -> None:
        self.dot.set_color(accent)

    def _refresh_perf(self) -> None:
        m = self.state.perf_mode
        self.perf_lbl.setText(PERF_LABEL.get(m, "—"))
        g = self.state.gfx.active
        self.gpu_lbl.setText(f"· GPU {GPU_LABEL.get(g, '—')}" if g else "· GPU —")
        self.dot.set_color(self.state.accent)
        for k, b in self.buttons.items():
            b.set_selected(k == m)

    def _refresh_sensors(self, s) -> None:
        if s is None:
            return
        sys_w, chg_w = self._smoother.push(getattr(s, "system_power_w", None),
                                           getattr(s, "battery_power_w", None), s.battery_status)
        full = compose_power(sys_w, chg_w)
        # the mini bar is narrow: headline only, the charge part goes to the tooltip
        self.pwr_lbl.setText(compose_power(sys_w, None) or full or ("Prizde" if s.on_ac else ""))
        self.pwr_lbl.setToolTip(full or "")
        unit = lambda txt: f'<span style="font-size:12px; color:{theme.TEXT2}; font-weight:400"> {txt}</span>'  # noqa: E731
        self.vals["CPU"].setText(f"{fmt_num(s.cpu_temp)}°" + unit(f"{fmt_num(s.cpu_load)}%"))
        gpu = {"sleep": "Uyku", "off": "Kapalı", "unknown": "—"}.get(s.gpu_state)
        self.vals["GPU"].setText(gpu if gpu else f"{fmt_num(s.gpu_temp)}°" + unit(f"{fmt_num(s.gpu_load)}%"))
        rpm = (s.fans_rpm or {}).get("cpu")
        self.vals["FAN"].setText(f"{fmt_num(rpm)}" + unit("rpm"))

    def apply_enabled(self) -> None:
        for b in self.buttons.values():
            b.setEnabled(not self.is_busy("perf"))
