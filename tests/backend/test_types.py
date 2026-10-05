from alaz.backend.types import Epp, FanCurve, GfxMode, GfxPower, Profile


def test_profile_values():
    assert (Profile.BALANCED, Profile.PERFORMANCE, Profile.QUIET) == (0, 1, 2)


def test_epp_values():
    assert [e.value for e in Epp] == [0, 1, 2, 3, 4]
    assert Epp.BALANCE_POWER == 3 and Epp.POWER == 4


def test_gfx_mode_values():
    assert GfxMode.HYBRID == 0 and GfxMode.INTEGRATED == 1
    assert GfxMode.ASUS_MUX_DGPU == 5 and GfxMode.NONE == 6


def test_gfx_power_values():
    assert GfxPower.ACTIVE == 0 and GfxPower.SUSPENDED == 1 and GfxPower.UNKNOWN == 5


def test_fan_curve_percent_matches_live_cpu_curve():
    c = FanCurve("CPU", (0, 59, 62, 65, 68, 71, 74, 76), (2, 25, 38, 51, 63, 81, 99, 117), False)
    assert c.percent() == (1, 10, 15, 20, 25, 32, 39, 46)


def test_fan_curve_percent_extremes_and_frozen():
    c = FanCurve("GPU", (20,) * 8, (0, 255) * 4, True)
    assert c.percent() == (0, 100) * 4
    try:
        c.fan = "X"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("FanCurve must be frozen")
