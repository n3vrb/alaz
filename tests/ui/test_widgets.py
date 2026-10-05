import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QSignalSpy  # noqa: E402

from alaz.ui import theme  # noqa: E402
from alaz.ui.widgets import (Banner, FanCurveChart, ModeTileRow, PendingCard, SectionHeader,  # noqa: E402
                                    Segmented, SensorPanel, ToggleSwitch, ValueSlider)

OPTS = [("Eco", "Eco", "leaf", "#34C08A"), ("Standart", "Standart", "layers", "#4C8DFF"),
        ("Ultimate", "Ultimate", "chip", "#FF5A5F"), ("Optimize", "Optimize", "refresh", "#F2A93B")]
PTS = [(0, 2), (59, 10), (62, 15), (65, 20), (68, 25), (71, 32), (74, 39), (255, 46)]


def test_theme_qss_and_font(qtbot):
    assert "#4C8DFF" in theme.qss("#4C8DFF")
    assert theme.font_family()


# ---- ToggleSwitch -----------------------------------------------------------
def test_toggle_emits_on_knob_click(qtbot):
    sw = ToggleSwitch("Panel Overdrive", "alt")
    qtbot.addWidget(sw)
    sw.resize(300, sw.height())
    sw.show()
    spy = QSignalSpy(sw.toggled)
    knob = QPoint(sw.width() - 12, sw.height() // 2)
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=knob)
    assert sw.isChecked() and len(spy) == 1 and spy[0][0] is True
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=QPoint(sw.width() - 36, sw.height() // 2))  # track left part
    assert not sw.isChecked() and len(spy) == 2 and spy[1][0] is False


def test_toggle_emits_on_label_click_and_keyboard(qtbot):
    sw = ToggleSwitch("Panel Overdrive")
    qtbot.addWidget(sw)
    sw.resize(300, sw.height())
    sw.show()
    spy = QSignalSpy(sw.toggled)
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=QPoint(20, sw.height() // 2))
    assert sw.isChecked() and len(spy) == 1
    qtbot.keyClick(sw, Qt.Key.Key_Space)
    assert not sw.isChecked() and len(spy) == 2


def test_toggle_programmatic_set_is_silent_by_default(qtbot):
    sw = ToggleSwitch("x")
    qtbot.addWidget(sw)
    spy = QSignalSpy(sw.toggled)
    sw.setChecked(True)
    assert sw.isChecked() and len(spy) == 0
    sw.setChecked(False, emit=True)
    assert len(spy) == 1


def test_toggle_disabled_does_not_emit(qtbot):
    sw = ToggleSwitch("x")
    qtbot.addWidget(sw)
    sw.resize(200, 28)
    sw.show()
    sw.setEnabled(False)
    spy = QSignalSpy(sw.toggled)
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton, pos=QPoint(180, 14))
    assert len(spy) == 0


# ---- ModeTileRow ------------------------------------------------------------
def test_tile_row_selected_pending_api(qtbot):
    row = ModeTileRow(OPTS)
    qtbot.addWidget(row)
    row.resize(480, 90)
    row.show()
    row.set_selected("Standart")
    assert row.selected() == "Standart"
    assert row.tile("Standart").is_selected() and not row.tile("Eco").is_selected()
    row.set_pending("Eco")
    assert row.pending() == "Eco" and row.tile("Eco").is_pending()
    row.set_pending(None)
    assert row.pending() is None and not row.tile("Eco").is_pending()
    # selecting the pending key clears pending
    row.set_pending("Ultimate")
    row.set_selected("Ultimate")
    assert row.pending() is None


def test_tile_row_click_emits_key_and_disabled_blocks(qtbot):
    row = ModeTileRow(OPTS)
    qtbot.addWidget(row)
    row.resize(480, 90)
    row.show()
    spy = QSignalSpy(row.clicked)
    qtbot.mouseClick(row.tile("Eco"), Qt.MouseButton.LeftButton)
    assert [s[0] for s in spy] == ["Eco"]
    row.set_enabled("Ultimate", False, "MUX yok")
    assert row.tile("Ultimate").toolTip() == "MUX yok" and not row.is_enabled("Ultimate")
    qtbot.mouseClick(row.tile("Ultimate"), Qt.MouseButton.LeftButton)
    assert len(spy) == 1
    row.set_enabled("Ultimate", True)
    assert row.tile("Ultimate").toolTip() == ""


def test_tile_row_renders_all_states(qtbot):
    row = ModeTileRow(OPTS)
    qtbot.addWidget(row)
    row.resize(480, 90)
    row.set_selected("Standart")
    row.set_pending("Eco")
    row.set_enabled("Optimize", False, "x")
    row.set_accent("#FF5A5F")
    assert not row.grab().isNull()


# ---- FanCurveChart ----------------------------------------------------------
@pytest.fixture
def chart(qtbot):
    c = FanCurveChart()
    qtbot.addWidget(c)
    c.resize(454, 236)
    c.show()
    c.set_points(PTS)
    return c


def test_chart_roundtrip_keeps_sentinel(chart):
    assert chart.points() == PTS
    assert chart.points()[-1][0] == 255 and chart.points()[0][0] == 0


def test_chart_drag_is_monotonic_and_emits_edited_on_release(chart, qtbot):
    chart.set_selected(3)
    spy = QSignalSpy(chart.edited)
    start = chart._pos(3).toPoint()
    qtbot.mousePress(chart, Qt.MouseButton.LeftButton, pos=start)
    # drag far right: must stop strictly before next point (68)
    qtbot.mouseMove(chart, QPoint(chart.width() - 1, start.y() - 20))
    t3, p3 = chart.points()[3]
    assert t3 == 67 and p3 > 20
    assert len(spy) == 0  # only on release
    # drag far left: stop strictly after previous (62)
    qtbot.mouseMove(chart, QPoint(0, start.y()))
    assert chart.points()[3][0] == 63
    qtbot.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=QPoint(0, start.y()))
    assert len(spy) == 1
    ts = [t for t, _ in chart.points()]
    assert all(a < b for a, b in zip(ts[1:], ts[2:]))


