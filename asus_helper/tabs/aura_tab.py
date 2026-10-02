from __future__ import annotations

import re

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import backend
from ..widgets.card import Card
from ..widgets.segmented import SegmentedControl

_BRIGHTNESS = ["Off", "Low", "Med", "High"]

_MODES = ["Static", "Breathe", "Rainbow", "Ripple"]

# 16 colour presets (matches HTML PRESETS array, 8 per row)
_PRESETS = [
    "#FF3D3D", "#FF8C00", "#FFD700", "#7FFF00",
    "#00E87A", "#00C8FF", "#4070FF", "#9B30F0",
    "#FF60CC", "#FFFFFF", "#FF6347", "#00E5CC",
    "#D053F3", "#FF2E88", "#FFA040", "#40DAFF",
]

_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


class _Swatch(QPushButton):
    """Coloured square swatch button."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self._apply_style(False)

    def set_selected(self, on: bool) -> None:
        self._apply_style(on)

    def _apply_style(self, on: bool) -> None:
        border = "2.5px solid #ffffff" if on else "2.5px solid transparent"
        outline = f"box-shadow: 0 0 0 2px #5080f0;" if on else ""
        self.setStyleSheet(
            f"QPushButton {{ "
            f"background:{self._color}; border-radius:7px; border:{border}; "
            f"}} "
            f"QPushButton:hover {{ border:2.5px solid rgba(255,255,255,.6); }}"
        )


class AuraTab(QWidget):
    def __init__(
        self, capabilities: backend.Capabilities, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._caps = capabilities
        self._color = QColor("#D053F3")
        self._swatches: list[_Swatch] = []
        self._active_mode = "Static"

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        col   = QVBoxLayout(inner)
        col.setContentsMargins(14, 14, 14, 14)
        col.setSpacing(10)

        col.addWidget(self._build_brightness_card())
        col.addWidget(self._build_mode_card())
        self._colour_card = self._build_colour_card()
        col.addWidget(self._colour_card)
        col.addStretch()

        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)

        if not self._caps.asusd_available:
            self.setDisabled(True)

    # ── Brightness ───────────────────────────────────────────────────────

    def _build_brightness_card(self) -> Card:
        card = Card("Keyboard Brightness")
        self._bright_seg = SegmentedControl(_BRIGHTNESS)
        self._bright_seg.set_value("Med")
        self._bright_seg.selected.connect(self._on_brightness)
        card.add(self._bright_seg)

        supported = {s.lower() for s in self._caps.brightness_levels}
        if supported:
            self._bright_seg.set_enabled_values(False)
            self._bright_seg.set_enabled_values(
                True,
                [lbl for lbl in _BRIGHTNESS if lbl.lower() in supported],
            )
        return card

    def _on_brightness(self, label: str) -> None:
        try:
            backend.set_kbd_brightness(label.lower())
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Brightness failed", str(exc))

    # ── Aura mode chips ──────────────────────────────────────────────────

    def _build_mode_card(self) -> Card:
        card = Card("Aura Mode")
        row  = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)

        supported_modes = {m.lower() for m in self._caps.aura_modes}
        self._mode_btns: dict[str, QPushButton] = {}

        for mode in _MODES:
            btn = QPushButton(mode)
            btn.setObjectName("ModeChip")
            btn.setCursor(Qt.PointingHandCursor)
            is_supported = mode.lower() in supported_modes or not supported_modes
            if not is_supported:
                btn.setDisabled(True)
                btn.setToolTip("Not supported by this firmware")
            btn.clicked.connect(lambda _, m=mode: self._on_mode(m))
            self._mode_btns[mode] = btn
            row.addWidget(btn)

        row.addStretch()
        card.add_layout(row)
        self._set_mode_chip("Static")
        return card

    def _on_mode(self, mode: str) -> None:
        self._active_mode = mode
        self._set_mode_chip(mode)
        # Show/hide colour card
        self._colour_card.setVisible(mode in {"Static", "Breathe"})

    def _set_mode_chip(self, active: str) -> None:
        for m, btn in self._mode_btns.items():
            btn.setProperty("active", m == active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Colour card ──────────────────────────────────────────────────────

    def _build_colour_card(self) -> Card:
        card = Card("Colour")

        # Swatch grid — 8 columns, 2 rows
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(7)
        for i, hex_col in enumerate(_PRESETS):
            sw = _Swatch(hex_col)
            sw.clicked.connect(lambda _, c=hex_col: self._pick_preset(c))
            self._swatches.append(sw)
            grid.addWidget(sw, i // 8, i % 8)
        card.add_layout(grid)

        # Colour row: preview box | hex input | apply button
        row = QHBoxLayout()
        row.setSpacing(12)

        self._preview = QFrame()
        self._preview.setFixedSize(80, 50)
        self._preview.setStyleSheet(
            f"background:{self._color.name()}; border-radius:8px; "
            "border:1px solid #272736;"
        )
        row.addWidget(self._preview)

        self._hex_input = QLineEdit(self._color.name().upper())
        self._hex_input.setFixedWidth(110)
        self._hex_input.setStyleSheet(
            "font-family:'Courier New',monospace; letter-spacing:0.5px;"
        )
        self._hex_input.textChanged.connect(self._on_hex_changed)
        self._hex_input.returnPressed.connect(self._apply_color)
        row.addWidget(self._hex_input)

        row.addStretch()

        if self._caps.aura_zones:
            from PyQt5.QtWidgets import QComboBox
            self._zone_combo = QComboBox()
            self._zone_combo.addItems(["(default)", *self._caps.aura_zones])
            row.addWidget(QLabel("Zone:"))
            row.addWidget(self._zone_combo)
        else:
            self._zone_combo = None

        self._apply_btn = QPushButton("Apply colour")
        self._apply_btn.setObjectName("Primary")
        self._apply_btn.clicked.connect(self._apply_color)
        row.addWidget(self._apply_btn)

        card.add_layout(row)

        if self._caps.aura_modes and "Static" not in self._caps.aura_modes:
            card.add(QLabel("Static colour not supported by this firmware."))
            self._apply_btn.setDisabled(True)

        self._update_preview()
        return card

    # ── Colour helpers ────────────────────────────────────────────────────

    def _pick_preset(self, hex_col: str) -> None:
        self._color = QColor(hex_col)
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hex_col.upper())
        self._hex_input.blockSignals(False)
        self._update_preview()
        self._update_swatch_selection(hex_col)

    def _on_hex_changed(self, text: str) -> None:
        clean = text.strip()
        if not clean.startswith("#"):
            clean = "#" + clean
        if _HEX_RE.match(clean):
            self._color = QColor(clean.upper())
            self._update_preview()
            self._update_swatch_selection(clean.upper())

    def _update_preview(self) -> None:
        self._preview.setStyleSheet(
            f"background:{self._color.name()}; border-radius:8px; "
            "border:1px solid #272736;"
        )

    def _update_swatch_selection(self, selected: str) -> None:
        sel = selected.upper()
        for sw, preset in zip(self._swatches, _PRESETS):
            sw.set_selected(preset.upper() == sel)

    def _apply_color(self) -> None:
        raw = self._hex_input.text().strip().lstrip("#")
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", raw):
            return
        zone = None
        if self._zone_combo is not None and self._zone_combo.currentIndex() > 0:
            zone = self._zone_combo.currentText()
        try:
            backend.set_aura_static(raw, zone=zone)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Aura failed", str(exc))
            return
        # ✓ Applied feedback
        self._apply_btn.setText("✓ Applied")
        self._apply_btn.setObjectName("OkBtn")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)
        QTimer.singleShot(2000, self._reset_apply_btn)

    def _reset_apply_btn(self) -> None:
        self._apply_btn.setText("Apply colour")
        self._apply_btn.setObjectName("Primary")
        self._apply_btn.style().unpolish(self._apply_btn)
        self._apply_btn.style().polish(self._apply_btn)
