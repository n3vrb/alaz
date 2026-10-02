import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from rog_control.backend import sensors as S


def w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(text))


def make_pci(root, status=None, vendor="0x10de", cls="0x030000"):
    d = root / "0000:01:00.0"
    w(d / "vendor", vendor)
    w(d / "class", cls)
    if status:
        w(d / "power/runtime_status", status)
    # an unrelated Intel iGPU
    w(root / "0000:00:02.0" / "vendor", "0x8086")
    w(root / "0000:00:02.0" / "class", "0x030000")


class Smi:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def __call__(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("Driver/library version mismatch")
        return 55.0, 12.0, 20.5


def sampler(tmp_path, smi, clock=lambda: 0.0):
    return S.Sampler(str(tmp_path / "pci"), str(tmp_path / "hwmon"), str(tmp_path / "ps"), smi, clock)


def test_fan_mapping(tmp_path):
    hw = tmp_path / "hwmon"
    w(hw / "hwmon3/name", "asus")
    for i, (lab, v) in enumerate([("cpu_fan", 2300), ("gpu_fan", 2100), ("mid_fan", 3800)], 1):
        w(hw / f"hwmon3/fan{i}_label", lab)
        w(hw / f"hwmon3/fan{i}_input", v)
    w(hw / "hwmon4/name", "acpi_fan")
    w(hw / "hwmon4/fan1_input", 9999)
    assert S.read_fans(str(hw)) == {"cpu": 2300, "gpu": 2100, "mid": 3800}


def test_cpu_temp_package(tmp_path):
    hw = tmp_path / "hwmon/hwmon1"
    w(hw / "name", "coretemp")
    w(hw / "temp1_label", "Package id 0"); w(hw / "temp1_input", 61000)
    w(hw / "temp2_label", "Core 0"); w(hw / "temp2_input", 50000)
    assert S.read_cpu_temp(str(tmp_path / "hwmon")) == 61.0


def test_battery_watts(tmp_path):
    ps = tmp_path / "ps"
    w(ps / "BAT1/type", "Battery"); w(ps / "BAT1/capacity", 80); w(ps / "BAT1/status", "Discharging")
    w(ps / "BAT1/current_now", 1500000); w(ps / "BAT1/voltage_now", 12000000)
    w(ps / "ACAD/type", "Mains"); w(ps / "ACAD/online", 0)
    pct, st, ac, watts = S.read_power(str(ps))
    assert (pct, st, ac) == (80.0, "Discharging", False)
    assert watts == pytest.approx(18.0)


def test_power_missing(tmp_path):
    assert S.read_power(str(tmp_path / "none")) == (None, None, None, None)


def test_gpu_suspended_no_smi(tmp_path):
    make_pci(tmp_path / "pci", "suspended")
    smi = Smi()
    assert sampler(tmp_path, smi).gpu()[0] == "sleep"
    assert smi.calls == 0


def test_gpu_absent_no_smi(tmp_path):
    (tmp_path / "pci").mkdir()
    smi = Smi()
    assert sampler(tmp_path, smi).gpu() == ("off", None, None, None)
    assert smi.calls == 0


def test_gpu_active_uses_smi(tmp_path):
    make_pci(tmp_path / "pci", "active")
    smi = Smi()
    assert sampler(tmp_path, smi).gpu() == ("active", 55.0, 12.0, 20.5)
    assert smi.calls == 1


def test_smi_backoff(tmp_path):
    make_pci(tmp_path / "pci", "active")
    t = [0.0]
    smi = Smi(fail=True)
    s = sampler(tmp_path, smi, lambda: t[0])
    assert s.gpu() == ("active", None, None, None)
    s.gpu(); s.gpu()
    assert smi.calls == 1
    t[0] = 31.0
    s.gpu()
    assert smi.calls == 2


def test_full_sample_and_reader(tmp_path, qtbot=None):
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer
    app = QCoreApplication.instance() or QCoreApplication([])
    make_pci(tmp_path / "pci", "suspended")
    got = []
    r = S.SensorReader(sampler(tmp_path, Smi()))
    r.updated.connect(got.append)
    loop = QEventLoop()
    r.updated.connect(lambda _s: loop.quit())
    QTimer.singleShot(3000, loop.quit)
    r.start(1000)
    loop.exec()
    r.stop()
    assert got and got[0].gpu_state == "sleep"
