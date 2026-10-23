"""Controller: Aura Sync, peripheral wiring and the monitor safety rules (fake backends only)."""
from __future__ import annotations

import dataclasses

import pytest
from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtWidgets import QApplication

from alaz import i18n
from alaz.backend.ddc import DdcClient, MonitorState
from alaz.backend.peripherals.headset import HeadsetState
from alaz.backend.peripherals.mouse import MouseState
from alaz.backend.types import Profile
from alaz.core.state import AuraSyncView
from tests.core.test_controller import Env


class FakeMouse(QObject):
    changed = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.polling = None

    def refresh(self):
        self.calls.append(("refresh",))

    def start_polling(self, ms=30_000):
        self.polling = ms

    def set_dpi_stage_value(self, i, dpi):
        self.calls.append(("dpi", i, dpi))

    def set_led(self, mode, brightness, rgb, save=True):
        self.calls.append(("led", mode, brightness, tuple(rgb), save))

    def set_polling(self, hz):
        self.calls.append(("polling", hz))


class FakeHeadset(QObject):
    changed = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.polling = None

    def refresh(self):
        self.calls.append(("refresh",))

    def start_polling(self, ms=30_000):
        self.polling = ms

    def set_lighting(self, effect, brightness, rgb):
        self.calls.append(("light", effect, brightness, tuple(rgb)))


class FakeDdc(QObject):
    """Real validate() rules (DdcClient.validate) with a recording runner."""
    changed = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def refresh(self):
        self.calls.append(("refresh",))

    def set_value(self, key, value, confirmed=False):
        self.calls.append(("set", key, value, confirmed))
        return True

    def set_value_debounced(self, key, value, ms=300):
        self.calls.append(("debounced", key, value))


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path, policy=Profile.BALANCED)     # standard env, then a controller with the peripheral fakes
    e.mouse, e.headset, e.ddc = FakeMouse(), FakeHeadset(), FakeDdc()
    from alaz.core.controller import Controller
    e.ctl = Controller(e.state, e.asusd, e.gfx, e.sensors, e.display, e.settings, mouse=e.mouse,
                       headset=e.headset, ddc=e.ddc, mux_path=str(e.mux), dbus_call=e.dbus)
    e.msgs.clear()
    return e


def view(**kw) -> AuraSyncView:
    base = dict(enabled=True, effect="static", color=(10, 20, 30), brightness=70,
                targets={"keyboard", "mouse", "headset"})
    base.update(kw)
    return AuraSyncView(**base)


def mouse_up(**kw):
    return MouseState(present=True, permission=True, asleep=False, battery_pct=66, **kw)


def headset_up(connected=True, **kw):
    return HeadsetState(present=True, permission=True, connected=connected, battery_pct=87, **kw)


def flush(e):
    """Fire the Aura Sync debounce timer now (and prove it was pending)."""
    assert e.ctl._aura_timer.isActive()
    e.ctl._aura_timer.stop()
    e.ctl._aura_flush()


def test_start_wires_peripherals_without_ddc_polling(env):
    env.ctl.start()
    assert env.mouse.polling == 30_000 and env.headset.polling == 30_000
    assert ("refresh",) in env.mouse.calls and ("refresh",) in env.headset.calls
    assert env.ddc.calls == []                      # DDC is never read at start or polled
    env.mouse.changed.emit(mouse_up())
    assert env.state.peripheral("mouse").battery_pct == 66
    env.ddc.changed.emit(MonitorState(present=True, model="X"))
    assert env.state.peripheral("monitor").model == "X"


def test_existing_construction_without_peripherals(tmp_path):
    e = Env(tmp_path, policy=Profile.BALANCED)
    e.ctl.start()
    e.ctl.mouse_set_dpi(0, 400)         # no backend -> silent no-ops
    e.ctl.headset_set_lighting(1, 50, (1, 2, 3))
    e.ctl.refresh_monitor()
    e.ctl.monitor_set("brightness", 10)
    assert e.msgs == []


