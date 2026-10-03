"""FansWindow (docs/design/V2Fans.dc.html): profile tiles, fan curve editor, power limits, NVIDIA, EPP, auto profile."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractButton, QHBoxLayout, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout,
                             QWidget)

from rog_control.i18n import tr
from rog_control.ui import theme
from rog_control.ui.widgets import FanCurveChart, Segmented, ValueSlider, make_button
from rog_control.ui.widgets._common import button_qss
from rog_control.ui.windows._base import (PERF_COLOR, PERF_KEYS, PERF_LABEL, POLICY_KEY, ChoiceButton, FramelessWindow,
                                          IconLabel, Panel, fmt_num, hline, label, request_perf, section_title)

log = logging.getLogger(__name__)

FANS = ("CPU", "GPU", "MID")
# EPP segmented key -> asusd Epp int (backend.types.Epp: PERFORMANCE=1, BALANCE_PERFORMANCE=2, BALANCE_POWER=3, POWER=4)
EPP_KEYS = (("performance", "Performans", 1), ("balance_performance", "Denge +", 2),
            ("balance_power", "Denge −", 3), ("power", "Tasarruf", 4))
EPP_PROP = {"quiet": "ThrottleQuietEpp", "balanced": "ThrottleBalancedEpp", "turbo": "ThrottlePerformanceEpp",
            "custom": "ThrottlePerformanceEpp"}
AUTO_ORDER = ("quiet", "balanced", "turbo")
DEFAULT_PL = (60, 90, 110)


class ChipButton(QAbstractButton):
    """Cycle chip: colour dot + label + chevron."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._key = "balanced"
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_key(self, key: str) -> None:
        self._key = key
        self.updateGeometry()
        self.update()

    def key(self) -> str:
        return self._key

    def sizeHint(self) -> QSize:
        w = QFontMetrics(theme.ui_font(13, 600)).horizontalAdvance(PERF_LABEL.get(self._key, "—"))
        return QSize(12 + 8 + 8 + w + 8 + 12 + 10, 32)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if not self.isEnabled():
            p.setOpacity(0.5)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.CONTROL))
        p.drawRoundedRect(r, 16, 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PERF_COLOR.get(self._key, theme.TEXT3)))
        p.drawEllipse(QRectF(12, 12, 8, 8))
        p.setFont(theme.ui_font(13, 600))
        p.setPen(QColor(theme.TEXT))
        tw = QFontMetrics(theme.ui_font(13, 600)).horizontalAdvance(PERF_LABEL.get(self._key, "—"))
        p.drawText(QRectF(28, 0, tw + 2, 32), Qt.AlignmentFlag.AlignVCenter, PERF_LABEL.get(self._key, "—"))
        # chevron-down
        from PyQt6.QtCore import QPointF
        cx, cy = 28 + tw + 14, 16
        pen = QPen(QColor(theme.TEXT2), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


class FansWindow(FramelessWindow):
    def __init__(self, state, controller, parent: QWidget | None = None):
        super().__init__(state, controller, tr("ROG Control — Fanlar & Güç"), 480, 920, back=True, parent=parent)
        self.edit_mode = state.perf_mode
        self.fan = "CPU"
        self._reset_sel = True
        self._curves: dict[str, dict[str, object]] = {}   # mode -> fan -> FanCurve
        self._work: dict[tuple[str, str], list[tuple[int, int]]] = {}
        self._ac, self._bat = "turbo", "quiet"
        self._build()
        self._select_profile(self.edit_mode, request=False)
        self._refresh_sensors(state.sensors)
        self._refresh_platform()
        self._refresh_perf()
        state.fanCurvesChanged.connect(self._on_curves)
        state.sensorsChanged.connect(self._refresh_sensors)
        state.platformChanged.connect(self._on_platform)
        state.perfModeChanged.connect(lambda _m: self._refresh_perf())

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        tb = self.titlebar.lay
        tb.addWidget(self.title_label(tr("Fanlar & Güç")))
        tb.addStretch(1)
        self.temp_lbl = label("", 12, 400, theme.TEXT3, rich=True)
        tb.addWidget(self.temp_lbl)
        self.add_window_buttons(minimize=False)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(True)
        scroll.verticalScrollBar().setStyleSheet(
            f"QScrollBar:vertical {{ background:{theme.BG}; width:8px; margin:0; }}"
            f"QScrollBar::handle:vertical {{ background:{theme.BORDER}; border-radius:4px; min-height:24px; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:{theme.BG}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }")
        inner = QWidget()
        inner.setObjectName("fansInner")
        inner.setStyleSheet(f"QWidget#fansInner {{ background:{theme.BG}; }}")
        scroll.viewport().setObjectName("fansVp")
        scroll.viewport().setStyleSheet(f"QWidget#fansVp {{ background:{theme.BG}; }}")
        scroll.setWidget(inner)
        BodyLay = QVBoxLayout(self.body)
        BodyLay.setContentsMargins(0, 0, 0, 0)
        BodyLay.addWidget(scroll)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)

        # DÜZENLENEN PROFİL
        lay.addWidget(section_title(tr("Düzenlenen profil")))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.profile_btns: dict[str, ChoiceButton] = {}
        for k in PERF_KEYS:
            b = ChoiceButton(PERF_LABEL[k], PERF_COLOR[k], 44, 10, dot=True)
            b.clicked.connect(lambda _=False, key=k: self._select_profile(key))
            row.addWidget(b)
            self.profile_btns[k] = b
        lay.addLayout(row)

        # FAN EĞRİSİ
        cp = Panel(14)
        cp.lay.setContentsMargins(12, 12, 12, 10)
        cp.lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(section_title(tr("Fan eğrisi")))
        top.addStretch(1)
        self.fan_seg = Segmented([("CPU", "CPU", "—"), ("GPU", "GPU", "—"), ("MID", "MID", "—")], height=28, pad=10)
        self.fan_seg.set_current("CPU")
        self.fan_seg.changed.connect(self._fan_changed)
        top.addWidget(self.fan_seg)
        cp.lay.addLayout(top)
        self.chart = FanCurveChart()
        self.chart.set_selected(5)
        self.chart.selectionChanged.connect(lambda _i: self._update_note())
        cp.lay.addWidget(self.chart)
        bot = QHBoxLayout()
        bot.setSpacing(8)
        self.note = label("", 12, 400, theme.TEXT2)
        self.note.setWordWrap(True)
        self.note.setMinimumWidth(10)
        bot.addWidget(self.note, 1)
        self.btn_default = make_button(tr("Varsayılan"), "secondary")
        self.btn_apply = make_button(tr("Uygula"), "primary", PERF_COLOR[self.edit_mode], pad=16)
        self.btn_default.clicked.connect(self._reset_curves)
        self.btn_apply.clicked.connect(self._apply_curve)
        bot.addWidget(self.btn_default)
        bot.addWidget(self.btn_apply)
        cp.lay.addLayout(bot)
        lay.addWidget(cp)

        # CPU GÜÇ LİMİTLERİ
        pp = Panel(14)
        pp.lay.setContentsMargins(12, 12, 12, 12)
        pp.lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(section_title(tr("CPU güç limitleri")))
        head.addStretch(1)
        self.limit_badge = label("", 11.5, 600)
        self.limit_badge.setFixedHeight(22)
        head.addWidget(self.limit_badge)
        pp.lay.addLayout(head)
        self.limit_stack = QStackedWidget()
        page_sl = QWidget()
        sl = QVBoxLayout(page_sl)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)
        self.pl_sliders: list[ValueSlider] = []
        get_limits = getattr(self.ctl, "custom_limits", None)
        pl = tuple(get_limits()) if callable(get_limits) else DEFAULT_PL
        for lab, sub, lo, hi, v in (("PL1 · SPL", tr("Sürekli güç"), 15, 120, pl[0]),
                                   ("PL2 · SPPT", tr("Kısa süreli"), 15, 150, pl[1]),
                                   ("FPPT", tr("Anlık tepe"), 15, 170, pl[2])):
            s = ValueSlider(lab, sub, lo, hi, 1, " W")
            s.setValue(v)
            s.committed.connect(lambda _v: self._commit_limits())
            sl.addWidget(s)
            self.pl_sliders.append(s)
        self.custom_hint = label("", 11.5, 400, theme.TEXT3)
        self.custom_hint.setWordWrap(True)
        self.btn_enable_custom = make_button(tr("Özel modu etkinleştir"), "secondary", height=30)
        self.btn_enable_custom.clicked.connect(lambda: request_perf(self.ctl, "custom"))
        hint_row = QHBoxLayout()
        hint_row.addWidget(self.custom_hint, 1)
        hint_row.addWidget(self.btn_enable_custom)
        sl.addLayout(hint_row)
        self.limit_stack.addWidget(page_sl)
        page_note = QWidget()
        page_note.setObjectName("fwnote")
        page_note.setStyleSheet(f"QWidget#fwnote {{ background:{theme.PANEL_DARK}; border-radius:10px; }}")
        nl = QHBoxLayout(page_note)
        nl.setContentsMargins(12, 10, 12, 10)
        nl.setSpacing(10)
        nl.addWidget(IconLabel("shield", theme.TEXT2, 18, 2.0))
        self.fw_note = label("", 12.5, 400, theme.TEXT_TILE, rich=True)
        self.fw_note.setWordWrap(True)
        nl.addWidget(self.fw_note, 1)
        self.btn_goto_custom = make_button(tr("Özel’e geç"), "secondary", height=32, pad=12)
        self.btn_goto_custom.clicked.connect(lambda: self._select_profile("custom"))
        nl.addWidget(self.btn_goto_custom)
        self.limit_stack.addWidget(page_note)
        pp.lay.addWidget(self.limit_stack)
        lay.addWidget(pp)

        # NVIDIA
        np_ = Panel(14)
        np_.lay.setContentsMargins(12, 12, 12, 12)
        np_.lay.setSpacing(10)
        np_.lay.addWidget(section_title("NVIDIA"))
        self.nv_boost = ValueSlider("Dynamic Boost", "5 – 25 W", 5, 25, 1, " W")
        self.nv_temp = ValueSlider(tr("Sıcaklık hedefi"), "75 – 87 °C", 75, 87, 1, " °C")
        self.nv_boost.committed.connect(lambda v: self.ctl.set_nv_boost(int(v)))
        self.nv_temp.committed.connect(lambda v: self.ctl.set_nv_temp_target(int(v)))
        np_.lay.addWidget(self.nv_boost)
        np_.lay.addWidget(self.nv_temp)
        lay.addWidget(np_)

        # EPP
        ep = Panel(14)
        ep.lay.setContentsMargins(12, 12, 12, 12)
        ep.lay.setSpacing(10)
        eh = QHBoxLayout()
        eh.addWidget(section_title(tr("Enerji tercihi (EPP)")))
        eh.addStretch(1)
        self.epp_for = label("", 11.5, 400, theme.TEXT3)
        eh.addWidget(self.epp_for)
        ep.lay.addLayout(eh)
        self.epp_seg = Segmented([(k, tr(t)) for k, t, _ in EPP_KEYS], height=28, font_px=12.5, pad=10, stretch=True)
        self.epp_seg.changed.connect(self._epp_changed)
        ep.lay.addWidget(self.epp_seg)
        lay.addWidget(ep)

        # OTOMATİK GEÇİŞ
        ap = Panel(14)
        ap.lay.setContentsMargins(12, 4, 12, 4)
        ap.lay.setSpacing(0)
        self.chip_ac, self.chip_bat = ChipButton(), ChipButton()
        self.chip_ac.clicked.connect(lambda: self._cycle("ac"))
        self.chip_bat.clicked.connect(lambda: self._cycle("bat"))
        for i, (icon, text, chip) in enumerate((("plug", tr("Prize takılınca"), self.chip_ac),
                                                ("battery", tr("Pilde"), self.chip_bat))):
            r = QHBoxLayout()
            r.setContentsMargins(0, 0, 0, 0)
            r.setSpacing(10)
            r.addWidget(IconLabel(icon, theme.TEXT2, 16, 2.0))
            r.addWidget(label(text, 13, 500), 1)
            r.addWidget(chip)
            w = QWidget()
            w.setFixedHeight(48)
            w.setLayout(r)
            ap.lay.addWidget(w)
            if i == 0:
                ap.lay.addWidget(hline())
        lay.addWidget(ap)
        lay.addStretch(1)

        # In-card controls follow the EDITED profile colour (mockup); window chrome keeps the active accent,
        # so these are deliberately not registered with track_accent().
        self._edit_widgets = (self.chart, self.fan_seg, self.epp_seg, self.nv_boost, self.nv_temp, *self.pl_sliders)
        self._apply_edit_color()

    def _apply_edit_color(self) -> None:
        col = PERF_COLOR[self.edit_mode]
        for w in self._edit_widgets:
            w.set_accent(col)
        self.btn_apply.setStyleSheet(button_qss(col, theme.INK, None, weight=600, pad=16))

    # ------------------------------------------------------------- profiles
    def _select_profile(self, mode: str, request: bool = True) -> None:
        self._stash_edits()
        self.edit_mode = mode
        self._reset_sel = True
        self._apply_edit_color()
        for k, b in self.profile_btns.items():
            b.set_selected(k == mode)
        self._show_curve()
        self._refresh_limits_page()
        if request:
            self.ctl.load_fan_curves(mode)

    def showEvent(self, e):
        super().showEvent(e)
        # unapplied edits survive this reload (see _on_curves)
        self.ctl.load_fan_curves(self.edit_mode)

    def accent_applied(self, accent: str) -> None:
        # chrome only; in-card controls use the edited profile colour
        self._refresh_limits_page()

    def _refresh_perf(self) -> None:
        self._refresh_limits_page()

    # ------------------------------------------------------------------ curves
    def _baseline(self, mode: str, fan: str) -> list[tuple[int, int]] | None:
        c = self._curves.get(mode, {}).get(fan)
        return list(zip(c.temps, c.percent())) if c is not None else None

    def _stash_edits(self) -> None:
        """Remember the chart's unapplied edits for (edit_mode, fan); drop the entry if it equals the baseline."""
        key = (self.edit_mode, self.fan)
        pts = self.chart.points()
        if not pts:
            return
        if pts == self._baseline(*key):
            self._work.pop(key, None)
        else:
            self._work[key] = pts

    def _on_curves(self, mode: str, curves) -> None:
        # Keep unapplied edits: stash them against the OLD baseline first, then swap the baseline and drop
        # only the work entries that now equal the new baseline (e.g. right after Uygula).
        self._stash_edits()
        self._curves[mode] = {c.fan: c for c in curves}
        for k in [k for k in self._work if k[0] == mode]:
            if self._work[k] == self._baseline(*k):
                del self._work[k]
        self._show_curve()

    def _reset_curves(self) -> None:
        """Varsayılan: the user explicitly discards edits for this profile."""
        for k in [k for k in self._work if k[0] == self.edit_mode]:
            del self._work[k]
        self._show_curve()
        self.ctl.reset_fan_curves(self.edit_mode)

    def _show_curve(self) -> None:
        c = self._curves.get(self.edit_mode, {}).get(self.fan)
        key = (self.edit_mode, self.fan)
        if key in self._work:
            pts = self._work[key]
        elif c is not None:
            pts = list(zip(c.temps, c.percent()))
        else:
            pts = []
        self.chart.set_points(pts)
        if pts and self._reset_sel:
            self._reset_sel = False
            self.chart.set_selected(min(5, len(pts) - 1))
        self.chart.set_editable(bool(pts))
        self._update_temp()
        self._update_note()

    def _fan_changed(self, fan: str) -> None:
        self._stash_edits()
        self.fan = fan
        self._reset_sel = True
        self._show_curve()

    def _update_note(self) -> None:
        n = len(self.chart.points())
        self.note.setText(tr("Nokta {i}/{n} seçili · sürükle veya ok tuşlarıyla ayarla",
                             i=self.chart.selected_index() + 1, n=n) if n else tr("Eğri okunuyor…"))

    def _apply_curve(self) -> None:
        pts = self.chart.points()
        if pts:
            self.ctl.apply_fan_curve(self.edit_mode, self.fan, pts)

    def _update_temp(self) -> None:
        s = self.state.sensors
        t = None
        if s is not None:
            t = s.gpu_temp if self.fan == "GPU" else s.cpu_temp
        self.chart.set_current_temp(t)

    def _refresh_sensors(self, s) -> None:
        if s is None:
            return
        rpm = s.fans_rpm or {}
        for f in FANS:
            v = rpm.get(f.lower())
            self.fan_seg.set_item_suffix(f, "—" if v is None else str(v))
        cpu = rpm.get("cpu")
        self.temp_lbl.setText(f'CPU <b style="color:{theme.TEXT}; font-weight:600">{fmt_num(s.cpu_temp)} °C</b>'
                              f' · <b style="color:{theme.TEXT}; font-weight:600">{fmt_num(cpu)}</b> rpm')
        self._update_temp()

    # --------------------------------------------------------------- limits page
    def _refresh_limits_page(self) -> None:
        is_custom = self.edit_mode == "custom"
        self.limit_stack.setCurrentIndex(0 if is_custom else 1)
        for i in range(self.limit_stack.count()):  # stack height follows the visible page only
            self.limit_stack.widget(i).setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred if i == self.limit_stack.currentIndex()
                else QSizePolicy.Policy.Ignored)
        self.limit_badge.setText(tr("Özel") if is_custom else tr("Firmware"))
        self.limit_badge.setStyleSheet(
            (f"background:{self._accent}; color:{theme.INK};" if is_custom else f"background:{theme.BORDER}; color:{theme.TEXT_TILE};")
            + " border-radius:11px; padding:0 9px; font-size:11.5px; font-weight:600;")
        for s in self.pl_sliders:
            s.setEnabled(is_custom and not self.is_busy("perf"))
        self._sync_limit_sliders()
        active = self.state.perf_mode == "custom"
        self.custom_hint.setText(tr("Değerler bırakınca uygulanır.") if active else
                                 tr("Özel mod etkin değil: değerler kaydedilir, Özel seçilince uygulanır."))
        self.btn_enable_custom.setVisible(not active)
        self.fw_note.setText(tr("{mode} modunda limitleri firmware yönetir. Kendi limitlerin için {custom} profili seç.",
                                mode=PERF_LABEL[self.edit_mode],
                                custom=f'<b style="font-weight:600; color:{theme.TEXT}">{PERF_LABEL["custom"]}</b>'))
        self.epp_for.setText(tr("{mode} profili için", mode=PERF_LABEL[self.edit_mode]))
        self._refresh_epp()

    def _sync_limit_sliders(self) -> None:
        get_limits = getattr(self.ctl, "custom_limits", None)
        if not callable(get_limits):
            return
        for s, v in zip(self.pl_sliders, get_limits()):
            s.set_value_if_idle(v)

    def _commit_limits(self) -> None:
        if self.edit_mode == "custom":
            self.ctl.set_custom_limits(*(s.value() for s in self.pl_sliders))
            # the controller clamps (pl2>=pl1, fppt>=pl2): show what was actually stored
            self._sync_limit_sliders()

    # ------------------------------------------------------------------- epp / nv / auto
    def _refresh_epp(self) -> None:
        v = self.state.platform.get(EPP_PROP[self.edit_mode])
        key = next((k for k, _t, n in EPP_KEYS if n == v), None)
        self.epp_seg.set_current(key)

    def _epp_changed(self, key: str) -> None:
        n = next(n for k, _t, n in EPP_KEYS if k == key)
        self.ctl.set_epp(self.edit_mode, n)

    def _on_platform(self, name: str, _v) -> None:
        """Update only the widget that owns the changed property (never fight a drag on the others)."""
        p = self.state.platform
        if name == "NvDynamicBoost" and p.get(name) is not None:
            self.nv_boost.set_value_if_idle(int(p[name]))
        elif name == "NvTempTarget" and p.get(name) is not None:
            self.nv_temp.set_value_if_idle(int(p[name]))
        elif name in ("ThrottlePolicyOnAc", "ThrottlePolicyOnBattery"):
            self._ac = POLICY_KEY.get(p.get("ThrottlePolicyOnAc"), self._ac)
            self._bat = POLICY_KEY.get(p.get("ThrottlePolicyOnBattery"), self._bat)
            self.chip_ac.set_key(self._ac)
            self.chip_bat.set_key(self._bat)
        elif name in EPP_PROP.values():
            self._refresh_epp()
        self.apply_enabled()

    def _refresh_platform(self) -> None:
        p = self.state.platform
        if p.get("NvDynamicBoost") is not None:
            self.nv_boost.set_value_if_idle(int(p["NvDynamicBoost"]))
        if p.get("NvTempTarget") is not None:
            self.nv_temp.set_value_if_idle(int(p["NvTempTarget"]))
        self.nv_boost.setEnabled(p.get("NvDynamicBoost") is not None and not self.is_busy("nv"))
        self.nv_temp.setEnabled(p.get("NvTempTarget") is not None and not self.is_busy("nv"))
        self._ac = POLICY_KEY.get(p.get("ThrottlePolicyOnAc"), self._ac)
        self._bat = POLICY_KEY.get(p.get("ThrottlePolicyOnBattery"), self._bat)
        self.chip_ac.set_key(self._ac)
        self.chip_bat.set_key(self._bat)
        self._refresh_epp()

    def _cycle(self, which: str) -> None:
        def nxt(k: str) -> str:
            return AUTO_ORDER[(AUTO_ORDER.index(k) + 1) % len(AUTO_ORDER)] if k in AUTO_ORDER else AUTO_ORDER[0]
        if which == "ac":
            self._ac = nxt(self._ac)
            self.chip_ac.set_key(self._ac)
        else:
            self._bat = nxt(self._bat)
            self.chip_bat.set_key(self._bat)
        self.ctl.set_auto_profile(self._ac, self._bat)

    # --------------------------------------------------------------------- busy
    def apply_enabled(self) -> None:
        b = self.is_busy
        self.btn_apply.setEnabled(not b("fan"))
        self.btn_default.setEnabled(not b("fan"))
        self.fan_seg.setEnabled(not b("fan"))
        self.epp_seg.setEnabled(not b("epp"))
        self.chip_ac.setEnabled(not b("auto"))
        self.chip_bat.setEnabled(not b("auto"))
        for s in self.pl_sliders:
            s.setEnabled(self.edit_mode == "custom" and not b("perf"))
        p = self.state.platform
        self.nv_boost.setEnabled(p.get("NvDynamicBoost") is not None and not b("nv"))
        self.nv_temp.setEnabled(p.get("NvTempTarget") is not None and not b("nv"))
