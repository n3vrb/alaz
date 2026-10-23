"""DevicesWindow offscreen (fake state/controller; nothing touches real devices)."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from alaz import i18n
from alaz.core.state import AuraSyncView
from alaz.ui.windows import devices_window, dialogs
from alaz.ui.windows._fake import FakeController, FakeState, fake_headset, fake_monitor, fake_mouse
from alaz.ui.windows.devices_window import DevicesWindow
from tests.windows.test_english_ui import assert_english, visible_texts


def make(**kw):
    st = FakeState("balanced")
    ctl = FakeController(st)
    w = DevicesWindow(st, ctl)
    w.show()
    QApplication.processEvents()
    return st, ctl, w


def tab(w, key):
    w.tabs.set_current(key, emit=True)
    QApplication.processEvents()


def test_opening_refreshes_monitor_once_and_renders_all_tabs():
    st, ctl, w = make()
    assert ctl.names().count("refresh_monitor") == 1
    for key in ("aura", "mouse", "headset", "monitor"):
        tab(w, key)
        assert w.stack.currentWidget() is w.pages[key]
        assert w.pages[key].grab().width() > 0
    assert w.mouse_battery.text() == "66 %"
    assert [sp.value() for sp in w.mouse_spins] == [400, 800, 1600, 3200]
    assert w.mouse_stage_btns[1].text() == "Etkin" and w.mouse_stage_btns[0].text() == "Seç"
    assert w.mouse_polling.current() == "1000" and w.mouse_debounce.currentText() == "12 ms"
    assert w.headset_battery.text() == "87 %"
    assert w.mon_model.text() == "XG27UCDMG"
    assert w.mon_combos["gamevisual"].currentText() == "Scenery"
    assert w.mon_combos["input"].currentText() == "USB-C"
    assert w.mon_hdr.text() == "Kapalı"
    assert ctl.calls and not [n for n in ctl.names() if n.startswith(("mouse_", "monitor_", "headset_", "aura_"))]


def test_unavailable_states():
    st, ctl, w = make()
    for mouse, text in ((fake_mouse(present=False), "Bağlı değil"), (fake_mouse(permission=False), "udev"),
                        (fake_mouse(asleep=True), "Fare uykuda")):
        st.set_peripheral("mouse", mouse)
        page = w.pages["mouse"]
        assert not page.notice_panel.isHidden() and page.content.isHidden()
        assert text in page.notice.text()
    st.set_peripheral("mouse", fake_mouse())
    assert w.pages["mouse"].notice_panel.isHidden() and not w.pages["mouse"].content.isHidden()
    st.set_peripheral("headset", fake_headset(connected=False))
    assert "Kulaklık kapalı" in w.pages["headset"].notice.text()
    st.set_peripheral("headset", fake_headset(present=False))
    assert "Bağlı değil" in w.pages["headset"].notice.text()
    st.set_peripheral("monitor", fake_monitor(present=False))
    assert "Bağlı değil" in w.pages["monitor"].notice.text()


def test_unknown_values_show_dash():
    st, ctl, w = make()
    st.set_peripheral("mouse", fake_mouse(battery_pct=None, polling_hz=None, debounce_ms=None, sleep_code=None))
    assert w.mouse_battery.text() == "—"
    assert w.mouse_polling.current() is None
    assert w.mouse_debounce.currentIndex() == -1 and w.mouse_debounce.placeholderText() == "—"
    st.set_peripheral("headset", fake_headset(battery_pct=None, firmware=None))
    assert w.headset_battery.text() == "—" and w.headset_fw.text() == "—"
    m = fake_monitor()
    st.set_peripheral("monitor", fake_monitor(values={**m.values, "contrast": None, "hdr": None}))
    assert w.mon_hdr.text() == "—" and not w.mon_contrast.isEnabled()


def test_mouse_writes_on_user_action_only():
    st, ctl, w = make()
    n = len(ctl.calls)
    st.set_peripheral("mouse", fake_mouse(dpi_stages=[500, 800, 1600, 3200]))   # programmatic: no writes
    assert len(ctl.calls) == n
    w.mouse_spins[0].setValue(1200)              # typing alone must not write (only editingFinished does)
    assert len(ctl.calls) == n
    w.mouse_spins[0].editingFinished.emit()
    assert ctl.calls[-1] == ("mouse_set_dpi", (0, 1200))
    w.mouse_spins[2].setValue(1630)              # rounded to the 50 DPI grid
    w.mouse_spins[2].editingFinished.emit()
    assert ctl.calls[-1] == ("mouse_set_dpi", (2, 1650))
    w.mouse_stage_btns[3].click()
    assert ctl.calls[-1] == ("mouse_set_active_stage", (4,))
    w.mouse_polling.set_current("500", emit=True)
    assert ctl.calls[-1] == ("mouse_set_polling", (500,))
    w.mouse_debounce.setCurrentIndex(w.mouse_debounce.findData(20))
    w.mouse_debounce.activated.emit(w.mouse_debounce.currentIndex())
    assert ctl.calls[-1] == ("mouse_set_debounce", (20,))
    w.mouse_sleep.setCurrentIndex(w.mouse_sleep.findData(0xFF))
    w.mouse_sleep.activated.emit(w.mouse_sleep.currentIndex())
    assert ctl.calls[-1] == ("mouse_set_sleep", (0xFF,))
    w.mouse_angle.toggle()
    assert ctl.calls[-1] == ("mouse_set_angle_snapping", (True,))
    w.mouse_led_mode.setCurrentIndex(w.mouse_led_mode.findData(1))
    w.mouse_led_mode.activated.emit(w.mouse_led_mode.currentIndex())
    assert ctl.calls[-1] == ("mouse_set_led", (1, 50, (0, 255, 0)))
    w.mouse_picker.hex.setText("#112233")
    w.mouse_picker.apply_btn.click()
    assert ctl.calls[-1] == ("mouse_set_led", (1, 50, (0x11, 0x22, 0x33)))


def test_headset_writes():
    st, ctl, w = make()
    w.headset_effect.set_current("4", emit=True)
    assert ctl.calls[-1] == ("headset_set_lighting", (4, 50, (0xEA, 0xB2, 0x15)))
    w.headset_picker.swatches[0].clicked.emit("#FF5A5F")
    assert ctl.calls[-1] == ("headset_set_lighting", (4, 50, (0xFF, 0x5A, 0x5F)))
    w.headset_bright.setValue(0)
    w.headset_bright.committed.emit(0)
    assert ctl.calls[-1][1][1] == 0


def test_aura_sync_panel_roundtrip_and_lock():
    st, ctl, w = make()
    assert not w.aura_enable.isChecked()
    assert w.aura_targets["mouse"].isEnabled()
    w.aura_enable.toggle()
    name, (view,) = ctl.calls[-1]
    assert name == "aura_sync_set" and view.enabled and view.targets == {"keyboard", "mouse", "headset"}
    assert w.aura_enable.isChecked()                    # fake controller published the new view
    w.aura_effect.set_current("cycle", emit=True)
    assert ctl.calls[-1][1][0].effect == "cycle"
    w.aura_targets["headset"].toggle()
    assert ctl.calls[-1][1][0].targets == {"keyboard", "mouse"}
    w.aura_picker.swatches[5].clicked.emit("#34C08A")
    assert ctl.calls[-1][1][0].color == (0x34, 0xC0, 0x8A)
    w.aura_bright.setValue(30, emit=True)
    assert ctl.calls[-1][1][0].brightness == 30
    # while Aura Sync manages mouse/keyboard-less devices their own lighting controls are disabled
    assert not w.mouse_light.isEnabled() and not w.mouse_managed.isHidden()
    assert w.headset_light.isEnabled() and w.headset_managed.isHidden()      # headset was deselected
    assert "Bağlı" in w.aura_targets["mouse"]._sub
    st.set_peripheral("mouse", fake_mouse(asleep=True))
    assert w.aura_targets["mouse"]._sub == "Fare uykuda"
    st.set_aura_sync(AuraSyncView(enabled=False))
    assert w.mouse_light.isEnabled()


def test_monitor_sliders_and_combos():
    st, ctl, w = make()
    w.mon_bright.setValue(55, emit=True)
    assert ctl.calls[-1] == ("monitor_set", ("brightness", 55))
    w.mon_combos["gamevisual"].setCurrentIndex(w.mon_combos["gamevisual"].findData(0x07))
    w.mon_combos["gamevisual"].activated.emit(0)
    assert ctl.calls[-1] == ("monitor_set", ("gamevisual", 0x07))


def test_locked_blue_light_disabled_with_hint():
    st, ctl, w = make()
    m = fake_monitor()
    st.set_peripheral("monitor", fake_monitor(locked={"blue_light"}, values={**m.values, "blue_light": None}))
    assert not w.mon_combos["blue_light"].isEnabled()
    assert not w.mon_notes["blue_light"].isHidden() and w.mon_notes["blue_light"].text() == "Bu modda kilitli"
    assert w.mon_combos["blue_light"].currentIndex() == -1
    assert w.mon_combos["shadow_boost"].isEnabled() and w.mon_notes["shadow_boost"].isHidden()


def test_input_switch_cancel_reverts_and_sends_nothing(monkeypatch):
    st, ctl, w = make()
    asked = []
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: asked.append(a) or False)
    combo = w.mon_combos["input"]
    combo.setCurrentIndex(combo.findData(0x0F))
    combo.activated.emit(combo.currentIndex())
    assert len(asked) == 1 and "USB-C" in asked[0][2]
    assert combo.data() == 0x1A                        # reverted
    assert not any(n in ("monitor_set_input", "monitor_set") for n in ctl.names())


def test_input_switch_confirmed_sends_once(monkeypatch):
    st, ctl, w = make()
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    combo = w.mon_combos["input"]
    combo.setCurrentIndex(combo.findData(0x11))
    combo.activated.emit(combo.currentIndex())
    assert ctl.calls[-1] == ("monitor_set_input", (0x11,))
    assert combo.data() == 0x11
    combo.activated.emit(combo.currentIndex())         # same value again: no dialog, no write
    assert ctl.names().count("monitor_set_input") == 1


def test_monitor_busy_state_never_blocks():
    st, ctl, w = make()
    tab(w, "monitor")
    st.emit_busy("monitor", True)
    assert not w.mon_busy.isHidden() and not w.mon_refresh.isEnabled()
    assert not w.mon_combos["input"].isEnabled()
    st.emit_busy("monitor", False)
    assert w.mon_busy.isHidden() and w.mon_refresh.isEnabled() and w.mon_combos["input"].isEnabled()
    w.mon_refresh.click()
    assert ctl.names().count("refresh_monitor") == 2


def test_choice_labels_have_english():
    from alaz.i18n_en import EN
    assert all(src in EN for src in devices_window.CHOICE_TR.values())
    assert all(t in EN for _c, t in devices_window.SLEEP_ITEMS + devices_window.LED_MODES
               + devices_window.HEADSET_EFFECTS)
    assert all(t in EN for _k, t in devices_window.AURA_EFFECT_ITEMS + devices_window.TARGET_LABELS)


def test_devices_window_english_has_no_turkish():
    i18n.set_language("en")
    st = FakeState("balanced")
    ctl = FakeController(st)
    w = DevicesWindow(st, ctl)
    w.show()
    variants = [
        lambda: None,
        lambda: st.set_aura_sync(AuraSyncView(True, "breathing", (1, 2, 3), 50, {"keyboard", "mouse", "headset"})),
        lambda: st.set_peripheral("mouse", fake_mouse(permission=False)),
        lambda: st.set_peripheral("mouse", fake_mouse(asleep=True)),
        lambda: st.set_peripheral("headset", fake_headset(connected=False)),
        lambda: st.set_peripheral("monitor", fake_monitor(locked={"blue_light", "shadow_boost"})),
        lambda: st.set_peripheral("monitor", fake_monitor(present=False)),
        lambda: (st.set_peripheral("mouse", fake_mouse(charging=True)),
                 st.set_peripheral("headset", fake_headset(charging=True))),
    ]
    for v in variants:
        v()
        for key in ("aura", "mouse", "headset", "monitor"):
            w.tabs.set_current(key, emit=True)
            QApplication.processEvents()
            texts = visible_texts(w)
            for combo in w.findChildren(devices_window.StyledCombo):
                texts += [combo.itemText(i) for i in range(combo.count())]
            assert_english(texts, f"devices/{key}")
