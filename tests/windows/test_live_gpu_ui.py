"""P4: live GPU switching UI (tiles, busy/ultimate dialogs, failure toast, tray) against the fakes."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from alaz import i18n
from alaz.ui.windows import dialogs
from alaz.ui.windows._fake import FakeController, FakeHolder, FakeState
from alaz.ui.windows.main_window import MainWindow
from alaz.ui.windows.tray import Tray


@pytest.fixture(autouse=True)
def turkish():
    i18n.set_language("tr")
    yield


@pytest.fixture
def env(tmp_path):
    st = FakeState("balanced")
    st.set_gfx(live_ready=True)
    ctl = FakeController(st)
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    return st, ctl, settings


def test_live_click_requests_without_reboot_dialog(env, monkeypatch):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: pytest.fail("no confirm for live switch"))
    w.gpu_row.clicked.emit("eco")
    assert ("request_gpu_mode", ("eco",)) in ctl.calls
    assert st.gfx.active == "eco" and w.gpu_row.selected() == "eco"
    assert "yeniden başlat" not in w.gpu_desc.text().lower()


def test_not_live_ready_keeps_reboot_wording(env):
    st, ctl, settings = env
    st.set_gfx(live_ready=False)
    w = MainWindow(st, ctl, settings)
    assert "yeniden başlatınca" in w.gpu_desc.text()


def test_optimize_and_ultimate_click_go_to_controller(env, monkeypatch):
    st, ctl, settings = env
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: False)
    w = MainWindow(st, ctl, settings)
    w.gpu_row.clicked.emit("optimize")
    assert ("request_gpu_mode", ("optimize",)) in ctl.calls
    assert w.gpu_row.selected() == "optimize"
    assert "Standart" in w.gpu_desc.text() and "Etkin" in w.gpu_header._value.text()   # hardware mode still shown
    w.gpu_row.clicked.emit("ultimate")
    assert ("request_gpu_mode", ("ultimate",)) in ctl.calls


def test_switching_disables_all_tiles(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    st.set_gfx(switching=True)
    for k in w.gpu_row.keys():
        assert not w.gpu_row.is_enabled(k)
    assert w.gpu_desc.text() == "Geçiliyor…" and not w.gpu_desc.isHidden()
    w.gpu_row.clicked.emit("eco")                       # ignored while switching
    assert "request_gpu_mode" not in ctl.names()
    st.set_gfx(switching=False)
    assert all(w.gpu_row.is_enabled(k) for k in w.gpu_row.keys())


def test_mux_direct_disables_eco_and_optimize(env):
    st, ctl, settings = env
    st.set_gfx(active="ultimate", mux_direct=True)
    w = MainWindow(st, ctl, settings)
    assert not w.gpu_row.is_enabled("eco") and not w.gpu_row.is_enabled("optimize")
    assert w.gpu_row.tile("eco").toolTip() == "Ultimate modunda kullanılamaz"
    assert w.gpu_row.is_enabled("standard") and w.gpu_row.is_enabled("ultimate")
    st.emit_busy("gpu", True)
    st.emit_busy("gpu", False)
    assert not w.gpu_row.is_enabled("eco")              # rule survives a busy cycle


def test_waiting_shows_pending_line_and_cancel(env):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    w.show()
    st.set_gfx(waiting="eco", holders=[FakeHolder(), FakeHolder(pid=2), FakeHolder(pid=3, comm="steam", exe="/x/steam")])
    assert not w.pending.isHidden() and w.pending._reboot.isHidden() and not w.pending._cancel.isHidden()
    assert w.gpu_row.pending() == "eco"
    assert "blender, steam kapanınca Eco moduna geçilecek" in w.pending._sub.text()
    w.pending.cancelClicked.emit()
    assert "cancel_gpu_pending" in ctl.names() and w.pending.isHidden()
    w.hide()


def test_selected_tile_click_cancels_waiting(env):
    st, ctl, settings = env
    st.set_gfx(waiting="eco", selected="eco")
    w = MainWindow(st, ctl, settings)
    w.gpu_row.clicked.emit("eco")
    assert "cancel_gpu_pending" in ctl.names()


def test_holder_names_dedup_and_fallback():
    hs = [FakeHolder(), FakeHolder(pid=9), FakeHolder(comm="Xorg", exe=""), {"comm": "steam", "exe": None}]
    assert dialogs.holder_names(hs) == ["blender", "Xorg", "steam"]


@pytest.mark.parametrize("choice", ["wait", "reboot", "cancel"])
def test_busy_dialog_choice_calls_resolve_busy(env, monkeypatch, choice):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    seen = []
    monkeypatch.setattr(dialogs, "ask_busy", lambda parent, holders, accent=None: seen.append(holders) or choice)
    ctl.gpuBusy.emit([FakeHolder()])
    assert seen and ("resolve_busy", (choice,)) in ctl.calls


def test_busy_dialog_buttons(env):
    dlg = dialogs.BusyDialog(None, ["blender", "steam"])
    assert dlg.apps_label.text() == "blender, steam"
    assert dlg.wait_btn.text() == "Kapatınca geç" and dlg.reboot_btn.text() == "Yeniden başlatınca uygula"
    assert dlg.cancel_btn.text() == "Vazgeç"
    for btn, expect in ((dlg.wait_btn, "wait"), (dlg.reboot_btn, "reboot"), (dlg.cancel_btn, "cancel")):
        dlg.choice = None
        btn.click()
        assert dlg.choice == expect


@pytest.mark.parametrize("answer", [True, False])
def test_ultimate_dialog_calls_confirm(env, monkeypatch, answer):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    asked = []
    monkeypatch.setattr(dialogs, "ask", lambda parent, title, text, *a, **k: asked.append(text) or answer)
    w.gpu_row.clicked.emit("ultimate")        # fake controller emits gpuUltimateConfirm
    assert ("confirm_ultimate", (answer,)) in ctl.calls
    text = asked[0]
    assert "MUX" in text and "siyah" in text and "Ctrl+Alt+F3" in text and "G-Helper" in text and "Optimize" in text


def test_failure_toast_with_reboot_action(env, monkeypatch):
    st, ctl, settings = env
    w = MainWindow(st, ctl, settings)
    w.show()
    ctl.gpuSwitchFailed.emit("Geçiş başarısız", False)
    assert w.toast.isVisible() and w.toast._action.isHidden()
    ctl.gpuSwitchFailed.emit("Sürücü yüklenemedi", True)
    assert not w.toast._action.isHidden() and w.toast._action.text() == "Yeniden başlat"
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    w.toast._action.click()
    assert ctl.rebooted and not w.toast.isVisible()
    w.hide()


def test_tray_gpu_entries(env, monkeypatch):
    st, ctl, settings = env
    t = Tray(st, ctl, settings)
    assert list(t.gpu_actions) == ["eco", "standard", "ultimate", "optimize"]
    assert t.gpu_actions["standard"].isChecked()
    t.gpu_actions["eco"].trigger()
    assert ("request_gpu_mode", ("eco",)) in ctl.calls and t.gpu_actions["eco"].isChecked()
    t.gpu_actions["optimize"].trigger()
    assert t.gpu_actions["optimize"].isChecked() and not t.gpu_actions["eco"].isChecked()
    st.set_gfx(switching=True)
    assert not any(a.isEnabled() for a in t.gpu_actions.values())
    st.set_gfx(switching=False, active="ultimate", mux_direct=True, optimize=False, selected="ultimate")
    assert not t.gpu_actions["eco"].isEnabled() and not t.gpu_actions["optimize"].isEnabled()
    assert t.gpu_actions["ultimate"].isChecked()


def test_tray_failure_notification(env, monkeypatch):
    st, ctl, settings = env
    t = Tray(st, ctl, settings)
    shown = []
    monkeypatch.setattr(t.icon, "isVisible", lambda: True)
    monkeypatch.setattr(t.icon, "showMessage", lambda *a, **k: shown.append(a))
    ctl.gpuSwitchFailed.emit("hata", False)
    assert shown and shown[0][1] == "hata"
