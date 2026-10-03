import importlib.machinery
import importlib.util
import io
import json
import os
import stat
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "helper" / "rog-control-gfx-helper"
ORIG = """{
  "mode": "Hybrid",
  "vfio_enable": false,
  "vfio_save": false,
  "always_reboot": true,
  "no_logind": false,
  "logout_timeout_s": 180,
  "hotplug_type": "Asus"
}"""


def _load():
    loader = importlib.machinery.SourceFileLoader("gfx_helper", str(HELPER))
    spec = importlib.util.spec_from_loader("gfx_helper", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


H = _load()


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "etc").mkdir()
    sysd = tmp_path / "sys/devices/platform/asus-nb-wmi"
    sysd.mkdir(parents=True)
    (tmp_path / "etc/supergfxd.conf").write_text(ORIG)
    os.chmod(tmp_path / "etc/supergfxd.conf", 0o644)
    (sysd / "dgpu_disable").write_text("0\n")
    (sysd / "gpu_mux_mode").write_text("1\n")
    return tmp_path


def run(tree, args, fake_root=True, euid=1000, extra_env=None):
    env = {H.ENV_ROOT: str(tree)}
    if fake_root:
        env[H.ENV_FAKE] = "1"
    env.update(extra_env or {})
    out, err = io.StringIO(), io.StringIO()
    rc = H.main(args, environ=env, euid=euid, out=out, err=err)
    return rc, out.getvalue(), err.getvalue()


def conf(tree):
    return tree / "etc/supergfxd.conf"


def test_integrated_preserves_format(tree):
    rc, out, _ = run(tree, ["set-boot-mode", "integrated"])
    assert rc == 0
    assert json.loads(out) == {"ok": True, "boot_mode": "Integrated", "reboot_required": True}
    assert conf(tree).read_text() == ORIG.replace('"Hybrid"', '"Integrated"')
    data = json.loads(conf(tree).read_text())
    assert list(data) == list(json.loads(ORIG))
    assert stat.S_IMODE(os.stat(conf(tree)).st_mode) == 0o644


def test_backup_and_no_tmp_left(tree):
    run(tree, ["set-boot-mode", "integrated"])
    assert (tree / "etc/supergfxd.conf.rog-control.bak").read_text() == ORIG
    assert sorted(p.name for p in (tree / "etc").iterdir()) == [
        "supergfxd.conf", "supergfxd.conf.rog-control.bak"]


def test_atomic_replace_used(tree, monkeypatch):
    calls = []
    real = os.replace
    monkeypatch.setattr(H.os, "replace", lambda a, b: (calls.append((a, b)), real(a, b))[1])
    run(tree, ["set-boot-mode", "integrated"])
    assert str(conf(tree)) in [b for _, b in calls]
    assert all(os.path.dirname(a) == os.path.dirname(b) for a, b in calls)


def test_roundtrip_back_to_hybrid(tree):
    run(tree, ["set-boot-mode", "integrated"])
    rc, out, _ = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 0 and json.loads(out)["boot_mode"] == "Hybrid"
    assert conf(tree).read_text() == ORIG


def test_symlink_refused(tree):
    real = tree / "real.conf"
    real.write_text(ORIG)
    conf(tree).unlink()
    conf(tree).symlink_to(real)
    rc, _, err = run(tree, ["set-boot-mode", "integrated"])
    assert rc == 6 and "symlink" in err
    assert real.read_text() == ORIG and conf(tree).is_symlink()


def _eco_tree(tree, systemctl_rc=0):
    """Fake tree in Eco state with a fake systemctl that logs its argv."""
    sysd = tree / "sys/devices/platform/asus-nb-wmi"
    (sysd / "dgpu_disable").write_text("1\n")
    (tree / "sys/bus/pci").mkdir(parents=True)
    (tree / "sys/bus/pci/drivers_autoprobe").write_text("1\n")
    conf(tree).write_text(ORIG.replace('"Hybrid"', '"Integrated"'))
    (tree / "usr/bin").mkdir(parents=True)
    log = tree / "calls.log"
    sc = tree / "usr/bin/systemctl"
    sc.write_text('#!/bin/sh\necho "systemctl $*" >> "%s"\nexit %d\n' % (log, systemctl_rc))
    sc.chmod(0o755)
    return log


