"""English mode: no window may show Turkish text. Built with the fakes (no real system access)."""
from __future__ import annotations

import re

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QMenu, QWidget

from rog_control import i18n
from rog_control.core.state import AppState
from rog_control.ui.windows import dialogs
from rog_control.ui.windows._fake import FakeController, FakeState, fake_curves, fake_sensors
from rog_control.ui.windows.fans_window import FansWindow
from rog_control.ui.windows.keyboard_window import KeyboardWindow
from rog_control.ui.windows.main_window import MainWindow
from rog_control.ui.windows.mini_window import MiniWindow
from rog_control.ui.windows.settings_window import SettingsWindow
from rog_control.ui.windows.tray import Tray

TURKISH_CHARS = re.compile("[çğıİöşüÇĞÖŞÜ]")
TURKISH_WORDS = re.compile(
    r"\b(Sessiz|Dengeli|Yeniden|Kapat|Uygula|Ayarlar|Klavye|Parlaklık|Renk|Vazgeç|Tamam|Devam|Sonra|Pilde|Prizde|"
    r"Otomatik|Ekran|Şarj|Kapalı|Uyku|Veri|Sistem|Pil|Standart|Düzelt|Güç|Fanlar|Performans|Düşük|Orta|Yüksek)\b",
    re.IGNORECASE)
# Explicit, deliberate exceptions: language names / the bilingual language row and restart hint.
ALLOWED = {"Türkçe", "English", "Dil / Language", "Değişiklik yeniden başlatınca uygulanır / Applies after restart"}
TAGS = re.compile(r"<[^>]+>")


@pytest.fixture(autouse=True)
def english():
    i18n.set_language("en")
    yield


def pump():
    QApplication.processEvents()


def make(perf="balanced"):
    st = FakeState(perf)
    return st, FakeController(st)


def visible_texts(root: QWidget) -> list[str]:
    out = [root.windowTitle()]
    widgets = [root, *root.findChildren(QWidget)]
    for w in widgets:
        out += [w.toolTip(), w.accessibleName()]
        if isinstance(w, QLabel):
            out.append(w.text())
        if isinstance(w, QAbstractButton):
            out.append(w.text())
        for attr in ("_label", "_text"):          # custom painted widgets (ModeTile, Pill, ...)
            v = getattr(w, attr, None)
            if isinstance(v, str):
                out.append(v)
        for it in getattr(w, "_items", []) or []:  # Segmented
            if isinstance(it, tuple):
                out += [x for x in it[1:] if isinstance(x, str)]
        if isinstance(w, QMenu):
            out += [a.text() for a in w.actions()]
        for a in w.actions():
            out.append(a.text())
        menu = w.menu() if hasattr(w, "menu") and callable(w.menu) else None
        if isinstance(menu, QMenu):
            out += [a.text() for a in menu.actions()]
    return [TAGS.sub("", t) for t in out if t]


def assert_english(texts: list[str], where: str) -> None:
    bad = []
    for t in texts:
        if t in ALLOWED:
            continue
        if TURKISH_CHARS.search(t) or TURKISH_WORDS.search(t):
            bad.append(t)
    assert not bad, f"{where}: Turkish text in English mode: {sorted(set(bad))}"


def test_sanity_marker_detects_turkish():
    with pytest.raises(AssertionError):
        assert_english(["Yeniden başlat"], "probe")


def sensor_variants():
    return [
        fake_sensors(),
        fake_sensors(gpu_state="active", gpu_temp=67, gpu_load=55, gpu_power_w=48, battery_status="Discharging",
                     on_ac=False, battery_power_w=26.4, system_power_w=26.4),
        fake_sensors(gpu_state="off", battery_status="Charging", on_ac=True, battery_power_w=65.2, system_power_w=104.0),
        fake_sensors(battery_status="Not charging", on_ac=True),
    ]


def test_main_window_english():
    for perf in ("quiet", "balanced", "turbo", "custom"):
        st, ctl = make(perf)
        w = MainWindow(st, ctl, QSettings())
        w.show()
        for s in sensor_variants():
            st.set_sensors(s)
            pump()
            assert_english(visible_texts(w), f"main/{perf}")
        for kw in (dict(boot="eco", pending="eco"), dict(active="eco", boot="eco", dgpu_disabled=True),
                   dict(active="eco", boot="standard", dgpu_disabled=True, pending=None),
                   dict(active="eco", boot="standard", pending="standard", dgpu_disabled=False),
                   dict(active="standard", boot="standard", pending=None, dgpu_disabled=False, power="sleep")):
            st.set_gfx(**kw)
            pump()
            assert_english(visible_texts(w), f"main/gfx {kw}")
        st.set_display(auto=True, current_hz=120)
        st.set_battery_limit(80)
        pump()
        assert_english(visible_texts(w), "main/display")
        # banner button/close and every Hz menu entry
        w.banner.set_action_visible(True)
        assert_english(visible_texts(w), "main/banner")
        w.hide()
    assert w.pill.text() in {"Silent", "Balanced", "Turbo", "Custom"}


