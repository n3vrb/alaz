from rog_control.core.state import ACCENTS, AppState, AuraView, DisplayView, GfxView


def test_defaults():
    s = AppState()
    assert s.perf_mode == "balanced"
    assert s.accent == "#4C8DFF"
    assert s.gfx == GfxView()
    assert s.gfx.can_eco_exit is True
    assert s.display == DisplayView()
    assert s.battery_limit is None
    assert s.sensors is None
    assert s.aura == AuraView()


def test_accent_table():
    assert ACCENTS == {"quiet": "#34C08A", "balanced": "#4C8DFF",
                       "turbo": "#FF5A5F", "custom": "#F2A93B"}


def test_mode_and_accent_signals_emit_once():
    s = AppState()
    modes, accents = [], []
    s.perfModeChanged.connect(modes.append)
    s.accentChanged.connect(accents.append)
    s.set_perf_mode("turbo")
    s.set_perf_mode("turbo")
    assert modes == ["turbo"] and accents == ["#FF5A5F"]
    assert s.accent == "#FF5A5F"


def test_unchanged_values_do_not_emit():
    s = AppState()
    got = []
    s.gfxChanged.connect(got.append)
    s.displayChanged.connect(got.append)
    s.batteryLimitChanged.connect(got.append)
    s.set_gfx(GfxView())
    s.set_display(DisplayView())
    s.set_battery_limit(80)
    s.set_battery_limit(80)
    assert got == [80]


def test_platform_dict_and_signal():
    s = AppState()
    got = []
    s.platformChanged.connect(lambda n, v: got.append((n, v)))
    s.set_platform_value("PanelOd", True)
    assert s.platform == {"PanelOd": True} and got == [("PanelOd", True)]


def test_invalid_mode_rejected():
    import pytest
    with pytest.raises(ValueError):
        AppState().set_perf_mode("nope")
