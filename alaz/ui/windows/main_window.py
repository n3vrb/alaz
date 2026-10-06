"""MainWindow (docs/design/V2Main.dc.html): 480x920, no scrolling."""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from alaz.i18n import tr
from alaz.ui import theme
from alaz.ui.widgets import (Banner, ModeTileRow, PendingCard, SectionHeader, Segmented, SensorPanel,
                                    ToggleSwitch, ValueSlider, make_button, strong)
from alaz.ui.widgets.icons import draw_icon  # noqa: F401  (kept for parity with gallery usage)
from alaz.ui.windows import dialogs
from alaz.ui.windows._base import (is_quitting, request_quit, GPU_LABEL, PERF_COLOR, PERF_KEYS, PERF_LABEL, POLICY_KEY, FramelessWindow,
                                          IconLabel, NavButton, Panel, Pill, cpu_model_short, hline, label,
                                          request_perf)

log = logging.getLogger(__name__)

PERF_DESC = {
    "quiet": "Düşük fan devri, sessiz çalışma ve uzun pil ömrü.",
    "balanced": "Günlük kullanım: performans ile ses arasında denge.",
    "turbo": "En yüksek güç limitleri ve agresif fan eğrisi.",
    "custom": "Kendi güç limitlerin ve fan eğrin — Fanlar & Güç’ten düzenle.",
}
GPU_DESC = {
    "eco": "dGPU tamamen kapalı. En uzun pil ömrü; harici ekran çıkışları çalışmaz.",
    "standard": "iGPU çizer, dGPU gerektiğinde uyanır.",
    "ultimate": "MUX: ekran doğrudan dGPU’ya bağlı. En yüksek oyun performansı.",
}
BAT_STATUS = {"Charging": "Şarj oluyor", "Discharging": "Boşalıyor", "Full": "Dolu", "Not charging": "Şarj olmuyor"}
GPU_REBOOT_SUB = {"eco": "Açık işlerini kaydet. Harici monitör bu modda çalışmaz.",
                  "standard": "Açık işlerini kaydet. Geçiş açılışta uygulanır."}
NOT_SUPPORTED = "Henüz desteklenmiyor"
HZ_QUICK = (60, 120, 240)


