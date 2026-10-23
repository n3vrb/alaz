"""DevicesWindow: Aura Sync, ROG mouse, ROG headset and the external ASUS monitor (DDC/CI).

Read AppState, write through the Controller only. Values the backends could not read are shown as "—".
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                             QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from alaz.core.state import AuraSyncView
from alaz.i18n import tr
from alaz.ui import theme
from alaz.ui.widgets import Segmented, ToggleSwitch, ValueSlider, make_button
from alaz.ui.widgets._common import AccentMixin, button_qss
from alaz.ui.windows import dialogs
from alaz.ui.windows._base import FramelessWindow, Panel, label, section_title
from alaz.ui.windows.keyboard_window import SWATCHES, Swatch, parse_hex, to_hex

log = logging.getLogger(__name__)

DASH = "—"
WIDTH, HEIGHT = 520, 820

# Turkish source texts (translated through tr() on use). Keys of the Mouse tables are protocol codes.
SLEEP_ITEMS = ((0, "1 dk"), (1, "2 dk"), (2, "3 dk"), (3, "5 dk"), (4, "10 dk"), (0xFF, "Hiç"))
LED_MODES = ((0, "Sabit"), (1, "Nefes"), (2, "Renk döngüsü"), (4, "Tepki"), (6, "Pil durumu"), (0xF0, "Kapalı"))
POLLING_HZ = (125, 250, 500, 1000)
DEBOUNCE_MS = tuple(range(8, 33, 4))
AURA_EFFECT_ITEMS = (("static", "Sabit"), ("breathing", "Nefes"), ("cycle", "Renk döngüsü"))
HEADSET_EFFECTS = ((1, "Sabit"), (2, "Nefes"), (3, "Yanıp sönme"), (4, "Renk döngüsü"))
TARGET_LABELS = (("keyboard", "Klavye"), ("mouse", "Fare"), ("headset", "Kulaklık"))

# DdcClient.FEATURES labels are English product strings: UI copies that are plain words are translated here,
# ASUS product names (Scenery, FPS, MOBA, Racing, RTS/RPG, sRGB Cal, DisplayPort, HDMI, USB-C, 6500K, ...) stay as is.
CHOICE_TR = {
    "Off": "Kapalı", "User": "Kullanıcı", "Dynamic": "Dinamik", "Cinema": "Sinema", "Night Vision": "Gece görüşü",
    "Level 1": "Seviye 1", "Level 2": "Seviye 2", "Level 3": "Seviye 3", "Level 4": "Seviye 4",
    "Light": "Hafif", "Middle": "Orta düzey", "Strong": "Güçlü",
    "2 hours": "2 saat", "4 hours": "4 saat", "8 hours": "8 saat",
}


def choice_label(text: str) -> str:
    src = CHOICE_TR.get(text)
    return tr(src) if src else text


def fmt_pct(v) -> str:
    return DASH if v is None else f"{v} %"


def mouse_status(st) -> tuple[str, str]:
    """(kind, text): kind in ok | absent | noperm | asleep."""
    if st is None or (not st.present and st.permission):
        return "absent", tr("Bağlı değil")
    if not st.permission:
        return "noperm", tr("İzin yok — helper/install.sh ile udev kuralını kurun")
    if st.asleep:
        return "asleep", tr("Fare uykuda")
    return "ok", tr("Bağlı")


def headset_status(st) -> tuple[str, str]:
    if st is None or (not st.present and st.permission):
        return "absent", tr("Bağlı değil")
    if not st.permission:
        return "noperm", tr("İzin yok — helper/install.sh ile udev kuralını kurun")
    if st.connected is False:
        return "off", tr("Kulaklık kapalı")
    return "ok", tr("Bağlı")


# ---------------------------------------------------------------------------------------------- small widgets
class StyledCombo(QComboBox):
    """Dark combo box with a chevron; `activated` fires on user choices only. Items carry their value as data."""

    def __init__(self, items=(), parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setMinimumWidth(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setPlaceholderText(DASH)
        self.setStyleSheet(
            f"QComboBox {{ background:{theme.CONTROL}; border:1px solid {theme.BORDER}; border-radius:8px;"
            f" padding:0 28px 0 10px; color:{theme.TEXT}; font-size:13px; }}"
            f"QComboBox:focus {{ border-color:{theme.TEXT2}; }}"
            f"QComboBox:disabled {{ color:{theme.TEXT3}; background:{theme.PANEL}; }}"
            "QComboBox::drop-down { border:0; width:0px; }"
            f"QComboBox QAbstractItemView {{ background:{theme.CONTROL}; color:{theme.TEXT};"
            f" border:1px solid {theme.BORDER}; selection-background-color:{theme.BORDER}; outline:0; }}")
        for text, data in items:
            self.addItem(text, data)
        self.setCurrentIndex(-1)

    def set_data(self, data) -> None:
        """Programmatic selection (no `activated`); unknown or None -> placeholder dash."""
        i = self.findData(data) if data is not None else -1
        self.setCurrentIndex(i)

    def data(self):
        return self.currentData()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(theme.TEXT3 if not self.isEnabled() else theme.TEXT2)
        p.setPen(QPen(col, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy = self.width() - 15, self.height() / 2
        p.drawPolyline(QPolygonF([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)]))


class ColorPicker(QWidget, AccentMixin):
    """16 swatches + hex entry + Apply. `colorPicked(rgb)` on user action only; set_color() never emits."""

    colorPicked = pyqtSignal(tuple)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rgb: tuple[int, int, int] | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.swatches: list[Swatch] = []
        for i, c in enumerate(SWATCHES):
            s = Swatch(c)
            s.clicked.connect(self._pick)
            grid.addWidget(s, i // 8, i % 8)
            self.swatches.append(s)
        lay.addLayout(grid)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.preview = QWidget()
        self.preview.setFixedSize(34, 34)
        row.addWidget(self.preview)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setPlaceholderText("#RRGGBB")
        self.hex.setFixedHeight(34)
        self.hex.setAccessibleName(tr("Renk (hex)"))
        self.hex.textChanged.connect(self._hex_changed)
        self.hex.returnPressed.connect(self._apply)
        row.addWidget(self.hex, 1)
        self.apply_btn = make_button(tr("Uygula"), "primary", self._accent, pad=16)
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(self.apply_btn)
        lay.addLayout(row)
        self._hex_changed("")

    def _accent_changed(self) -> None:
        self.apply_btn.setStyleSheet(button_qss(self._accent, theme.INK, None, weight=600, pad=16))
        self._hex_changed(self.hex.text())

    def color(self) -> tuple[int, int, int] | None:
        return self._rgb

    def set_color(self, rgb) -> None:
        self._rgb = tuple(rgb) if rgb is not None else None
        if not self.hex.hasFocus():
            self.hex.blockSignals(True)
            self.hex.setText(to_hex(self._rgb) if self._rgb else "")
            self.hex.blockSignals(False)
            self._hex_changed(self.hex.text())
        cur = to_hex(self._rgb) if self._rgb else None
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
            f"QLineEdit:focus {{ border-color:{self._accent}; }}"
            f"QLineEdit:disabled {{ color:{theme.TEXT3}; }}")
        shown = rgb if ok else self._rgb
        self.preview.setStyleSheet(f"background:{to_hex(shown) if shown else theme.CONTROL}; border-radius:8px;"
                                   f" border:1px solid {theme.BORDER};")
        self.apply_btn.setEnabled(ok)

    def _apply(self) -> None:
        rgb = parse_hex(self.hex.text())
        if rgb is not None:
            self._rgb = rgb
            self.set_color(rgb)
            self.colorPicked.emit(rgb)


def _row(text: str, widget: QWidget, note: QLabel | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    if note is None:
        row.addWidget(label(text, 13, 500))
    else:
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(text, 13, 500))
        col.addWidget(note)
        row.addLayout(col)
    row.addStretch(1)
    row.addWidget(widget)
    return row


def _note(text: str = "", color: str = theme.TEXT3) -> QLabel:
    l = label(text, 11.5, 400, color)
    l.setWordWrap(True)
    return l


class _TabPage(QWidget):
    """Scrollable tab page with a notice card (unavailable states) above the content widget."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.viewport().setObjectName("devVp")
        scroll.viewport().setStyleSheet(f"QWidget#devVp {{ background:{theme.BG}; }}")
        inner = QWidget()
        inner.setObjectName("devInner")
        inner.setStyleSheet(f"QWidget#devInner {{ background:{theme.BG}; }}")
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(16, 12, 16, 14)
        self.lay.setSpacing(12)
        self.scroll = scroll
        self.notice_panel = Panel(12)
        self.notice = label("", 13, 500, theme.TEXT2)
        self.notice.setWordWrap(True)
        self.notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice.setMinimumHeight(54)
        self.notice_panel.lay.addWidget(self.notice)
        self.lay.addWidget(self.notice_panel)
        self.content = QWidget()
        self.clay = QVBoxLayout(self.content)
        self.clay.setContentsMargins(0, 0, 0, 0)
        self.clay.setSpacing(12)
        self.lay.addWidget(self.content)
        self.lay.addStretch(1)
        self.notice_panel.hide()

    def show_notice(self, text: str | None) -> None:
        self.notice_panel.setVisible(text is not None)
        self.notice.setText(text or "")
        self.content.setVisible(text is None)


