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


def test_eco_exit_refused(tree):
    (tree / "sys/devices/platform/asus-nb-wmi/dgpu_disable").write_text("1\n")
    conf(tree).write_text(ORIG.replace('"Hybrid"', '"Integrated"'))
    before = conf(tree).read_text()
    rc, _, err = run(tree, ["set-boot-mode", "hybrid"])
    assert rc == 3 and "Eco" in err
    assert conf(tree).read_text() == before
    assert not (tree / "etc/supergfxd.conf.rog-control.bak").exists()


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
    assert "subprocess" not in code and "os.system" not in code
