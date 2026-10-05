import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from alaz.backend import sensors as S


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


def sampler(tmp_path, smi, clock=lambda: 0.0, own_pid=None):
    return S.Sampler(str(tmp_path / "pci"), str(tmp_path / "hwmon"), str(tmp_path / "ps"), smi, clock,
                     str(tmp_path / "proc"), own_pid if own_pid is not None else 999999,
                     rapl_root=str(tmp_path / "rapl"))


def add_proc(tmp_path, pid, comm="game", target="/dev/nvidia0"):
    d = tmp_path / "proc" / str(pid)
    (d / "fd").mkdir(parents=True, exist_ok=True)
    w(d / "comm", comm)
    os.symlink(target, d / "fd" / "3")


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
    add_proc(tmp_path, 100)
    smi = Smi()
    assert sampler(tmp_path, smi).gpu() == ("active", 55.0, 12.0, 20.5)
    assert smi.calls == 1


def test_active_no_users_no_smi(tmp_path):
    make_pci(tmp_path / "pci", "active")
    (tmp_path / "proc").mkdir()
    add_proc(tmp_path, 101, target="/dev/null")
    smi = Smi()
    s = sampler(tmp_path, smi)
    assert s.gpu() == ("active", None, None, None)
    assert smi.calls == 0


def test_own_pid_and_persistenced_ignored(tmp_path):
    make_pci(tmp_path / "pci", "active")
    add_proc(tmp_path, 4242)  # own
    add_proc(tmp_path, 300, comm="nvidia-persiste")
    smi = Smi()
    s = sampler(tmp_path, smi, own_pid=4242)
    assert s.gpu() == ("active", None, None, None)
    assert smi.calls == 0


def test_unreadable_proc_skipped(tmp_path):
    make_pci(tmp_path / "pci", "active")
    w(tmp_path / "proc" / "55" / "comm", "x")  # no fd dir at all
    add_proc(tmp_path, 56)
    smi = Smi()
    assert sampler(tmp_path, smi).gpu()[1] == 55.0


def test_smi_rate_limited_with_users(tmp_path):
    make_pci(tmp_path / "pci", "active")
    add_proc(tmp_path, 100)
    t = [0.0]
    smi = Smi()
    s = sampler(tmp_path, smi, lambda: t[0])
    outs = []
    for i in range(10):
        t[0] = float(i)
        outs.append(s.gpu())
    assert smi.calls == 2  # t=0 and t=5 -> at most one per 5 s
    assert all(o == ("active", 55.0, 12.0, 20.5) for o in outs)


def test_users_scan_cached_5s(tmp_path):
    make_pci(tmp_path / "pci", "active")
    t = [0.0]
    smi = Smi()
    s = sampler(tmp_path, smi, lambda: t[0])
    assert s.gpu()[1] is None
    add_proc(tmp_path, 100)
    t[0] = 2.0
    assert s.gpu()[1] is None and smi.calls == 0  # cached "no users"
    t[0] = 5.0
    assert s.gpu()[1] == 55.0


def test_smi_backoff(tmp_path):
    make_pci(tmp_path / "pci", "active")
    add_proc(tmp_path, 100)
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


def test_compositor_holders_are_not_gpu_users(tmp_path):
    # gnome-shell/Xwayland keep /dev/nvidia0 open permanently (verified live while
    # the GPU stayed suspended); they must not trigger nvidia-smi polling.
    make_pci(tmp_path / "pci", "active")
    add_proc(tmp_path, 2722, comm="gnome-shell")
    add_proc(tmp_path, 3199, comm="Xwayland")
    smi = Smi()
    assert sampler(tmp_path, smi).gpu() == ("active", None, None, None)
    assert smi.calls == 0


# ---- RAPL psys -------------------------------------------------------------
def rapl_tree(tmp_path, energy="1000000", name="psys", idx=1, mode=None):
    d = tmp_path / "rapl" / f"intel-rapl:{idx}"
    d.mkdir(parents=True, exist_ok=True)
    (tmp_path / "rapl" / "intel-rapl:0").mkdir(exist_ok=True)
    w(tmp_path / "rapl" / "intel-rapl:0" / "name", "package-0")
    w(d / "name", name)
    w(d / "max_energy_range_uj", "1000000000")
    w(d / "energy_uj", energy)
    if mode is not None:
        os.chmod(d / "energy_uj", mode)
    return d


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_psys_delta_and_first_sample(tmp_path):
    d = rapl_tree(tmp_path, "1000000")
    clk = Clock()
    r = S.PsysReader(str(tmp_path / "rapl"), clk)
    assert r.read() is None and r.available is True      # first sample
    clk.t += 2.0
    w(d / "energy_uj", "31000000")                       # 30 J in 2 s
    assert r.read() == pytest.approx(15.0)


def test_psys_wrap(tmp_path):
    d = rapl_tree(tmp_path, "999000000")
    clk = Clock()
    r = S.PsysReader(str(tmp_path / "rapl"), clk)
    r.read()
    clk.t += 1.0
    w(d / "energy_uj", "29000000")                       # wrapped: 1e9-999e6+29e6 = 30e6 uJ
    assert r.read() == pytest.approx(30.0)


def test_psys_found_by_name_not_index(tmp_path):
    rapl_tree(tmp_path, idx=3)
    r = S.PsysReader(str(tmp_path / "rapl"), Clock())
    r.read()
    assert r.available is True


def test_psys_missing_domain(tmp_path):
    rapl_tree(tmp_path, name="dram")
    r = S.PsysReader(str(tmp_path / "rapl"), Clock())
    assert r.read() is None and r.available is False


def test_psys_permission_retry_every_60s(tmp_path, monkeypatch):
    d = rapl_tree(tmp_path, "1000000")
    clk = Clock()
    r = S.PsysReader(str(tmp_path / "rapl"), clk)
    real_open = open
    denied = {"on": True, "opens": 0}

    def fake_open(path, *a, **k):
        if str(path).endswith("energy_uj"):
            denied["opens"] += 1
            if denied["on"]:
                raise PermissionError(13, "denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    assert r.read() is None and r.available is False and denied["opens"] == 1
    clk.t += 30
    assert r.read() is None and denied["opens"] == 1      # no retry before 60 s
    clk.t += 31
    denied["on"] = False                                  # rule installed meanwhile
    assert r.read() is None and r.available is True       # opened again, first sample
    clk.t += 1
    w(d / "energy_uj", "11000000")
    assert r.read() == pytest.approx(10.0)


def test_sampler_exposes_psys(tmp_path):
    rapl_tree(tmp_path)
    s = sampler(tmp_path, Smi())
    snap = s.sample()
    assert snap.psys_available is True and snap.system_power_w is None
    snap = sampler(tmp_path / "nothing", Smi()).sample()
    assert snap.psys_available is False and snap.system_power_w is None