def _spy(monkeypatch, tree, log, fail_dgpu=False, noop_dgpu=False):
    real_w, real_a = H._write_sysfs, H._atomic_write

    def w(path, value):
        name = os.path.relpath(path, str(tree))
        with open(log, "a") as f:
            f.write("sysfs %s=%s\n" % (name, value))
        if path.endswith("dgpu_disable") and value == "0":
            if fail_dgpu:
                raise OSError(5, "boom")
            if noop_dgpu:
                return
        real_w(path, value)

    def a(path, text, *args):
        with open(log, "a") as f:
            f.write("config %s\n" % ("Hybrid" if '"Hybrid"' in text else "Integrated"))
        real_a(path, text, *args)

    monkeypatch.setattr(H, "_write_sysfs", w)
    monkeypatch.setattr(H, "_atomic_write", a)


DGPU = "sys/devices/platform/asus-nb-wmi/dgpu_disable"
PROBE = "sys/bus/pci/drivers_autoprobe"


def test_eco_exit_full_sequence(tree, monkeypatch):
    log = _eco_tree(tree)
    _spy(monkeypatch, tree, log)
    rc, out, err = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 0, err
    assert json.loads(out) == {"ok": True, "boot_mode": "Hybrid", "reboot_required": True, "eco_exit": True}
    lines = log.read_text().splitlines()
    # first config write is the backup (previous Integrated content), then the real config
    assert lines == ["config Integrated", "config Hybrid", "systemctl stop supergfxd.service",
                     "sysfs %s=0" % PROBE, "sysfs %s=0" % DGPU]
    assert conf(tree).read_text() == ORIG
    assert (tree / PROBE).read_text() == "0"
    assert (tree / DGPU).read_text() == "0"


def test_eco_exit_systemctl_failure_rolls_back(tree, monkeypatch):
    log = _eco_tree(tree, systemctl_rc=1)
    before = conf(tree).read_text()
    _spy(monkeypatch, tree, log)
    rc, _, err = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 7 and "supergfxd" in err
    assert conf(tree).read_text() == before
    assert (tree / PROBE).read_text() == "1\n" and (tree / DGPU).read_text() == "1\n"
    assert not any(l.startswith("sysfs") for l in log.read_text().splitlines())


def test_eco_exit_missing_systemctl_is_exit7(tree, monkeypatch):
    log = _eco_tree(tree)
    (tree / "usr/bin/systemctl").unlink()
    before = conf(tree).read_text()
    rc, _, _ = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 7 and conf(tree).read_text() == before


@pytest.mark.parametrize("mode", ["raise", "noop"])
def test_eco_exit_dgpu_failure_restores_autoprobe(tree, monkeypatch, mode):
    log = _eco_tree(tree)
    _spy(monkeypatch, tree, log, fail_dgpu=(mode == "raise"), noop_dgpu=(mode == "noop"))
    rc, _, err = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 8 and "Eco" in err
    assert (tree / PROBE).read_text() == "1"            # restored
    assert conf(tree).read_text() == ORIG               # config stays Hybrid
    assert log.read_text().splitlines()[-1] == "sysfs %s=1" % PROBE


def test_eco_exit_config_already_hybrid_still_runs(tree, monkeypatch):
    log = _eco_tree(tree)
    conf(tree).write_text(ORIG)                         # dual-boot leftover: config Hybrid, dGPU disabled
    _spy(monkeypatch, tree, log)
    rc, out, _ = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 0 and json.loads(out)["eco_exit"] is True
    assert "config" not in log.read_text()