class MainWindow(FramelessWindow):
    openFans = pyqtSignal()
    openKeyboard = pyqtSignal()
    openSettings = pyqtSignal()
    openMini = pyqtSignal()

    def __init__(self, state, controller, settings=None, tray_available=None, parent: QWidget | None = None):
        super().__init__(state, controller, "Alaz", 480, 920, parent=parent)
        self._settings = settings
        self._tray_available = tray_available or (lambda: False)
        self._build()
        self.refresh_all()
        state.perfModeChanged.connect(lambda _m: self._refresh_perf())
        state.sensorsChanged.connect(self._refresh_sensors)
        state.gfxChanged.connect(lambda _v: self._refresh_gfx())
        state.gfxChanged.connect(lambda _v: self._refresh_logo())
        state.displayChanged.connect(lambda _v: self._refresh_display())
        state.batteryLimitChanged.connect(lambda _v: self._refresh_battery_limit())
        state.platformChanged.connect(self._on_platform)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        tb = self.titlebar.lay
        tb.setContentsMargins(16, 0, 8, 0)
        from alaz.ui.app_icon import app_icon
        self._logo = QLabel()
        # QIcon.pixmap() already applies the screen's device pixel ratio in Qt 6;
        # scaling it again made the logo 2x too big and clipped on HiDPI screens.
        self._logo.setPixmap(app_icon(self.state.gfx.active).pixmap(22, 22))
        self._logo_mode = self.state.gfx.active
        self._logo.setScaledContents(True)
        self._logo.setFixedSize(22, 22)
        tb.addWidget(self._logo)
        tb.addSpacing(8)
        tb.addWidget(self.title_label("Alaz"))
        tb.addWidget(label("Zephyrus", 12, 400, theme.TEXT3))
        tb.addStretch(1)
        self.pill = Pill("", self._accent)
        tb.addWidget(self.pill)
        tb.addSpacing(-2)
        self.add_window_buttons()

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 14, 16, 0)
        lay.setSpacing(14)

        self.sensor = SensorPanel()
        self.sensor.set_cpu_model(cpu_model_short())
        lay.addWidget(self.sensor)

        self.banner = Banner(tr("Windows'tan kalan Eco ayarı"),
                             tr("dGPU firmware'de kapalı kalmış (dgpu_disable=1); bir sonraki GPU modu seçimi bunu düzeltir"),
                             tr("Düzelt"))
        self.banner.set_action_visible(False)
        self.banner.closed.connect(self.banner.hide)
        self.banner.hide()
        lay.addWidget(self.banner)

        # PERFORMANS
        self.perf_header = SectionHeader("gauge", tr("Performans"), "")
        self.perf_row = ModeTileRow([(k, PERF_LABEL[k], ic, PERF_COLOR[k]) for k, ic in
                                     zip(PERF_KEYS, ("moon", "gauge", "bolt", "sliders"))])
        self.perf_row.clicked.connect(lambda k: request_perf(self.ctl, k))
        self.perf_desc = label("", 12, 400, theme.TEXT2)
        lay.addLayout(self._section(self.perf_header, self.perf_row, self.perf_desc))

        # GPU MODU
        self.gpu_header = SectionHeader("chip", tr("GPU modu"), "")
        self.gpu_row = ModeTileRow([("eco", GPU_LABEL["eco"], "leaf", PERF_COLOR_GPU["eco"]),
                                    ("standard", GPU_LABEL["standard"], "layers", PERF_COLOR_GPU["standard"]),
                                    ("ultimate", GPU_LABEL["ultimate"], "chip", PERF_COLOR_GPU["ultimate"]),
                                    ("optimize", GPU_LABEL["optimize"], "refresh", PERF_COLOR_GPU["optimize"])])
        self.gpu_row.set_enabled("ultimate", False, tr(NOT_SUPPORTED))
        self.gpu_row.set_enabled("optimize", False, tr(NOT_SUPPORTED))
        self.gpu_row.clicked.connect(self._gpu_clicked)
        self.gpu_desc = label("", 12, 400, theme.TEXT2)
        self.pending = PendingCard()
        self.pending.rebootClicked.connect(lambda: dialogs.reboot_now(self, self.ctl, self._accent))
        if hasattr(self.ctl, "gpuRebootRequired"):
            self.ctl.gpuRebootRequired.connect(self._eco_exit_reboot_prompt)
        self.pending.cancelClicked.connect(lambda: self.ctl.cancel_gpu_pending())
        self.pending.hide()
        lay.addLayout(self._section(self.gpu_header, self.gpu_row, self.gpu_desc, self.pending))

        # EKRAN
        self.disp_header = SectionHeader("monitor", tr("Ekran"), "")
        panel = Panel(12)
        panel.lay.setContentsMargins(4, 4, 4, 4)
        panel.lay.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(10, 4, 4, 4)
        row.setSpacing(8)
        row.addWidget(label(tr("Yenileme hızı"), 13, 500), 1)
        self._hz_row = row
        self._hz_sig = None
        self.hz_seg = Segmented([("auto", tr("Otomatik"))], 30, 12.5, 12)
        self.hz_seg.changed.connect(self._hz_changed)
        self.hz_more = make_button("···", "ghost", height=30, pad=0)
        self.hz_more.setFixedSize(34, 30)
        self.hz_more.setToolTip(tr("Diğer yenileme hızları"))
        self.hz_more.setStyleSheet(self.hz_more.styleSheet() + "QPushButton::menu-indicator { image: none; width: 0; }")
        self._hz_menu = QMenu(self)
        self.hz_more.setMenu(self._hz_menu)
        row.addWidget(self.hz_seg)
        row.addWidget(self.hz_more)
        panel.lay.addLayout(row)
        sep = hline()
        sep_wrap = QHBoxLayout()
        sep_wrap.setContentsMargins(10, 4, 10, 4)
        sep_wrap.addWidget(sep)
        panel.lay.addLayout(sep_wrap)
        self.od = ToggleSwitch(tr("Panel Overdrive"), tr("Daha hızlı piksel tepkisi"))
        self.od.toggled.connect(lambda on: self.ctl.set_panel_od(bool(on)))
        od_wrap = QHBoxLayout()
        od_wrap.setContentsMargins(10, 0, 6, 0)
        od_wrap.addWidget(self.od)
        panel.lay.addLayout(od_wrap)
        lay.addLayout(self._section(self.disp_header, panel))

        # ŞARJ LİMİTİ
        self.bat_header = SectionHeader("battery", tr("Şarj limiti"), "")
        bp = Panel(12)
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.bat_seg = Segmented([("60", "60 %"), ("80", "80 %"), ("100", "100 %")])
        self.bat_seg.changed.connect(lambda k: self.ctl.set_battery_limit(int(k)))
        self.bat_slider = ValueSlider("", "", 20, 100, 5, " %", label_width=0, value_width=50, value_px=17)
        self.bat_slider.committed.connect(lambda v: self.ctl.set_battery_limit(int(v)))
        row2.addWidget(self.bat_seg)
        row2.addWidget(self.bat_slider, 1)
        bp.lay.addLayout(row2)
        lay.addLayout(self._section(self.bat_header, bp))

        lay.addStretch(1)
        nav = QHBoxLayout()
        nav.setSpacing(6)
        nav.setContentsMargins(0, 0, 0, 14)
        self.btn_fans = NavButton("fan", tr("Fanlar & Güç"))
        self.btn_kbd = NavButton("keyboard", tr("Klavye"))
        self.btn_set = NavButton("settings", tr("Ayarlar"))
        self.btn_mini = NavButton("expand", "", tr("Mini moda geç"))
        self.btn_light = NavButton("kbd_light", "", tr("Klavye ışığı aç/kapat"))
        self.btn_light.clicked.connect(self.ctl.toggle_kbd_light)
        self.state.auraChanged.connect(lambda _v: self._refresh_light())
        self.btn_fans.clicked.connect(self.openFans)
        self.btn_kbd.clicked.connect(self.openKeyboard)
        self.btn_set.clicked.connect(self.openSettings)
        self.btn_mini.clicked.connect(self.openMini)
        # Proportional widths so the longest label ("Fanlar & Güç" / "Fans & Power") isn't clipped
        # now that two 44 px icon buttons share the row.
        for b, stretch in ((self.btn_fans, 13), (self.btn_kbd, 10), (self.btn_light, 0),
                           (self.btn_set, 10), (self.btn_mini, 0)):
            nav.addWidget(b, stretch)
        lay.addLayout(nav)

        self.track_accent(self.perf_header, self.perf_row, self.gpu_header, self.gpu_row, self.disp_header, self.od,
                          self.hz_seg, self.bat_header, self.bat_seg, self.bat_slider, self.sensor)

    @staticmethod
    def _section(header, *widgets) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(10)
        v.addWidget(header)
        for w in widgets:
            v.addWidget(w)
        return v

    # ---------------------------------------------------------------- refresh
    def refresh_all(self) -> None:
        self._refresh_perf()
        self._refresh_sensors(self.state.sensors)
        self._refresh_gfx()
        self._refresh_display()
        self._refresh_battery()
        self._refresh_platform()
        self.apply_enabled()

    def accent_applied(self, accent: str) -> None:
        self._refresh_light()
        self.pill.set(PERF_LABEL.get(self.state.perf_mode, ""), accent)
        self.gpu_header.set_accent(accent)
        self.pending.set_accent(self._pending_color())

    def _refresh_logo(self) -> None:
        """Title-bar logo colour follows the active GPU mode."""
        from alaz.ui.app_icon import app_icon
        m = self.state.gfx.active
        if m != self._logo_mode:
            self._logo_mode = m
            self._logo.setPixmap(app_icon(m).pixmap(22, 22))

    def _refresh_perf(self) -> None:
        m = self.state.perf_mode
        self.perf_row.set_selected(m)
        self.perf_desc.setText(tr(PERF_DESC.get(m, "")))
        self.pill.set(PERF_LABEL.get(m, ""), self.state.accent)

    def _refresh_sensors(self, s) -> None:
        if s is None:
            return
        self.sensor.update(cpu_temp=s.cpu_temp, cpu_load=s.cpu_load, gpu_state=s.gpu_state, gpu_temp=s.gpu_temp,
                           gpu_load=s.gpu_load, gpu_power_w=s.gpu_power_w, fans=s.fans_rpm, ram_pct=s.ram_pct,
                           battery_pct=s.battery_pct, battery_status=s.battery_status, on_ac=s.on_ac,
                           battery_power_w=getattr(s, "battery_power_w", None),
                           system_power_w=getattr(s, "system_power_w", None))
        self._refresh_battery_text()

    def _reboot_required(self) -> bool:
        """Eco was left (dGPU re-enabled, drivers_autoprobe off): only a reboot completes it."""
        g = self.state.gfx
        return bool(g.pending == "standard" and g.active == "eco" and g.dgpu_disabled is False)

    def _pending_color(self) -> str:
        p = self.state.gfx.pending
        if self._reboot_required():
            return theme.WARN_ACCENT
        return PERF_COLOR_GPU.get(p, self._accent) if p else self._accent

    def _eco_exit_reboot_prompt(self) -> None:
        self._refresh_gfx()
        dialogs.reboot_now(self, self.ctl, self._accent, after_eco_exit=True)

    def _refresh_gfx(self) -> None:
        g = self.state.gfx
        self.gpu_header.set_value(tr("Etkin: {name}", name=strong(GPU_LABEL.get(g.active, "—") if g.active else "—")))
        self.gpu_row.set_selected(g.active)
        self.gpu_row.set_pending(g.pending)
        show_banner = bool(g.dgpu_disabled and g.active == "eco" and g.boot != "eco")
        self.banner.setVisible(show_banner)
        if g.pending:
            name = GPU_LABEL.get(g.pending, g.pending)
            urgent = self._reboot_required()
            if urgent:
                self.pending.set_content(tr("Yeniden başlatma gerekli"),
                                         tr("dGPU yeniden etkinleştirildi. Standart mod için bilgisayarı "
                                            "şimdi yeniden başlat."))
            else:
                self.pending.set_content(tr("{name} yeniden başlatınca etkin olacak", name=name),
                                         tr(GPU_REBOOT_SUB.get(g.pending, "Açık işlerini kaydet.")))
            self.pending.set_urgent(urgent)
            self.pending.set_accent(self._pending_color())
            self.pending.set_color(self._pending_color())
            self.pending.show()
            self.gpu_desc.hide()
        else:
            self.pending.hide()
            desc = tr(GPU_DESC.get(g.active or "", ""))
            if g.active == "standard":
                desc += " " + tr("Şu an dGPU uykuda.") if g.power == "sleep" else ""
            self.gpu_desc.setText(desc)
            self.gpu_desc.show()

    def _refresh_display(self) -> None:
        d = self.state.display
        rates = sorted(set(d.rates or []))
        quick = [r for r in HZ_QUICK if r in rates] or rates[:3]
        items = [(str(r), f"{r} Hz") for r in quick] + [("auto", tr("Otomatik"))]
        if self._hz_sig != tuple(items):
            self._hz_sig = tuple(items)
            old = self.hz_seg
            self.hz_seg = Segmented(items, 30, 12.5, 12)
            self.hz_seg.changed.connect(self._hz_changed)
            self.hz_seg.set_accent(self._accent)
            self._hz_row.replaceWidget(old, self.hz_seg)
            if old in self._accent_widgets:
                self._accent_widgets.remove(old)
            self._accent_widgets.append(self.hz_seg)
            old.deleteLater()
            self.hz_seg.setEnabled(not self.is_busy("refresh"))
        self._hz_menu.clear()
        for r in rates:
            a = self._hz_menu.addAction(f"{r} Hz")
            a.setCheckable(True)
            a.setChecked(not d.auto and d.current_hz == r)
            a.triggered.connect(lambda _=False, hz=r: self.ctl.set_refresh(hz))
        self.hz_more.setVisible(len(rates) > len(quick))
        cur = "auto" if d.auto else (str(d.current_hz) if d.current_hz else None)
        self.hz_seg.set_current(cur if cur in {k for k, _ in items} else None)
        cur_txt = "—" if d.current_hz is None else f"{d.current_hz} Hz" + (" " + tr("(otomatik)") if d.auto else "")
        self.disp_header.set_value(tr("Dahili panel · {value}", value=strong(cur_txt)))

    def _refresh_battery(self) -> None:
        self._refresh_battery_limit()
        self._refresh_battery_text()

    def _refresh_battery_limit(self) -> None:
        """Only on batteryLimitChanged (and initial fill); never from the 1 Hz sensor tick."""
        lim = self.state.battery_limit
        if lim is not None:
            self.bat_seg.set_current(str(lim) if lim in (60, 80, 100) else None)
            self.bat_slider.set_value_if_idle(lim)

    def _refresh_battery_text(self) -> None:
        s = self.state.sensors
        txt = ""
        if s is not None and s.battery_pct is not None:
            st = tr(BAT_STATUS.get(s.battery_status or "", ""))
            txt = tr("Pil {value}", value=strong(f"{s.battery_pct:.0f} %")) + (f" · {st}" if st else "")
        self.bat_header.set_value(txt)

    def _on_platform(self, name: str, _v) -> None:
        if name in ("PanelOd", "ThrottlePolicyOnAc", "ThrottlePolicyOnBattery"):
            self._refresh_platform()

    def _refresh_platform(self) -> None:
        p = self.state.platform
        od = p.get("PanelOd")
        if od is not None:
            self.od.setChecked(bool(od))
        self.od.setEnabled(od is not None and not self.is_busy("panel_od"))
        ac, bat = POLICY_KEY.get(p.get("ThrottlePolicyOnAc")), POLICY_KEY.get(p.get("ThrottlePolicyOnBattery"))
        if ac and bat:
            self.perf_header.set_value(tr("Otomatik: prizde {ac} · pilde {bat}", ac=strong(PERF_LABEL[ac]), bat=strong(PERF_LABEL[bat])))
        else:
            self.perf_header.set_value("")

    # ------------------------------------------------------------------ actions
    def _gpu_clicked(self, key: str) -> None:
        g = self.state.gfx
        if key == g.active:
            if g.pending:
                self.ctl.cancel_gpu_pending()
            return
        if key in ("eco", "standard"):
            dialogs.request_gpu_mode(self, self.ctl, key, PERF_COLOR_GPU[key],
                                     leaving_eco=(key == "standard" and g.active == "eco"))

    def _hz_changed(self, key: str) -> None:
        self.ctl.set_refresh(None if key == "auto" else int(key))

    # -------------------------------------------------------------------- busy
    def _refresh_light(self) -> None:
        if not hasattr(self, "btn_light"):
            return
        br = self.state.aura.brightness
        self.btn_light.setEnabled(br is not None and not self.is_busy("kbd"))
        self.btn_light.set_active(self._accent if br else None)

    def apply_enabled(self) -> None:
        b = self.is_busy
        self._refresh_light()
        self.perf_row.setEnabled(not b("perf"))
        self.gpu_row.setEnabled(not b("gpu"))
        self.gpu_row.set_enabled("ultimate", False, tr(NOT_SUPPORTED))
        self.gpu_row.set_enabled("optimize", False, tr(NOT_SUPPORTED))
        self.pending.setEnabled(not b("gpu"))
        self.hz_seg.setEnabled(not b("refresh"))
        self.hz_more.setEnabled(not b("refresh"))
        self.od.setEnabled(self.state.platform.get("PanelOd") is not None and not b("panel_od"))
        self.bat_seg.setEnabled(not b("battery"))
        self.bat_slider.setEnabled(not b("battery"))

    # ------------------------------------------------------------------- close
    def closeEvent(self, e: QCloseEvent) -> None:
        to_tray = True if self._settings is None else self._settings.value("ui/minimize_to_tray", True, type=bool)
        if to_tray and self._tray_available() and not is_quitting():
            e.ignore()
            self.hide()
            return
        e.accept()
        if not is_quitting():
            request_quit()

    def quit_for_real(self) -> None:
        request_quit()


PERF_COLOR_GPU = {"eco": theme.MODE_COLORS["Eco"], "standard": theme.MODE_COLORS["Standart"],
                  "ultimate": theme.MODE_COLORS["Ultimate"], "optimize": theme.MODE_COLORS["Optimize"]}
