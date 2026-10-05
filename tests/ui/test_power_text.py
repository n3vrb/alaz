from alaz.ui.power_text import PowerSmoother, power_line, power_text


def test_texts():
    assert power_text(26.4, "Discharging") == "Sistem 26 W"
    assert power_text(65.2, "Charging") == "Şarj +65 W"
    assert power_text(3.0, "Full") is None
    assert power_text(3.0, "Not charging") is None
    assert power_text(None, "Discharging") is None
    assert power_text(10.0, None) is None


def test_line():
    assert power_line(26.4, "Discharging", False) == "Pilde · Sistem 26 W"
    assert power_line(65.2, "Charging", True) == "Prizde · Şarj +65 W"
    assert power_line(0.0, "Full", True) == "Prizde"
    assert power_line(None, None, None) == ""


def test_smoother_average_and_reset():
    s = PowerSmoother(3)
    assert s.push(10, "Discharging") == 10
    assert s.push(20, "Discharging") == 15
    s.push(30, "Discharging")
    assert s.push(40, "Discharging") == 30  # window of 3: 20,30,40
    assert s.push(65, "Charging") == 65     # reset on status change
    assert s.push(None, "Charging") is None


import pytest  # noqa: E402

from alaz.ui.power_text import PowerView, compose_power  # noqa: E402


@pytest.mark.parametrize("psys,status,bat,expect", [
    (31.0, "Not charging", 0.0, "Sistem 31 W"),
    (48.0, "Charging", 40.0, "Sistem 48 W · Şarj +40 W"),
    (20.0, "Full", 0.0, "Sistem 20 W"),
    (26.0, "Discharging", 25.0, "Sistem 25 W"),   # on battery the battery value wins
    (None, "Discharging", 26.4, "Sistem 26 W"),
    (None, "Charging", 65.2, "Şarj +65 W"),
    (None, "Full", 0.0, None),
    (None, "Not charging", 0.0, None),
])
def test_power_matrix(psys, status, bat, expect):
    sys_w, chg_w = PowerView(5).push(psys, bat, status)
    assert compose_power(sys_w, chg_w) == expect


def test_power_view_charge_is_moving_average_and_ac_converges():
    v = PowerView(5)
    for x in (10, 20, 30):
        sys_w, chg_w = v.push(x, x / 2, "Charging")
    assert chg_w == 10                      # 5-sample moving average of 5, 10, 15
    for _ in range(60):
        sys_w, _ = v.push(30, 15, "Charging")
    assert abs(sys_w - 30) < 0.5            # AC/psys EMA converges


# Real per-second psys samples measured on battery on the reference laptop (2026-10-05),
# with the battery's own reading at the same time (std 1.0 W).
_PSYS = [18, 21, 19, 23, 22, 25, 27, 27, 26, 37, 29, 23, 19, 22, 18, 18, 16, 16, 16, 16,
         18, 24, 22, 19, 26, 21, 23, 34, 35, 36]
_BAT = [21, 22, 21, 21, 21, 21, 21, 21, 22, 22, 22, 23, 23, 23, 23, 22, 22, 22, 21, 21,
        21, 20, 20, 20, 20, 20, 21, 21, 22, 23]


def _spread(xs):
    return max(xs) - min(xs)


def test_on_battery_shows_the_steady_battery_value():
    v = PowerView(5)
    shown = [v.push(p, b, "Discharging")[0] for p, b in zip(_PSYS, _BAT)]
    assert _spread(shown[5:]) <= 3          # was ~14 W with psys + 5-sample average


def test_on_ac_psys_is_strongly_smoothed():
    v = PowerView(5)
    shown = [v.push(p, 0.0, "Not charging")[0] for p in _PSYS]
    five = [sum(_PSYS[max(0, i - 4):i + 1]) / len(_PSYS[max(0, i - 4):i + 1]) for i in range(len(_PSYS))]
    assert _spread(shown[10:]) < _spread(five[10:]) / 2


def test_source_switch_resets_ac_average():
    v = PowerView(5)
    for _ in range(30):
        v.push(60.0, 0.0, "Not charging")
    sys_w, _ = v.push(20.0, 21.0, "Discharging")   # unplugged: battery value immediately
    assert sys_w == 21.0
    sys_w, _ = v.push(15.0, 0.0, "Not charging")   # plugged back: fresh average, not 60-ish
    assert sys_w == 15.0