def test_main_window_english_content():
    st, ctl = make("quiet")
    w = MainWindow(st, ctl, QSettings())
    assert w.pill.text() == "Silent"
    assert w.btn_set.text() == "Settings" and w.btn_kbd.text() == "Keyboard" and w.btn_fans.text() == "Fans & Power"
    assert "battery" in w.perf_desc.text().lower()
    assert w.sensor._fan.sub.parent() is not None
    assert w.perf_header._value.text().startswith("Auto: ")


def test_fans_window_english():
    for mode in ("quiet", "balanced", "turbo", "custom"):
        st, ctl = make(mode)
        w = FansWindow(st, ctl)
        w.show()
        pump()
        assert_english(visible_texts(w), f"fans/{mode}")
        for other in ("custom", "quiet"):
            w._select_profile(other)
            w.fan_seg.set_current("GPU", emit=True)
            pump()
            assert_english(visible_texts(w), f"fans/{mode}->{other}")
        w.hide()
    assert w.note.text().startswith("Point ")
    assert w.btn_apply.text() == "Apply" and w.btn_default.text() == "Default"


def test_keyboard_settings_mini_english(tmp_path):
    st, ctl = make()
    kb = KeyboardWindow(st, ctl)
    kb.show()
    assert_english(visible_texts(kb), "keyboard")
    se = SettingsWindow(st, ctl, QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat),
                        autostart_path=tmp_path / "a.desktop", systemctl_runner=lambda args, cb: cb(0, "enabled"))
    se.show()
    for s in sensor_variants()[:1] + [fake_sensors(psys_available=False), fake_sensors(psys_available=None)]:
        st.set_sensors(s)
        assert_english(visible_texts(se), "settings")
    se._language_changed("tr")      # only the explicitly bilingual hint may be Turkish
    assert se.lang_note.text() == "Değişiklik yeniden başlatınca uygulanır / Applies after restart"
    mini = MiniWindow(st, ctl)
    mini.show()
    for s in sensor_variants():
        st.set_sensors(s)
        assert_english(visible_texts(mini), "mini")
        assert_english([mini.pwr_lbl.toolTip(), mini.pwr_lbl.text()], "mini power")


def test_tray_english():
    st, ctl = make()
    settings = QSettings()
    tray = Tray(st, ctl, settings)
    for s in sensor_variants():
        st.set_sensors(s)
        texts = [a.text() for a in tray.menu.actions()] + [tray.icon.toolTip()]
        assert_english(texts, "tray")
    texts = [a.text() for a in tray.menu.actions() if a.text() and a.isVisible()]
    head = ["ROG Control", tray.info.text()] + ([tray.power.text()] if tray.power.isVisible() else [])
    assert texts[:len(head) + 1] == head + ["PERFORMANCE"]
    if tray.power.isVisible():
        assert tray.power.text().startswith("Power: ")
    assert tray.act_quit.text() == "Quit" and tray.act_open.text() == "Open window"
    assert tray.perf_actions["quiet"].text() == "Silent"


def test_dialogs_english(monkeypatch):
    seen = []

    def fake_exec(self):
        seen.append([self.windowTitle(), *[lbl.text() for lbl in self.findChildren(QLabel)],
                     self.ok_btn.text(), self.cancel_btn.text()])
        return 0

    monkeypatch.setattr(dialogs.ConfirmDialog, "exec", fake_exec)
    dialogs.confirm_gpu_change(None, "eco")
    dialogs.confirm_gpu_change(None, "standard", leaving_eco=True)
    dialogs.confirm_reboot(None)
    dialogs.confirm_reboot_after_eco_exit(None)
    assert len(seen) == 4
    for texts in seen:
        assert_english(texts, "dialogs")
    assert seen[0][0] == "GPU mode: Eco" and seen[0][-2:] == ["Continue", "Cancel"]


def test_visible_texts_collects_something():
    st, ctl = make()
    w = MainWindow(st, ctl, QSettings())
    texts = visible_texts(w)
    for expected in ("Silent", "Eco", "Standard", "Refresh rate", "Charge limit", "Fans & Power", "FANS"):
        assert any(expected.lower() in t.lower() for t in texts), expected


def test_language_setting_is_stored_and_applies_after_restart(tmp_path):
    st, ctl = make()
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    se = SettingsWindow(st, ctl, settings, autostart_path=tmp_path / "a.desktop")
    assert se.lang_seg.current() == "auto"
    i18n.set_language("auto", locale_name="en_US")
    se.lang_seg.set_current("tr", emit=True)
    assert settings.value(i18n.KEY_LANGUAGE) == "tr"
    assert i18n.current_language() == "en"                      # not applied live
    assert "Applies after restart" in se.lang_note.text()
    se.lang_seg.set_current("auto", emit=True)
    assert settings.value(i18n.KEY_LANGUAGE) == "auto" and se.lang_note.text() == ""
    assert SettingsWindow(st, ctl, settings, autostart_path=tmp_path / "b.desktop").lang_seg.current() == "auto"
