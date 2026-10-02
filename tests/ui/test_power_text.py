from rog_control.ui.power_text import PowerSmoother, power_line, power_text


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
