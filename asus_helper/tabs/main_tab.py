from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class _PlaceholderLine(QLineEdit):
    """QLineEdit with placeholder text that clears on focus."""
    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)

from .. import backend, display
from ..dialogs import LogoutCountdownDialog
from ..profiles import Profile, ProfileManager
from ..sensors import SensorSnapshot
from ..widgets.card import Card
from ..widgets.segmented import SegmentedControl
from ..widgets.toggle import ToggleRow
from ..theme import TX2, TX3, ACCENT

# GPU-mode description text (mirrors HTML gfxHints)
_GFX_HINTS: dict[str, str] = {
    "Eco":      "dGPU disabled · best battery life",
    "Hybrid":   "iGPU renders · dGPU available for offload",
    "Ultimate": "dGPU renders all outputs · no iGPU",
}


class MainTab(QWidget):
    """Performance profile, GPU mode, display, and battery."""

    profile_changed = pyqtSignal(str)   # asusctl name
    gpu_mode_changed = pyqtSignal(str)  # supergfx name

    def __init__(
        self, capabilities: backend.Capabilities, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._caps = capabilities

        # ── scrollable content area ───────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        col   = QVBoxLayout(inner)
        col.setContentsMargins(14, 14, 14, 14)
        col.setSpacing(10)

        col.addWidget(self._build_user_profiles_card())
        col.addWidget(self._build_profile_card())
        col.addWidget(self._build_gpu_card())
        col.addWidget(self._build_display_card())
        col.addWidget(self._build_battery_card())
        col.addStretch()

        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)

        self.refresh()

    # ── User profiles (saved presets) ─────────────────────────────────────

    def _build_user_profiles_card(self) -> Card:
        card = Card("Profiles")
        self._pm = ProfileManager()

        # Row 1: name input + Save
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._prof_name_input = _PlaceholderLine("New profile name…")
        row1.addWidget(self._prof_name_input, 1)
        save_btn = QPushButton("Save current")
        save_btn.setObjectName("Primary")
        save_btn.clicked.connect(self._on_prof_save)
        row1.addWidget(save_btn)
        card.add_layout(row1)

        # Row 2: combo + Load + Delete
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self._prof_combo = QComboBox()
        self._prof_combo.setPlaceholderText("— select saved profile —")
        self._prof_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._prof_combo.currentTextChanged.connect(self._on_prof_selected)
        row2.addWidget(self._prof_combo, 1)
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._on_prof_load)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_prof_delete)
        row2.addWidget(load_btn)
        row2.addWidget(delete_btn)
        card.add_layout(row2)

        self._prof_hint = QLabel("")
        self._prof_hint.setObjectName("Hint")
        self._prof_hint.setTextFormat(Qt.RichText)
        card.add(self._prof_hint)

        self._reload_prof_combo()
        return card

    def _reload_prof_combo(self) -> None:
        self._prof_combo.blockSignals(True)
        current = self._prof_combo.currentText()
        self._prof_combo.clear()
        for name in self._pm.list_names():
            self._prof_combo.addItem(name)
        # Try to restore selection
        idx = self._prof_combo.findText(current)
        if idx >= 0:
            self._prof_combo.setCurrentIndex(idx)
        self._prof_combo.blockSignals(False)
        self._on_prof_selected(self._prof_combo.currentText())

    def _on_prof_selected(self, name: str) -> None:
        if not name:
            self._prof_hint.setText("")
            return
        p = self._pm.get(name)
        if p:
            self._prof_hint.setText(
                f"<b>{ProfileManager.summary(p)}</b>"
            )
        else:
            self._prof_hint.setText("")

    def _on_prof_save(self) -> None:
        name = self._prof_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "No name", "Enter a profile name before saving.")
            return
        p = ProfileManager.snapshot_current(name)
        if p is None:
            QMessageBox.warning(self, "Cannot read state", "Could not read current system state.")
            return
        self._pm.save(p)
        self._prof_name_input.clear()
        self._reload_prof_combo()
        # Select the just-saved profile
        idx = self._prof_combo.findText(name)
        if idx >= 0:
            self._prof_combo.setCurrentIndex(idx)

    def _on_prof_load(self) -> None:
        name = self._prof_combo.currentText()
        if not name:
            return
        p = self._pm.get(name)
        if p is None:
            return
        self._apply_user_profile(p)

    def _on_prof_delete(self) -> None:
        name = self._prof_combo.currentText()
        if not name:
            return
        self._pm.delete(name)
        self._reload_prof_combo()

    def _apply_user_profile(self, p: Profile) -> None:
        """Apply a saved profile: perf → gpu → battery limit."""
        errors: list[str] = []

        # 1. Performance profile
        try:
            backend.set_profile(p.perf)
        except backend.BackendError as e:
            errors.append(f"Profile: {e}")

        # 2. GPU mode (may require logout — show countdown dialog)
        gpu_result = ""
        try:
            prev_raw   = backend.get_gpu_mode()
            from_label = backend.SUPERGFX_TO_GPU_LABEL.get(prev_raw, prev_raw)
            to_label   = backend.SUPERGFX_TO_GPU_LABEL.get(p.gpu, p.gpu)
            gpu_result = backend.set_gpu_mode(p.gpu)
        except backend.BackendError as e:
            errors.append(f"GPU mode: {e}")

        # 3. Battery limit
        try:
            backend.set_charge_limit(p.bat_limit)
        except backend.BackendError as e:
            errors.append(f"Charge limit: {e}")

        # Refresh UI
        self.refresh_profile()
        self.refresh_gpu()
        self.refresh_battery()
        self.profile_changed.emit(p.perf)
        self.gpu_mode_changed.emit(p.gpu)

        if errors:
            QMessageBox.warning(self, "Profile load errors", "\n".join(errors))

        # GPU mode logout dialog (after UI refresh)
        if gpu_result:
            lowered = gpu_result.lower()
            if "reboot" in lowered:
                QMessageBox.information(self, "Reboot required",
                    f"Reboot required to finish switching GPU to <b>{to_label}</b>.")
            else:
                LogoutCountdownDialog.maybe_show(gpu_result, from_label, to_label, self)

    # ── Performance profile card ──────────────────────────────────────────

    def _build_profile_card(self) -> Card:
        card = Card("Performance Profile")
        self._profile_seg = SegmentedControl(["Silent", "Balanced", "Turbo"])
        self._profile_seg.selected.connect(self._on_profile_clicked)
        card.add(self._profile_seg)

        self._profile_hint = QLabel("")
        self._profile_hint.setObjectName("Hint")
        card.add(self._profile_hint)

        if not self._caps.asusd_available:
            self._profile_seg.setDisabled(True)
            self._profile_hint.setText("asusd not running")
        return card

    def _on_profile_clicked(self, label: str) -> None:
        asusctl_name = backend.PROFILE_LABEL_TO_ASUSCTL[label]
        self._profile_seg.setDisabled(True)
        try:
            backend.set_profile(asusctl_name)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Profile change failed", str(exc))
        else:
            self.profile_changed.emit(asusctl_name)
        finally:
            QTimer.singleShot(500, lambda: self._profile_seg.setDisabled(False))
            self.refresh_profile()

    def refresh_profile(self) -> None:
        if not self._caps.asusd_available:
            return
        try:
            current = backend.get_profile()
        except backend.BackendError as exc:
            self._profile_hint.setText(f"error: {exc}")
            return
        label = backend.ASUSCTL_TO_PROFILE_LABEL.get(current, current)
        self._profile_seg.set_value(label)
        self._profile_hint.setText(f"Active: <b>{label}</b>")
        self._profile_hint.setTextFormat(Qt.RichText)

    # ── GPU card ─────────────────────────────────────────────────────────

    def _build_gpu_card(self) -> Card:
        card = Card("Graphics Mode")

        if self._caps.supergfxd_available:
            try:
                supported = backend.get_supported_gpu_modes()
            except backend.BackendError:
                supported = []
        else:
            supported = []

        labels = [backend.SUPERGFX_TO_GPU_LABEL.get(m, m) for m in supported]
        if not labels:
            labels = ["Eco", "Hybrid", "Ultimate"]
        self._supported_gpu_modes = supported

        self._gpu_seg = SegmentedControl(labels)
        self._gpu_seg.selected.connect(self._on_gpu_clicked)
        card.add(self._gpu_seg)

        self._gpu_hint = QLabel("")
        self._gpu_hint.setObjectName("Hint")
        self._gpu_hint.setTextFormat(Qt.RichText)
        self._gpu_hint.setWordWrap(True)
        card.add(self._gpu_hint)

        if not self._caps.supergfxd_available:
            self._gpu_seg.setDisabled(True)
            self._gpu_hint.setText("supergfxd not running")
        return card

    def _on_gpu_clicked(self, label: str) -> None:
        target = backend.GPU_LABEL_TO_SUPERGFX.get(label, label)
        self._gpu_seg.setDisabled(True)

        try:
            prev_raw   = backend.get_gpu_mode()
            from_label = backend.SUPERGFX_TO_GPU_LABEL.get(prev_raw, prev_raw)
        except backend.BackendError:
            from_label = self._gpu_seg.value() or "current mode"

        try:
            result = backend.set_gpu_mode(target)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "GPU mode switch failed", str(exc))
            self.refresh_gpu()
            QTimer.singleShot(500, lambda: self._gpu_seg.setDisabled(False))
            return

        self.gpu_mode_changed.emit(target)
        QTimer.singleShot(500, lambda: self._gpu_seg.setDisabled(False))
        self.refresh_gpu()

        lowered = result.lower()
        if "reboot" in lowered:
            QMessageBox.information(
                self, "Reboot required",
                f"Reboot required to finish switching to <b>{label}</b>.",
            )
        else:
            LogoutCountdownDialog.maybe_show(result, from_label, label, self)

    def refresh_gpu(self) -> None:
        if not self._caps.supergfxd_available:
            return
        try:
            current = backend.get_gpu_mode()
        except backend.BackendError as exc:
            self._gpu_hint.setText(f"error: {exc}")
            return
        label = backend.SUPERGFX_TO_GPU_LABEL.get(current, current)
        self._gpu_seg.set_value(label)

        desc = _GFX_HINTS.get(label, "")
        pending = backend.get_pending_gpu_mode()
        if pending and pending.lower() not in {"none", "", "unknown"}:
            action = backend.get_pending_gpu_action()
            self._gpu_hint.setText(
                f"Active: <b>{label}</b> · {desc}"
                f"<br><span style='color:#f5a623;'>Pending: {pending}"
                f" ({action or 'none'})</span>"
            )
        else:
            self._gpu_hint.setText(f"Active: <b>{label}</b> · {desc}")

    # ── Display card ─────────────────────────────────────────────────────

    def _build_display_card(self) -> Card:
        card = Card("Display & Panel")

        # Sub-label
        hz_lbl = QLabel("REFRESH RATE (HZ)")
        hz_lbl.setObjectName("SubLabel")
        card.add(hz_lbl)

        self._display_state = display.get_display_state()
        if self._display_state and self._display_state.rates:
            labels = [str(r) for r in self._display_state.rates]
            self._rate_seg = SegmentedControl(labels)
            self._rate_seg.selected.connect(self._on_rate_selected)
            card.add(self._rate_seg)
        else:
            self._rate_seg = None
            card.add(QLabel("not available"))

        # Panel overdrive toggle
        self._panel_od = ToggleRow("Panel Overdrive")
        self._panel_od.toggled.connect(self._on_panel_od)
        card.add(self._panel_od)
        if not self._caps.has_panel_overdrive:
            self._panel_od.setDisabled(True)
            self._panel_od.setToolTip("Not supported by this firmware / asusctl")

        # Flicker-free — shown only when firmware exposes it
        if self._caps.flicker_free_iface:
            self._flicker = ToggleRow("Flicker-free Dimming")
            self._flicker.toggled.connect(self._on_flicker)
            card.add(self._flicker)
        else:
            self._flicker = None

        return card

    def _on_rate_selected(self, label: str) -> None:
        if not self._display_state:
            return
        hz = int(label)
        try:
            display.set_refresh_rate(self._display_state.connector, hz)
        except display.DisplayError as exc:
            QMessageBox.warning(self, "Refresh rate change failed", str(exc))
        QTimer.singleShot(300, self.refresh_display)

    def _on_panel_od(self, checked: bool) -> None:
        if not self._caps.has_panel_overdrive:
            return
        try:
            backend.set_panel_overdrive(checked)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Panel Overdrive failed", str(exc))
            QTimer.singleShot(0, self.refresh_display)

    def _on_flicker(self, checked: bool) -> None:
        iface = self._caps.flicker_free_iface
        if not iface:
            return
        try:
            backend.set_flicker_free(iface, checked)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Flicker-free toggle failed", str(exc))

    def refresh_display(self) -> None:
        if self._rate_seg is not None:
            state = display.get_display_state()
            if state:
                self._display_state = state
                self._rate_seg.set_value(str(state.current_hz))
        if self._caps.has_panel_overdrive:
            try:
                on = backend.get_panel_overdrive()
            except backend.BackendError:
                on = False
            self._panel_od.blockSignals(True)
            self._panel_od.setChecked(on)
            self._panel_od.blockSignals(False)
        if self._flicker and self._caps.flicker_free_iface:
            on = backend.get_flicker_free(self._caps.flicker_free_iface)
            self._flicker.blockSignals(True)
            self._flicker.setChecked(on)
            self._flicker.blockSignals(False)

    # ── Battery card ─────────────────────────────────────────────────────

    def _build_battery_card(self) -> Card:
        card = Card("Battery Charge Limit")

        row = QHBoxLayout()
        row.setSpacing(10)

        self._bat_slider = QSlider(Qt.Horizontal)
        self._bat_slider.setRange(20, 100)
        self._bat_slider.setSingleStep(1)
        self._bat_slider.setPageStep(5)
        self._bat_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._bat_num = QLabel("90 %")
        self._bat_num.setStyleSheet(
            "padding:5px 10px; background:#1c1c26; border:1px solid #272736; "
            "border-radius:6px; font-size:13px; min-width:58px; text-align:center;"
        )
        self._bat_num.setAlignment(Qt.AlignCenter)

        self._bat_apply = QPushButton("Apply")
        self._bat_apply.setObjectName("Primary")
        self._bat_apply.clicked.connect(self._on_bat_apply)

        self._bat_slider.valueChanged.connect(
            lambda v: self._bat_num.setText(f"{v} %")
        )

        row.addWidget(self._bat_slider, 1)
        row.addWidget(self._bat_num)
        row.addWidget(self._bat_apply)
        card.add_layout(row)

        self._bat_hint = QLabel("")
        self._bat_hint.setObjectName("Hint")
        self._bat_hint.setTextFormat(Qt.RichText)
        card.add(self._bat_hint)

        if not self._caps.asusd_available:
            for w in (self._bat_slider, self._bat_num, self._bat_apply):
                w.setDisabled(True)
            self._bat_hint.setText("asusd not running")
        return card

    def _on_bat_apply(self) -> None:
        pct = self._bat_slider.value()
        try:
            backend.set_charge_limit(pct)
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Charge limit failed", str(exc))
            return
        self._refresh_bat_hint(pct, None, None)

    def _refresh_bat_hint(
        self,
        limit: int,
        bat_pct: float | None,
        plugged: bool | None,
        bat_status: str | None = None,
    ) -> None:
        parts = [f"Current limit: <b>{limit}%</b>"]
        if bat_pct is not None:
            status_lower = (bat_status or "").lower()
            if "charging" in status_lower and "not" not in status_lower:
                state = "charging ⚡"
            elif plugged:
                state = "plugged in · not charging"
            else:
                state = "on battery"
            parts.append(f"Battery: {round(bat_pct)}% ({state})")
        self._bat_hint.setText(" · ".join(parts))

    def refresh_battery(self) -> None:
        try:
            limit = backend.read_charge_limit()
        except Exception:
            limit = 100
        self._bat_slider.blockSignals(True)
        self._bat_slider.setValue(limit)
        self._bat_slider.blockSignals(False)
        self._bat_num.setText(f"{limit} %")
        self._refresh_bat_hint(limit, None, None)

    def update_snapshot(self, snap: SensorSnapshot) -> None:
        """Called ~1 Hz from the sensor thread — updates live battery line."""
        try:
            limit = backend.read_charge_limit()
        except Exception:
            limit = self._bat_slider.value()
        self._refresh_bat_hint(
            limit, snap.battery_pct, snap.battery_plugged, snap.battery_status
        )

    # ── Public refresh ────────────────────────────────────────────────────

    def refresh(self) -> None:
        self.refresh_profile()
        self.refresh_gpu()
        self.refresh_display()
        self.refresh_battery()