def test_eco_exit_needs_root(tree):
    _eco_tree(tree)
    rc, _, _ = run(tree, ["set-boot-mode", "hybrid"], fake_root=False)
    assert rc == 5 and not (tree / "calls.log").exists()


def test_eco_exit_paths_rerooted_and_clean_env(tree):
    paths, _ = H.resolve_env({H.ENV_ROOT: str(tree)}, 1000)
    assert paths["systemctl"] == str(tree / "usr/bin/systemctl")
    assert paths["autoprobe"] == str(tree / PROBE)
    paths, _ = H.resolve_env({H.ENV_ROOT: str(tree)}, 0)
    assert paths["systemctl"] == "/usr/bin/systemctl" and paths["autoprobe"] == "/sys/bus/pci/drivers_autoprobe"


def test_systemctl_called_with_safe_args(monkeypatch):
    seen = {}

    class R:
        returncode = 0

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, kw=kw)
        return R()

    monkeypatch.setattr(H.subprocess, "run", fake_run)
    assert H._stop_supergfxd("/usr/bin/systemctl") is None
    assert seen["cmd"] == ["/usr/bin/systemctl", "stop", "supergfxd.service"]
    assert seen["kw"]["timeout"] == 30 and seen["kw"]["check"] is False
    assert not seen["kw"].get("shell") and seen["kw"]["env"] == H.CLEAN_ENV


def test_mux_refused(tree):
    (tree / "sys/devices/platform/asus-nb-wmi/gpu_mux_mode").write_text("0\n")
    rc, _, err = run(tree, ["set-boot-mode", "integrated"])
    assert rc == 4 and err
    assert conf(tree).read_text() == ORIG


def test_no_change(tree):
    rc, out, _ = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 0 and "no change" in out
    assert conf(tree).read_text() == ORIG
    assert not (tree / "etc/supergfxd.conf.rog-control.bak").exists()


@pytest.mark.parametrize("args", [
    [], ["bogus"], ["set-boot-mode"], ["set-boot-mode", "nvidia"],
    ["set-boot-mode", "hybrid", "x"], ["status", "x"], ["set-boot-mode", "Hybrid"],
])
def test_bad_args(tree, args):
    rc, _, err = run(tree, args)
    assert rc == 2 and "Usage" in err
    assert conf(tree).read_text() == ORIG


def test_non_root_refused(tree):
    rc, _, _ = run(tree, ["set-boot-mode", "integrated"], fake_root=False)
    assert rc == 5
    assert conf(tree).read_text() == ORIG


def test_env_ignored_when_euid_root(tree):
    paths, is_root = H.resolve_env({H.ENV_ROOT: str(tree), H.ENV_FAKE: "1"}, 0)
    assert is_root and paths["config"] == "/etc/supergfxd.conf"
    assert paths["dgpu_disable"].startswith("/sys/")
    paths, is_root = H.resolve_env({H.ENV_ROOT: str(tree)}, 1000)
    assert not is_root and paths["config"].startswith(str(tree))
    paths, is_root = H.resolve_env({H.ENV_FAKE: "1"}, 1000)
    assert not is_root and paths["config"] == "/etc/supergfxd.conf"


def test_status_readonly(tree):
    rc, out, _ = run(tree, ["status"], fake_root=False)
    assert rc == 0
    assert json.loads(out) == {"configured_mode": "Hybrid", "dgpu_disable": 0, "gpu_mux_mode": 1}
    assert conf(tree).read_text() == ORIG
    assert not (tree / "etc/supergfxd.conf.rog-control.bak").exists()


def test_invalid_json(tree):
    conf(tree).write_text("{nope")
    rc, _, _ = run(tree, ["set-boot-mode", "integrated"])
    assert rc == 6
    assert conf(tree).read_text() == "{nope"


def test_no_forbidden_calls():
    src = HELPER.read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "os.system" not in code and "shell=True" not in code and "Popen" not in code
    assert code.count("subprocess.run(") == 1          # only the supergfxd stop
    assert src.startswith("#!/usr/bin/python3 -I\n")
