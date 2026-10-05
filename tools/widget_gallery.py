#!/usr/bin/env python3
"""Widget gallery: every ui widget in its key states.

Render offscreen:  QT_QPA_PLATFORM=offscreen .venv/bin/python tools/widget_gallery.py --png out.png
Interactive:       .venv/bin/python tools/widget_gallery.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,  # noqa: E402
                             QWidget)

from alaz.ui import theme  # noqa: E402
from alaz.ui.widgets import (Banner, FanCurveChart, ModeTileRow, PendingCard, SectionHeader,  # noqa: E402
                                    Segmented, SensorPanel, ToggleSwitch, ValueSlider, strong)

C = theme.MODE_COLORS
PERF = [("Sessiz", "Sessiz", "moon", C["Sessiz"]), ("Dengeli", "Dengeli", "gauge", C["Dengeli"]),
        ("Turbo", "Turbo", "bolt", C["Turbo"]), ("Özel", "Özel", "sliders", C["Özel"])]
GPU = [("Eco", "Eco", "leaf", C["Eco"]), ("Standart", "Standart", "layers", C["Standart"]),
       ("Ultimate", "Ultimate", "chip", C["Ultimate"]), ("Optimize", "Optimize", "refresh", C["Optimize"])]
RAW_CPU = [(0, 2), (59, 10), (62, 15), (65, 20), (68, 25), (71, 32), (74, 39), (255, 46)]


class Panel(QFrame):
    """Card container matching the mockup panels (PANEL bg, BORDER, radius 12/14)."""

    def __init__(self, radius: int = 12, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"Panel {{ background:{theme.PANEL}; border:1px solid {theme.BORDER}; border-radius:{radius}px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.lay.setSpacing(8)


def col() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    w.setObjectName("root")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(12)
    return w, lay


def caption(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{theme.TEXT3}; font-size:11px; background:transparent")
    return l


def left_column() -> QWidget:
    w, lay = col()
    s1 = SensorPanel()
    s1.set_accent(C["Dengeli"])
    s1.set_cpu_model("285H")
    s1.update(cpu_temp=48, cpu_load=12, gpu_state="sleep", gpu_temp=None, gpu_load=None, gpu_power_w=None,
              fans={"cpu": 2300, "gpu": 2100, "mid": 3800}, ram_pct=38, battery_pct=90, battery_status="Full", on_ac=True)
    s2 = SensorPanel()
    s2.set_accent(C["Turbo"])
    s2.update(cpu_temp=81, cpu_load=74, gpu_state="active", gpu_temp=67, gpu_load=55, gpu_power_w=48,
              fans={"cpu": 4900, "gpu": 4700, "mid": 5200}, ram_pct=61, battery_pct=44, battery_status="Discharging", on_ac=False)
    s3 = SensorPanel()
    s3.set_accent(C["Sessiz"])
    s3.update()  # all None -> dashes
    s3.update(None, None, "off", None, None, None, {}, None, None, None, None)
    lay.addWidget(caption("SensorPanel: uyku / aktif pilde / veri yok"))
    for s in (s1, s2, s3):
        lay.addWidget(s)
    b = Banner("Windows'tan kalan Eco ayarı", "dGPU firmware'de kapalı kalmış (dgpu_disable=1)")
    lay.addWidget(b)

    h = SectionHeader("gauge", "Performans", f"Otomatik: prizde {strong('Turbo')} · pilde {strong('Sessiz')}")
    h.set_accent(C["Dengeli"])
    lay.addWidget(h)
    r = ModeTileRow(PERF)
    r.set_selected("Dengeli")
    lay.addWidget(r)
    lay.addWidget(caption("Günlük kullanım: performans ile ses arasında denge."))

    h2 = SectionHeader("chip", "GPU modu", f"Etkin: {strong('Standart')}")
    h2.set_accent(C["Dengeli"])
    lay.addWidget(h2)
    g = ModeTileRow(GPU)
    g.set_selected("Standart")
    g.set_pending("Eco")
    g.set_enabled("Ultimate", False, "Bu cihazda MUX anahtarı desteklenmiyor")
    lay.addWidget(g)
    pc = PendingCard()
    pc.set_accent(C["Eco"])
    pc.set_content("Eco yeniden başlatınca etkin olacak", "Açık işlerini kaydet. Harici monitör bu modda çalışmaz.")
    lay.addWidget(pc)

    h3 = SectionHeader("monitor", "Ekran", f"Dahili panel · 2560×1600 · {strong('240 Hz (prizde)')}")
    h3.set_accent(C["Dengeli"])
    lay.addWidget(h3)
    p = Panel()
    p.lay.setContentsMargins(14, 6, 10, 6)
    row = QHBoxLayout()
    lab = QLabel("Yenileme hızı")
    lab.setStyleSheet("font-size:13px; font-weight:500; background:transparent")
    row.addWidget(lab, 1)
    seg = Segmented([("60", "60 Hz"), ("240", "240 Hz"), ("auto", "Otomatik")])
    seg.set_accent(C["Dengeli"])
    seg.set_current("auto")
    row.addWidget(seg)
    p.lay.addLayout(row)
    sw = ToggleSwitch("Panel Overdrive", "Daha hızlı piksel tepkisi")
    sw.set_accent(C["Dengeli"])
    sw.setChecked(True)
    p.lay.addWidget(sw)
    lay.addWidget(p)

    h4 = SectionHeader("battery", "Şarj limiti", f"Pil {strong('90 %')} · Dolu")
    h4.set_accent(C["Dengeli"])
    lay.addWidget(h4)
    p2 = Panel()
    row2 = QHBoxLayout()
    row2.setSpacing(12)
    seg2 = Segmented([("60", "60 %"), ("80", "80 %"), ("100", "100 %")])
    seg2.set_accent(C["Dengeli"])
    seg2.set_current("80")
    row2.addWidget(seg2)
    vs = ValueSlider("", "", 20, 100, 5, " %", label_width=0, value_width=50, value_px=17)
    vs.set_accent(C["Dengeli"])
    vs.setValue(90)
    row2.addWidget(vs, 1)
    p2.lay.addLayout(row2)
    lay.addWidget(p2)
    lay.addStretch(1)
    return w


def right_column() -> QWidget:
    w, lay = col()
    lay.addWidget(SectionHeader("fan", "Fan eğrisi", f"Nokta {strong('6/8')} seçili"))
    p = Panel(14)
    p.lay.setContentsMargins(12, 12, 12, 10)
    fans = Segmented([("CPU", "CPU", "2300"), ("GPU", "GPU", "2100"), ("MID", "MID", "3800")], height=28, pad=10)
    fans.set_current("CPU")
    fans.set_accent(C["Turbo"])
    p.lay.addWidget(fans, 0, Qt.AlignmentFlag.AlignRight)
    ch = FanCurveChart()
    ch.set_accent(C["Turbo"])
    ch.set_points([(0, 10), (55, 20), (59, 25), (64, 36), (69, 46), (74, 58), (79, 72), (255, 86)])
    ch.set_selected(5)
    ch.set_current_temp(48)
    p.lay.addWidget(ch)
    lay.addWidget(p)

    lay.addWidget(caption("Salt okunur eğri + Dengeli (mavi) + sentinel 255 son noktası"))
    ch2 = FanCurveChart()
    ch2.set_accent(C["Dengeli"])
    ch2.set_points(RAW_CPU)
    ch2.set_selected(7)
    ch2.set_current_temp(66)
    ch2.set_editable(False)
    ch2.setMinimumHeight(190)
    lay.addWidget(ch2)

    p2 = Panel(14)
    p2.lay.setSpacing(10)
    hh = SectionHeader("sliders", "CPU güç limitleri", "")
    hh.set_accent(C["Özel"])
    p2.lay.addWidget(hh)
    for label, sub, lo, hi, v in (("PL1 · SPL", "Sürekli güç", 15, 120, 60), ("PL2 · SPPT", "Kısa süreli", 15, 150, 90),
                                 ("FPPT", "Anlık tepe", 15, 170, 110)):
        s = ValueSlider(label, sub, lo, hi, 1, " W")
        s.set_accent(C["Özel"])
        s.setValue(v)
        p2.lay.addWidget(s)
    dis = ValueSlider("Dynamic Boost", "5 – 25 W", 5, 25, 1, " W")
    dis.set_accent(C["Özel"])
    dis.setValue(5)
    dis.setEnabled(False)
    p2.lay.addWidget(dis)
    epp = Segmented([("p", "Performans"), ("bp", "Denge +"), ("bw", "Denge −"), ("s", "Tasarruf")], height=28,
                    font_px=12.5, pad=10, stretch=True)
    epp.set_accent(C["Özel"])
    epp.set_current("bw")
    p2.lay.addWidget(epp)
    lay.addWidget(p2)

    lay.addWidget(caption("Dört vurgu rengi: seçili kutucuk, anahtar, segmentli"))
    for name in ("Sessiz", "Dengeli", "Turbo", "Özel"):
        r = ModeTileRow(PERF)
        r.set_selected(name)
        r.set_accent(C[name])
        lay.addWidget(r)
    accents = QHBoxLayout()
    for name in ("Sessiz", "Dengeli", "Turbo", "Özel"):
        s = ToggleSwitch()
        s.set_accent(C[name])
        s.setChecked(True)
        s.setFixedWidth(40)
        accents.addWidget(s)
        s2 = ToggleSwitch()
        s2.set_accent(C[name])
        s2.setFixedWidth(40)
        accents.addWidget(s2)
    lay.addLayout(accents)
    off = ToggleSwitch("Devre dışı anahtar")
    off.setEnabled(False)
    lay.addWidget(off)
    lay.addStretch(1)
    return w


def build_gallery() -> QWidget:
    root = QWidget()
    root.setObjectName("root")
    lay = QHBoxLayout(root)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for c in (left_column(), right_column()):
        c.setFixedWidth(480)
        lay.addWidget(c)
    root.setStyleSheet(f"QWidget#root {{ background:{theme.BG}; }}")
    return root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", help="render offscreen to this PNG and exit")
    args = ap.parse_args()
    app = QApplication(sys.argv)
    theme.apply(app)
    g = build_gallery()
    if args.png:
        g.adjustSize()
        g.resize(960, g.sizeHint().height())
        g.show()
        app.processEvents()
        g.resize(960, max(g.sizeHint().height(), g.minimumSizeHint().height()))
        app.processEvents()
        ok = g.grab().save(args.png)
        print(("saved " if ok else "FAILED ") + args.png)
        return 0 if ok else 1
    sc = QScrollArea()
    sc.setWidget(g)
    sc.resize(990, 900)
    sc.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