def test_chart_drag_y_clamped(chart, qtbot):
    chart.set_selected(2)
    start = chart._pos(2).toPoint()
    qtbot.mousePress(chart, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(chart, QPoint(start.x(), -500))
    assert chart.points()[2][1] == 100
    qtbot.mouseMove(chart, QPoint(start.x(), 5000))
    assert chart.points()[2][1] == 0
    qtbot.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=QPoint(start.x(), 5000))


def test_chart_sentinel_survives_vertical_drag_and_is_replaced_when_moved(chart, qtbot):
    chart.set_selected(7)
    start = chart._pos(7).toPoint()
    qtbot.mousePress(chart, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(chart, QPoint(start.x(), start.y() - 10))
    qtbot.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=QPoint(start.x(), start.y() - 10))
    t, p = chart.points()[7]
    assert t == 255 and p > 46
    qtbot.keyClick(chart, Qt.Key.Key_Left)
    assert chart.points()[7][0] == 99


def test_chart_arrow_keys(chart, qtbot):
    chart.set_selected(4)
    spy = QSignalSpy(chart.edited)
    qtbot.keyClick(chart, Qt.Key.Key_Right)
    assert chart.points()[4] == (69, 25)
    qtbot.keyClick(chart, Qt.Key.Key_Up)
    assert chart.points()[4] == (69, 26)
    qtbot.keyClick(chart, Qt.Key.Key_Down)
    qtbot.keyClick(chart, Qt.Key.Key_Down)
    qtbot.keyClick(chart, Qt.Key.Key_Left)
    assert chart.points()[4] == (68, 24)
    assert len(spy) == 5
    # cannot cross the neighbour: 71 is point 5 -> max 70
    for _ in range(10):
        qtbot.keyClick(chart, Qt.Key.Key_Right)
    assert chart.points()[4][0] == 70
    n = len(spy)
    qtbot.keyClick(chart, Qt.Key.Key_Right)  # no change -> no edited()
    assert len(spy) == n


def test_chart_y_keys_clamped(chart, qtbot):
    chart.set_selected(0)
    for _ in range(5):
        qtbot.keyClick(chart, Qt.Key.Key_Down)
    assert chart.points()[0][1] == 0


def test_chart_tab_cycles_points(chart, qtbot):
    chart.setFocus()
    chart.set_selected(0)
    assert chart.focusNextPrevChild(True) and chart.selected_index() == 1
    assert chart.focusNextPrevChild(False) and chart.selected_index() == 0


def test_chart_not_editable_ignores_input(chart, qtbot):
    chart.set_editable(False)
    chart.set_selected(4)
    spy = QSignalSpy(chart.edited)
    qtbot.keyClick(chart, Qt.Key.Key_Right)
    start = chart._pos(4).toPoint()
    qtbot.mousePress(chart, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(chart, QPoint(start.x() + 3, start.y() - 30))
    qtbot.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=start)
    assert chart.points() == PTS and len(spy) == 0


def test_chart_current_temp_and_render(chart):
    chart.set_current_temp(48)
    chart.set_accent("#F2A93B")
    assert not chart.grab().isNull()


# ---- the rest -----------------------------------------------------------------
def test_segmented_exclusive_and_signal(qtbot):
    s = Segmented([("a", "60 Hz"), ("b", "240 Hz"), ("c", "Otomatik")])
    qtbot.addWidget(s)
    s.resize(s.sizeHint())
    s.show()
    s.set_current("a")
    spy = QSignalSpy(s.changed)
    r = s._rects()[2]
    qtbot.mouseClick(s, Qt.MouseButton.LeftButton, pos=r.center().toPoint())
    assert s.current() == "c" and [x[0] for x in spy] == ["c"]
    s.set_current("a")  # programmatic: silent
    assert len(spy) == 1