def test_aura_sync_maps_each_target(env):
    env.ctl.start()
    env.mouse.changed.emit(mouse_up())
    env.headset.changed.emit(headset_up())
    env.mouse.calls.clear()
    env.headset.calls.clear()
    env.ctl.aura_sync_set(view(effect="breathing"))
    assert env.mouse.calls == [] and env.headset.calls == []       # debounced
    flush(env)
    assert env.mouse.calls == [("led", 1, 70, (10, 20, 30), True)]
    assert env.headset.calls == [("light", 2, 70, (10, 20, 30))]
    assert ("color", (10, 20, 30)) in env.asusd.calls              # keyboard: static colour only
    assert not any(c[0] == "kbd" for c in env.asusd.calls)         # never touches keyboard brightness
    env.mouse.calls.clear()
    env.headset.calls.clear()
    env.ctl.aura_sync_set(view(effect="cycle", color=(1, 2, 3), brightness=40))
    flush(env)
    assert env.mouse.calls == [("led", 2, 40, (1, 2, 3), True)]
    assert env.headset.calls == [("light", 4, 40, (1, 2, 3))]
    env.mouse.calls.clear()
    env.ctl.aura_sync_set(view(effect="static", color=(1, 2, 3), brightness=40))
    flush(env)
    assert env.mouse.calls == [("led", 0, 40, (1, 2, 3), True)]


def test_aura_sync_debounce_coalesces_slider_drag(env):
    env.ctl.start()
    env.mouse.changed.emit(mouse_up())
    env.mouse.calls.clear()
    for b in range(10, 60, 10):
        env.ctl.aura_sync_set(view(brightness=b))
    flush(env)
    assert [c for c in env.mouse.calls if c[0] == "led"] == [("led", 0, 50, (10, 20, 30), True)]


def test_aura_sync_skips_absent_and_unselected_targets(env):
    env.ctl.start()
    env.mouse.changed.emit(MouseState(present=False))
    env.headset.changed.emit(headset_up(connected=False))
    env.ctl.aura_sync_set(view())
    flush(env)
    assert env.mouse.calls == [("refresh",)] and env.headset.calls == [("refresh",)]
    env.ctl.aura_sync_set(view(targets={"keyboard"}))              # the mouse is deselected
    env.mouse.changed.emit(mouse_up())
    flush(env)
    assert [c for c in env.mouse.calls if c[0] == "led"] == []
    env.ctl.aura_sync_set(view(targets={"keyboard"}, brightness=5))
    flush(env)
    assert [c for c in env.mouse.calls if c[0] == "led"] == []


def test_aura_sync_off_applies_nothing(env):
    env.ctl.start()
    env.mouse.changed.emit(mouse_up())
    env.mouse.calls.clear()
    env.ctl.aura_sync_set(view(enabled=False))
    assert not env.ctl._aura_timer.isActive()
    env.ctl._aura_flush()
    assert env.mouse.calls == [] and env.asusd.calls.count(("color", (10, 20, 30))) == 0


def test_reapply_only_on_reconnect_transition(env):
    env.ctl.start()
    env.ctl.aura_sync_set(view())
    flush(env)
    env.mouse.changed.emit(mouse_up())                     # appears -> applied once
    env.headset.changed.emit(headset_up())
    assert env.mouse.calls.count(("led", 0, 70, (10, 20, 30), True)) == 1
    assert env.headset.calls.count(("light", 1, 70, (10, 20, 30))) == 1
    for _ in range(3):                                     # polling re-emits: no loop
        env.mouse.changed.emit(mouse_up())
        env.headset.changed.emit(headset_up())
    assert env.mouse.calls.count(("led", 0, 70, (10, 20, 30), True)) == 1
    assert env.headset.calls.count(("light", 1, 70, (10, 20, 30))) == 1
    env.headset.changed.emit(headset_up(connected=False))  # powered off, then on: re-applied
    env.headset.changed.emit(headset_up(connected=True))
    assert env.headset.calls.count(("light", 1, 70, (10, 20, 30))) == 2
    env.mouse.changed.emit(dataclasses.replace(mouse_up(), asleep=True))
    env.mouse.changed.emit(mouse_up())
    assert env.mouse.calls.count(("led", 0, 70, (10, 20, 30), True)) == 2


def test_aura_sync_persisted(env, tmp_path):
    env.ctl.aura_sync_set(view(effect="cycle", color=(255, 0, 128), brightness=33, targets={"mouse", "keyboard"}))
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.sync()
    from alaz.core.controller import Controller
    from alaz.core.state import AppState
    st2 = AppState()
    Controller(st2, env.asusd, env.gfx, env.sensors, env.display, settings, mux_path=str(env.mux), dbus_call=env.dbus)
    v = st2.aura_sync
    assert v == AuraSyncView(True, "cycle", (255, 0, 128), 33, {"mouse", "keyboard"})
    assert settings.value("aura_sync/color") == "#FF0080"


