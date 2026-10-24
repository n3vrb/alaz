"""install.sh / uninstall.sh environment.d handling, run only against a fake HOME (--prefix)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINE = "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json\n"


def _run(script, prefix, *args, force=True):
    env = dict(os.environ, ALAZ_NO_SYSTEMCTL="1")
    env.pop("XDG_CONFIG_HOME", None)
    env.pop("XDG_DATA_HOME", None)
    if force:
        env["ALAZ_EGL_JSON_FORCE"] = "1"
    return subprocess.run(["sh", str(ROOT / script), "--prefix", str(prefix), *args],
                          capture_output=True, text=True, env=env, timeout=120)


@pytest.fixture
def prefix(tmp_path):
    return tmp_path / "home"


def _conf(prefix):
    return prefix / ".config/environment.d/90-alaz-egl-mesa.conf"


def test_install_creates_conf_idempotent_and_uninstall_removes(prefix):
    r = _run("install.sh", prefix)
    if r.returncode != 0 and "Missing Python dependencies" in r.stderr:
        pytest.skip("PyQt6/psutil not importable by system python3")
    assert r.returncode == 0, r.stderr
    assert _conf(prefix).read_text() == LINE
    assert "oturumu kapatıp" in r.stdout
    r = _run("install.sh", prefix)
    assert r.returncode == 0 and _conf(prefix).read_text() == LINE
    assert "log out" not in r.stdout
    r = _run("uninstall.sh", prefix)
    assert r.returncode == 0, r.stderr
    assert not _conf(prefix).exists()


def test_modified_conf_is_kept_with_warning(prefix):
    _conf(prefix).parent.mkdir(parents=True)
    _conf(prefix).write_text("MINE=1\n")
    r = _run("install.sh", prefix)
    if r.returncode != 0 and "Missing Python dependencies" in r.stderr:
        pytest.skip("PyQt6/psutil not importable by system python3")
    assert r.returncode == 0, r.stderr
    assert _conf(prefix).read_text() == "MINE=1\n"
    assert "warning" in r.stderr
    _run("uninstall.sh", prefix)
    assert _conf(prefix).read_text() == "MINE=1\n"