def test_value_slider_snaps_and_signals(qtbot):
    v = ValueSlider("PL1", "Sürekli", 20, 100, 5, " W")
    qtbot.addWidget(v)
    spy = QSignalSpy(v.valueChanged)
    v.setValue(63)
    assert v.value() == 65 and len(spy) == 0
    assert v._value.text() == "65 W"
    v.slider().setValue(v.slider().value() + 1)
    assert v.value() == 70 and spy[-1][0] == 70


def test_banner_and_pending_card_signals(qtbot):
    b = Banner("t", "s")
    qtbot.addWidget(b)
    b.show()
    a, c = QSignalSpy(b.actionClicked), QSignalSpy(b.closed)
    b._action.click()
    b._close.click()
    assert len(a) == 1 and len(c) == 1
    pc = PendingCard()
    qtbot.addWidget(pc)
    pc.set_content("Eco", "x")
    r, x = QSignalSpy(pc.rebootClicked), QSignalSpy(pc.cancelClicked)
    pc._reboot.click()
    pc._cancel.click()
    assert len(r) == 1 and len(x) == 1


def test_sensor_panel_none_and_values(qtbot):
    sp = SensorPanel()
    qtbot.addWidget(sp)
    sp.update(None, None, None, None, None, None, None, None, None, None, None)
    assert sp._cpu.big.text() == "—" and sp._fan.big.text() == "—"
    sp.update(cpu_temp=48.4, cpu_load=12, gpu_state="sleep", gpu_temp=None, gpu_load=None, gpu_power_w=None,
              fans={"cpu": 2300, "gpu": 2100, "mid": 3800}, ram_pct=38, battery_pct=90, battery_status="Full",
              on_ac=True)
    assert sp._cpu.big.text() == "48" and sp._gpu.big.text() == "Uyku"
    assert sp._fan.sub.text() == "GPU 2100 · MID 3800"
    assert "Dolu" in sp._bat.text() and sp._ac.text() == "Prizde"
    sp.update(cpu_temp=70, cpu_load=50, gpu_state="active", gpu_temp=65, gpu_load=40, gpu_power_w=30, fans={},
              ram_pct=None, battery_pct=None, battery_status=None, on_ac=False)
    assert sp._gpu.big.text() == "65" and sp._ac.text() == "Pilde" and "—" in sp._fan.sub.text()
    sp.update()  # plain repaint request still works
    assert not sp.grab().isNull()


def test_section_header_and_accent(qtbot):
    h = SectionHeader("gauge", "Performans", "x")
    qtbot.addWidget(h)
    h.set_accent("#FF5A5F")
    assert h.accent == "#FF5A5F" and h._title.text() == "PERFORMANS"


# ---- review regressions -------------------------------------------------------
def _wheel(qtbot, w, delta=120):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)
    QApplication.processEvents()
    return ev


def test_slider_wheel_is_ignored_and_never_commits(qtbot):
    s = ValueSlider("PL1", "", 20, 100, 5, " W")
    qtbot.addWidget(s)
    s.show()
    s.setValue(50)
    spy = QSignalSpy(s.committed)
    ev = _wheel(qtbot, s.slider())
    assert not ev.isAccepted()                  # passes on to the parent scroll area
    assert s.value() == 50 and len(spy) == 0
    assert s.slider().focusPolicy() == Qt.FocusPolicy.ClickFocus


def test_slider_keyboard_still_commits(qtbot):
    s = ValueSlider("PL1", "", 20, 100, 5, " W")
    qtbot.addWidget(s)
    s.show()
    s.setValue(50)
    spy = QSignalSpy(s.committed)
    qtbot.keyClick(s.slider(), Qt.Key.Key_Right)
    qtbot.waitUntil(lambda: len(spy) == 1)
    assert spy[0][0] == 55


def test_set_value_if_idle_skips_during_drag(qtbot):
    s = ValueSlider("PL1", "", 20, 100, 5, " W")
    qtbot.addWidget(s)
    s.setValue(50)
    s.slider().setSliderDown(True)
    assert s.set_value_if_idle(80) is False and s.value() == 50
    s.slider().setSliderDown(False)
    assert s.set_value_if_idle(80) is True and s.value() == 80


def test_sensor_panel_power_text(qtbot):
    sp = SensorPanel()
    qtbot.addWidget(sp)
    sp.update(battery_status="Discharging", on_ac=False, battery_power_w=26.4)
    assert sp._ac.text().startswith("Pilde") and "Sistem 26 W" in sp._ac.text()
    sp.update(battery_status="Charging", on_ac=True, battery_power_w=65.2)
    assert "Prizde" in sp._ac.text() and "Şarj +65 W" in sp._ac.text()
    sp.update(battery_status="Full", on_ac=True, battery_power_w=0.0)
    assert sp._ac.text() == "Prizde"
    sp.update(battery_status="Discharging", on_ac=False, battery_power_w=None)
    assert sp._ac.text() == "Pilde"