# ---------------------------------------------------------------------------------------------- the window
class DevicesWindow(FramelessWindow):
    def __init__(self, state, controller, parent: QWidget | None = None):
        super().__init__(state, controller, tr("Alaz — Cihazlar"), WIDTH, HEIGHT, back=True, parent=parent)
        tb = self.titlebar.lay
        tb.addWidget(self.title_label(tr("Cihazlar")))
        tb.addStretch(1)
        self.add_window_buttons(minimize=False)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 12, 16, 0)
        lay.setSpacing(0)
        self.tabs = Segmented([("aura", tr("Aura Sync")), ("mouse", tr("Fare")), ("headset", tr("Kulaklık")),
                               ("monitor", tr("Monitör"))], height=32, stretch=True)
        self.tabs.changed.connect(self._set_tab)
        lay.addWidget(self.tabs)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.pages: dict[str, _TabPage] = {}
        for key, build in (("aura", self._build_aura), ("mouse", self._build_mouse),
                           ("headset", self._build_headset), ("monitor", self._build_monitor)):
            page = _TabPage()
            self.pages[key] = page
            self.stack.addWidget(page)
            build(page)
        self.tabs.set_current("aura")

        self.track_accent(self.tabs, self.aura_enable, self.aura_effect, self.aura_picker, self.aura_bright,
                          *self.aura_targets.values(), self.mouse_picker, self.mouse_bright, self.mouse_polling,
                          self.mouse_angle, self.headset_effect, self.headset_picker, self.headset_bright,
                          self.mon_bright, self.mon_contrast)

        state.peripheralsChanged.connect(self._on_peripheral)
        state.auraSyncChanged.connect(lambda _v: self._refresh_aura_related())
        self._refresh_all()

    # ------------------------------------------------------------------ helpers
    def _set_tab(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])

    def accent_applied(self, accent: str) -> None:
        self._refresh_mouse()       # the active DPI stage button uses the accent colour

    def showEvent(self, e):
        super().showEvent(e)
        self.ctl.refresh_monitor()      # DDC is never polled: read it when the window opens

    def _on_peripheral(self, kind: str, _st) -> None:
        {"mouse": self._refresh_mouse, "headset": self._refresh_headset,
         "monitor": self._refresh_monitor}.get(kind, lambda: None)()
        self._refresh_aura_related()

    def _refresh_all(self) -> None:
        self._refresh_aura()
        self._refresh_mouse()
        self._refresh_headset()
        self._refresh_monitor()

    def _refresh_aura_related(self) -> None:
        self._refresh_aura()
        self._refresh_mouse_lighting_lock()
        self._refresh_headset_lighting_lock()

    def _managed(self, target: str) -> bool:
        v = self.state.aura_sync
        return bool(v.enabled and target in v.targets)

    # ================================================================== Aura Sync
    def _build_aura(self, page: _TabPage) -> None:
        c = page.clay
        p = Panel(12)
        self.aura_enable = ToggleSwitch(tr("Aura Sync"), tr("Seçili cihazları aynı renk ve efektle eşler"))
        self.aura_enable.toggled.connect(lambda _on: self._aura_edited())
        p.lay.addWidget(self.aura_enable)
        c.addWidget(p)

        c.addWidget(section_title(tr("Efekt")))
        ep = Panel(12)
        self.aura_effect = Segmented([(k, tr(t)) for k, t in AURA_EFFECT_ITEMS], height=32, stretch=True)
        self.aura_effect.changed.connect(lambda _k: self._aura_edited())
        ep.lay.addWidget(self.aura_effect)
        self.aura_note = _note(tr("Klavye her zaman sabit renk kullanır; Nefes ve Renk döngüsü yalnızca fare ve "
                                  "kulaklıkta çalışır."))
        ep.lay.addWidget(self.aura_note)
        c.addWidget(ep)

        c.addWidget(section_title(tr("Renk")))
        cp = Panel(12)
        cp.lay.setSpacing(12)
        self.aura_picker = ColorPicker()
        self.aura_picker.colorPicked.connect(lambda _rgb: self._aura_edited())
        cp.lay.addWidget(self.aura_picker)
        self.aura_bright = ValueSlider(tr("Parlaklık"), "", 0, 100, 1, " %", label_width=84, value_width=50)
        self.aura_bright.valueChanged.connect(lambda _v: self._aura_edited())   # controller debounces
        cp.lay.addWidget(self.aura_bright)
        c.addWidget(cp)

        c.addWidget(section_title(tr("Cihazlar")))
        tp = Panel(12)
        self.aura_targets: dict[str, ToggleSwitch] = {}
        for key, text in TARGET_LABELS:
            sw = ToggleSwitch(tr(text), tr("Bağlı değil"))
            sw.toggled.connect(lambda _on: self._aura_edited())
            self.aura_targets[key] = sw
            tp.lay.addWidget(sw)
        c.addWidget(tp)

    def _aura_view(self) -> AuraSyncView:
        cur = self.state.aura_sync
        return AuraSyncView(
            enabled=self.aura_enable.isChecked(),
            effect=self.aura_effect.current() or cur.effect,
            color=self.aura_picker.color() or cur.color,
            brightness=self.aura_bright.value(),
            targets={k for k, sw in self.aura_targets.items() if sw.isChecked()})

    def _aura_edited(self) -> None:
        self.ctl.aura_sync_set(self._aura_view())

    def _refresh_aura(self) -> None:
        v = self.state.aura_sync
        self.aura_enable.setChecked(v.enabled)
        self.aura_effect.set_current(v.effect)
        self.aura_picker.set_color(v.color)
        self.aura_bright.set_value_if_idle(v.brightness)
        for key, sw in self.aura_targets.items():
            sw.setChecked(key in v.targets)
        self.aura_targets["keyboard"].set_texts(tr("Klavye"), tr("Bağlı"))
        self.aura_targets["mouse"].set_texts(tr("Fare"), mouse_status(self.state.peripheral("mouse"))[1])
        self.aura_targets["headset"].set_texts(tr("Kulaklık"), headset_status(self.state.peripheral("headset"))[1])
        self.aura_note.setVisible(v.effect != "static")

    # ================================================================== Mouse
    def _build_mouse(self, page: _TabPage) -> None:
        c = page.clay
        c.addWidget(section_title(tr("Pil")))
        bp = Panel(12)
        self.mouse_battery = label(DASH, 13, 600)
        bp.lay.addLayout(_row(tr("Pil"), self.mouse_battery))
        c.addWidget(bp)

        c.addWidget(section_title("DPI"))
        dp = Panel(12)
        dp.lay.setSpacing(8)
        self.mouse_spins: list[QSpinBox] = []
        self.mouse_stage_btns: list[QPushButton] = []
        for i in range(4):
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(label(tr("Aşama {n}", n=i + 1), 13, 500))
            row.addStretch(1)
            sp = QSpinBox()
            sp.setRange(100, 42000)
            sp.setSingleStep(50)
            sp.setSuffix(" DPI")
            sp.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            sp.setAlignment(Qt.AlignmentFlag.AlignRight)
            sp.setFixedSize(120, 32)
            sp.setStyleSheet(
                f"QSpinBox {{ background:{theme.CONTROL}; border:1px solid {theme.BORDER}; border-radius:8px;"
                f" padding:0 10px; color:{theme.TEXT}; font-size:13px; }}"
                f"QSpinBox:focus {{ border-color:{theme.TEXT2}; }} QSpinBox:disabled {{ color:{theme.TEXT3}; }}")
            sp.editingFinished.connect(lambda i=i: self._dpi_edited(i))
            btn = QPushButton()
            btn.setFixedSize(76, 32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.clicked.connect(lambda _c=False, i=i: self._stage_clicked(i))
            row.addWidget(sp)
            row.addWidget(btn)
            dp.lay.addLayout(row)
            self.mouse_spins.append(sp)
            self.mouse_stage_btns.append(btn)
        c.addWidget(dp)

        c.addWidget(section_title(tr("Sensör")))
        sp_ = Panel(12)
        sp_.lay.setSpacing(10)
        sp_.lay.addWidget(label(tr("Yoklama hızı"), 13, 500))
        self.mouse_polling = Segmented([(str(h), f"{h} Hz") for h in POLLING_HZ], height=32, stretch=True)
        self.mouse_polling.changed.connect(lambda k: self.ctl.mouse_set_polling(int(k)))
        sp_.lay.addWidget(self.mouse_polling)
        self.mouse_debounce = StyledCombo([(f"{m} ms", m) for m in DEBOUNCE_MS])
        self.mouse_debounce.activated.connect(lambda _i: self._combo_write(self.mouse_debounce,
                                                                           self.ctl.mouse_set_debounce))
        sp_.lay.addLayout(_row(tr("Debounce süresi"), self.mouse_debounce))
        self.mouse_angle = ToggleSwitch(tr("Açı yakalama"))
        self.mouse_angle.toggled.connect(self.ctl.mouse_set_angle_snapping)
        sp_.lay.addWidget(self.mouse_angle)
        self.mouse_sleep = StyledCombo([(tr(t), code) for code, t in SLEEP_ITEMS])
        self.mouse_sleep.activated.connect(lambda _i: self._combo_write(self.mouse_sleep, self.ctl.mouse_set_sleep))
        sp_.lay.addLayout(_row(tr("Uyku süresi"), self.mouse_sleep))
        c.addWidget(sp_)

        c.addWidget(section_title(tr("Aydınlatma")))
        lp = Panel(12)
        lp.lay.setSpacing(10)
        self.mouse_managed = _note(tr("Aura Sync tarafından yönetiliyor"), theme.WARN_ACCENT)
        lp.lay.addWidget(self.mouse_managed)
        self.mouse_light = QWidget()
        ll = QVBoxLayout(self.mouse_light)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        self.mouse_led_mode = StyledCombo([(tr(t), m) for m, t in LED_MODES])
        self.mouse_led_mode.activated.connect(lambda _i: self._mouse_led())
        ll.addLayout(_row(tr("Mod"), self.mouse_led_mode))
        self.mouse_picker = ColorPicker()
        self.mouse_picker.colorPicked.connect(lambda _rgb: self._mouse_led())
        ll.addWidget(self.mouse_picker)
        self.mouse_bright = ValueSlider(tr("Parlaklık"), "", 0, 100, 1, " %", label_width=84, value_width=50)
        self.mouse_bright.committed.connect(lambda _v: self._mouse_led())
        ll.addWidget(self.mouse_bright)
        lp.lay.addWidget(self.mouse_light)
        c.addWidget(lp)

    def _combo_write(self, combo: StyledCombo, fn) -> None:
        if combo.data() is not None:
            fn(int(combo.data()))

    def _dpi_edited(self, i: int) -> None:
        st = self.state.peripheral("mouse")
        stages = (st.dpi_stages if st is not None else None) or []
        v = self.mouse_spins[i].value()
        v = max(100, min(42000, int(round(v / 50.0)) * 50))
        if i < len(stages) and stages[i] == v:
            self.mouse_spins[i].setValue(v)
            return
        self.mouse_spins[i].setValue(v)
        self.ctl.mouse_set_dpi(i, v)

    def _stage_clicked(self, i: int) -> None:
        st = self.state.peripheral("mouse")
        if st is not None and st.dpi_stage == i + 1:
            return
        self.ctl.mouse_set_active_stage(i + 1)

    def _mouse_led(self) -> None:
        st = self.state.peripheral("mouse")
        mode = self.mouse_led_mode.data()
        if mode is None:
            return
        rgb = self.mouse_picker.color() or (st.led_rgb if st is not None else None) or (255, 255, 255)
        self.ctl.mouse_set_led(int(mode), self.mouse_bright.value(), rgb)

    def _refresh_mouse_lighting_lock(self) -> None:
        managed = self._managed("mouse")
        self.mouse_managed.setVisible(managed)
        self.mouse_light.setEnabled(not managed)

    def _refresh_mouse(self) -> None:
        st = self.state.peripheral("mouse")
        kind, text = mouse_status(st)
        page = self.pages["mouse"]
        page.show_notice(None if kind == "ok" else text)
        if kind != "ok":
            return
        bat = fmt_pct(st.battery_pct)
        if st.charging:
            bat += " · " + tr("şarj oluyor")
        self.mouse_battery.setText(bat)
        stages = st.dpi_stages or []
        for i, sp in enumerate(self.mouse_spins):
            if not sp.hasFocus():
                sp.blockSignals(True)
                sp.setValue(stages[i] if i < len(stages) else 100)
                sp.blockSignals(False)
            sp.setEnabled(i < len(stages))
            active = st.dpi_stage == i + 1
            b = self.mouse_stage_btns[i]
            b.setText(tr("Etkin") if active else tr("Seç"))
            b.setStyleSheet(button_qss(self._accent, theme.INK, None, weight=600, pad=8) if active
                            else button_qss(theme.CONTROL, theme.TEXT, theme.BORDER, pad=8))
        self.mouse_polling.set_current(str(st.polling_hz) if st.polling_hz is not None else None)
        self.mouse_debounce.set_data(st.debounce_ms)
        self.mouse_angle.setChecked(bool(st.angle_snapping))
        self.mouse_angle.setEnabled(st.angle_snapping is not None)
        self.mouse_sleep.set_data(st.sleep_code)
        self.mouse_led_mode.set_data(st.led_mode)
        self.mouse_picker.set_color(st.led_rgb)
        if st.led_brightness is not None:
            self.mouse_bright.set_value_if_idle(st.led_brightness)
        self._refresh_mouse_lighting_lock()

    # ================================================================== Headset
    def _build_headset(self, page: _TabPage) -> None:
        c = page.clay
        c.addWidget(section_title(tr("Pil")))
        bp = Panel(12)
        self.headset_battery = label(DASH, 13, 600)
        bp.lay.addLayout(_row(tr("Pil"), self.headset_battery))
        self.headset_fw = label(DASH, 13, 600, theme.TEXT2)
        bp.lay.addLayout(_row(tr("Yazılım sürümü"), self.headset_fw))
        c.addWidget(bp)

        c.addWidget(section_title(tr("Aydınlatma")))
        lp = Panel(12)
        lp.lay.setSpacing(10)
        self.headset_managed = _note(tr("Aura Sync tarafından yönetiliyor"), theme.WARN_ACCENT)
        lp.lay.addWidget(self.headset_managed)
        self.headset_light = QWidget()
        ll = QVBoxLayout(self.headset_light)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        self.headset_effect = Segmented([(str(e), tr(t)) for e, t in HEADSET_EFFECTS], height=32, stretch=True)
        self.headset_effect.changed.connect(lambda _k: self._headset_light())
        ll.addWidget(self.headset_effect)
        self.headset_picker = ColorPicker()
        self.headset_picker.colorPicked.connect(lambda _rgb: self._headset_light())
        ll.addWidget(self.headset_picker)
        self.headset_bright = ValueSlider(tr("Parlaklık"), tr("0 = kapalı"), 0, 100, 1, " %", label_width=84,
                                          value_width=50)
        self.headset_bright.committed.connect(lambda _v: self._headset_light())
        ll.addWidget(self.headset_bright)
        lp.lay.addWidget(self.headset_light)
        c.addWidget(lp)

    def _headset_light(self) -> None:
        st = self.state.peripheral("headset")
        eff = self.headset_effect.current()
        if eff is None:
            return
        rgb = self.headset_picker.color() or (st.light_rgb if st is not None else None) or (255, 255, 255)
        self.ctl.headset_set_lighting(int(eff), self.headset_bright.value(), rgb)

    def _refresh_headset_lighting_lock(self) -> None:
        managed = self._managed("headset")
        self.headset_managed.setVisible(managed)
        self.headset_light.setEnabled(not managed)

    def _refresh_headset(self) -> None:
        st = self.state.peripheral("headset")
        kind, text = headset_status(st)
        self.pages["headset"].show_notice(None if kind == "ok" else text)
        if kind != "ok":
            return
        bat = fmt_pct(st.battery_pct)
        if st.charging:
            bat += " · " + tr("şarj oluyor")
        self.headset_battery.setText(bat)
        self.headset_fw.setText(st.firmware or DASH)
        self.headset_effect.set_current(str(st.light_effect) if st.light_effect is not None else None)
        self.headset_picker.set_color(st.light_rgb)
        if st.light_brightness is not None:
            self.headset_bright.set_value_if_idle(st.light_brightness)
        self._refresh_headset_lighting_lock()

    # ================================================================== Monitor
    def _build_monitor(self, page: _TabPage) -> None:
        from alaz.backend.ddc import FEATURES
        self._features = FEATURES
        c = page.clay
        # header (always visible, outside the notice/content switch)
        hp = Panel(12)
        row = QHBoxLayout()
        row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.mon_model = label(DASH, 14, 700)
        self.mon_serial = label("", 11.5, 400, theme.TEXT3)
        col.addWidget(self.mon_model)
        col.addWidget(self.mon_serial)
        row.addLayout(col, 1)
        self.mon_busy = label(tr("Okunuyor… birkaç saniye sürebilir"), 12, 500, theme.TEXT2)
        row.addWidget(self.mon_busy)
        self.mon_refresh = make_button(tr("Yenile"), "secondary", pad=14)
        self.mon_refresh.clicked.connect(self.ctl.refresh_monitor)
        row.addWidget(self.mon_refresh)
        hp.lay.addLayout(row)
        page.lay.insertWidget(0, hp)

        c.addWidget(section_title(tr("Görüntü")))
        gp = Panel(12)
        gp.lay.setSpacing(10)
        self.mon_bright = ValueSlider(tr("Parlaklık"), "", 0, 100, 1, " %", label_width=84, value_width=50)
        self.mon_bright.valueChanged.connect(lambda v: self.ctl.monitor_set("brightness", v))
        self.mon_contrast = ValueSlider(tr("Kontrast"), "", 0, 100, 1, " %", label_width=84, value_width=50)
        self.mon_contrast.valueChanged.connect(lambda v: self.ctl.monitor_set("contrast", v))
        gp.lay.addWidget(self.mon_bright)
        gp.lay.addWidget(self.mon_contrast)
        self.mon_combos: dict[str, StyledCombo] = {}
        self.mon_notes: dict[str, QLabel] = {}
        for key, title in (("gamevisual", "GameVisual"), ("color_temp", tr("Renk sıcaklığı")),
                           ("shadow_boost", "Shadow Boost"), ("blue_light", tr("Mavi ışık filtresi"))):
            gp.lay.addLayout(self._monitor_choice_row(key, title))
        c.addWidget(gp)

        c.addWidget(section_title(tr("OLED bakımı")))
        op = Panel(12)
        op.lay.setSpacing(10)
        op.lay.addLayout(self._monitor_choice_row("screen_move", tr("Ekran kaydırma (Screen Move)")))
        op.lay.addLayout(self._monitor_choice_row("pixel_clean_reminder", tr("Piksel temizleme hatırlatıcısı")))
        c.addWidget(op)

        c.addWidget(section_title(tr("Diğer")))
        xp = Panel(12)
        xp.lay.setSpacing(10)
        self.mon_hdr = label(DASH, 13, 600)
        xp.lay.addLayout(_row("HDR", self.mon_hdr))
        xp.lay.addLayout(self._monitor_choice_row("input", tr("Giriş kaynağı")))
        self.mon_input_note = _note(tr("Girişi USB-C dışına çevirirsen bu bilgisayarın görüntüsü monitörde kaybolur."))
        xp.lay.addWidget(self.mon_input_note)
        c.addWidget(xp)
        self.mon_header_panel = hp

    def _monitor_choice_row(self, key: str, title: str) -> QHBoxLayout:
        feat = self._features[key]
        combo = StyledCombo([(choice_label(txt), val) for val, txt in feat.choices.items()])
        combo.setMinimumWidth(170)
        note = _note("", theme.WARN_ACCENT)
        note.hide()
        self.mon_combos[key] = combo
        self.mon_notes[key] = note
        if key == "input":
            combo.activated.connect(lambda _i: self._input_chosen())
        else:
            combo.activated.connect(lambda _i, k=key: self._combo_write(combo, lambda v: self.ctl.monitor_set(k, v)))
        return _row(title, combo, note)

    def _input_chosen(self) -> None:
        combo = self.mon_combos["input"]
        value = combo.data()
        st = self.state.peripheral("monitor")
        current = st.values.get("input") if st is not None else None
        if value is None or value == current:
            return
        name = combo.currentText()
        ok = dialogs.ask(
            self, tr("Monitör girişi: {name}", name=name),
            tr("Monitör girişi {name} olarak değiştirilecek. USB-C dışındaki bir girişe geçersen bu bilgisayarın "
               "görüntüsü monitörde kaybolur; geri dönmek için monitörün kendi menüsünden girişi tekrar USB-C "
               "yapman gerekir. Devam edilsin mi?", name=name),
            tr("Girişi değiştir"), tr("Vazgeç"), self._accent)
        if ok:
            self.ctl.monitor_set_input(int(value))
        else:
            combo.set_data(current)      # revert the combo, nothing is sent

    def _refresh_monitor(self) -> None:
        st = self.state.peripheral("monitor")
        busy = self.is_busy("monitor")
        page = self.pages["monitor"]
        self.mon_busy.setVisible(busy)
        self.mon_refresh.setEnabled(not busy)
        present = st is not None and st.present
        self.mon_model.setText((st.model if present and st.model else None) or DASH)
        self.mon_serial.setText(tr("Seri no: {serial}", serial=st.serial) if present and st.serial else "")
        if not present:
            page.show_notice(tr("Monitör okunuyor…") if busy else tr("Bağlı değil"))
            return
        page.show_notice(None)
        v = st.values
        for key, slider in (("brightness", self.mon_bright), ("contrast", self.mon_contrast)):
            val = v.get(key)
            top = st.maxima.get(key) or 100
            slider.setEnabled(val is not None)
            if val is not None:
                if top != 100:
                    slider.set_range(0, top)
                slider.set_value_if_idle(val)
        for key, combo in self.mon_combos.items():
            locked = key in st.locked
            combo.set_data(v.get(key))
            combo.setEnabled(not locked and not busy)
            note = self.mon_notes[key]
            note.setText(tr("Bu modda kilitli") if locked else "")
            note.setVisible(locked)
        hdr = v.get("hdr")
        self.mon_hdr.setText(DASH if hdr is None else (tr("Kapalı") if hdr == 0 else tr("Açık")))
        self.mon_input_note.setVisible(True)

    def apply_enabled(self) -> None:
        # busy key "monitor": show the busy label and keep the controls from being used mid-read
        if hasattr(self, "mon_busy"):
            self._refresh_monitor()