def test_aura_sync_set_sanitises(env):
    env.ctl.aura_sync_set(view(effect="bogus", brightness=500, color=(300, -4, 5), targets={"mouse", "toaster"}))
    v = env.state.aura_sync
    assert (v.effect, v.brightness, v.color, v.targets) == ("static", 100, (255, 0, 5), {"mouse"})


def test_direct_lighting_clears_dedupe(env):
    env.ctl.start()
    env.mouse.changed.emit(mouse_up())
    env.ctl.aura_sync_set(view())
    flush(env)
    env.ctl.mouse_set_led(4, 20, (9, 9, 9))
    env.mouse.calls.clear()
    env.ctl.aura_sync_set(view(enabled=False))
    env.ctl.aura_sync_set(view())                          # re-enabled: full state goes out again
    flush(env)
    assert ("led", 0, 70, (10, 20, 30), True) in env.mouse.calls


def test_monitor_rules(env):
    env.ctl.start()
    env.ctl.monitor_set("brightness", 40)
    env.ctl.monitor_set("gamevisual", 2)
    env.ctl.monitor_set("hdr", 1)                          # read-only: refused
    env.ctl.monitor_set("input", 0x0F)                     # needs the confirm path: refused, nothing sent
    assert env.ddc.calls == [("debounced", "brightness", 40), ("set", "gamevisual", 2, False)]
    assert env.msgs and env.msgs[-1][0] == "error"
    env.ctl.monitor_set_input(0x1A)
    assert env.ddc.calls[-1] == ("set", "input", 0x1A, True)


def test_ddc_validate_rejects_unconfirmed_input():
    ddc = DdcClient(run=lambda argv, timeout: (0, "", ""))
    assert ddc.validate("input", 0x0F) is not None
    assert ddc.validate("input", 0x0F, confirmed=True) is None


def test_refresh_monitor_busy_cycle(env):
    env.ctl.start()
    env.ctl.refresh_monitor()
    assert ("monitor", True) in env.busy and env.ddc.calls == [("refresh",)]
    env.ddc.changed.emit(MonitorState(present=True))
    assert env.busy[-1] == ("monitor", False)
    env.ctl.refresh_monitor()
    env.ddc.error.emit("boom")
    assert env.busy[-1] == ("monitor", False) and env.msgs[-1][0] == "error"


def test_peripheral_messages_english(env):
    i18n.set_language("en")
    env.ctl.start()
    env.mouse.error.emit("x")
    env.headset.error.emit("y")
    env.ddc.error.emit("z")
    texts = [t for _l, t in env.msgs]
    assert texts == ["Mouse: x", "Headset: y", "Monitor: z"]


def test_mouse_writes_forwarded(env):
    env.ctl.start()
    env.ctl.mouse_set_dpi(1, 800)
    env.ctl.mouse_set_polling(500)
    env.ctl.mouse_set_led(0, 50, (1, 2, 3))
    assert ("dpi", 1, 800) in env.mouse.calls and ("polling", 500) in env.mouse.calls
    assert ("led", 0, 50, (1, 2, 3), True) in env.mouse.calls
    QApplication.processEvents()


def test_reconnect_skips_write_when_device_already_matches(env):
    # The mouse keeps its lighting in flash and sleeps every few minutes: a wake-up that already shows the
    # synced lighting must not be rewritten (flash wear); a device showing something else is rewritten.
    env.ctl.start()
    env.ctl.aura_sync_set(view())
    flush(env)
    synced = dict(led_mode=0, led_brightness=70, led_rgb=(10, 20, 30))
    env.mouse.changed.emit(mouse_up(**synced))
    env.mouse.changed.emit(dataclasses.replace(mouse_up(**synced), asleep=True))
    env.mouse.changed.emit(mouse_up(**synced))
    assert not [c for c in env.mouse.calls if c[0] == "led"]
    env.headset.changed.emit(headset_up(light_effect=1, light_brightness=50, light_rgb=(234, 178, 21)))
    assert env.headset.calls.count(("light", 1, 70, (10, 20, 30))) == 1
