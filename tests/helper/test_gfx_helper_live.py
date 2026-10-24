"""Tests for live-eco / live-hybrid / holders / status (docs/LIVE_GPU_CONTRACT.md).

Everything runs against a fake root (ALAZ_HELPER_TESTROOT); subprocesses (_run), sleeping
and the sysfs writer are faked: nothing here touches the real system.
"""
import io
import json
import os
import shutil

import pytest

from tests.helper.test_gfx_helper import H, ORIG, conf, run, tree  # noqa: F401  (H = loaded helper module)

RULE = "etc/udev/rules.d/61-alaz-mutter-ignore-nvidia.rules"
MASK = "run/udev/rules.d/71-nvidia.rules"
BL = "run/modprobe.d/alaz-live-nvidia.conf"
PCI = "sys/bus/pci/devices"
GPU, AUDIO = "0000:01:00.0", "0000:01:00.1"
INTEGRATED = ORIG.replace('"Hybrid"', '"Integrated"')
ALL_MODS = ("nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm")


class World:
    def __init__(self, tree, monkeypatch):
        self.t = tree
        self.ev = []                 # ordered event log
        self.fail = set()            # keys that return rc 1 (see key())
        self.persistenced_active = True
        self.appear_on_rescan = False
        self.mask_seen = []          # (key, mask exists, blacklist exists) at each subprocess
        self.dgpu_disable_stuck = False
        self.remove_raises = False
        self.hold_after_stop = None  # holders appear after persistenced stop
        self.mp = monkeypatch
        monkeypatch.setattr(H, "_run", self.fake_run)
        monkeypatch.setattr(H, "_sleep", lambda s: self.ev.append("sleep"))
        self.real_w = H._write_sysfs
        monkeypatch.setattr(H, "_write_sysfs", self.fake_w)
        (tree / "etc/udev/rules.d").mkdir(parents=True)
        (tree / RULE).write_text('... TAG+="mutter-device-ignore"\n')
        for exe in ("usr/sbin/modprobe", "usr/bin/udevadm", "usr/bin/systemctl"):
            (tree / exe).parent.mkdir(parents=True, exist_ok=True)
            (tree / exe).write_text("")
        (tree / "sys/bus/pci").mkdir(parents=True, exist_ok=True)
        (tree / "sys/bus/pci/drivers_autoprobe").write_text("1\n")
        (tree / "proc").mkdir(exist_ok=True)
        (tree / "sys/class/drm").mkdir(parents=True, exist_ok=True)
        (tree / "sys/module").mkdir(exist_ok=True)

    # ---- state builders
    def dgpu(self, driver=True, drm=True):
        for addr, cls in ((GPU, "0x030200"), (AUDIO, "0x040300")):
            d = self.t / PCI / addr
            d.mkdir(parents=True, exist_ok=True)
            (d / "vendor").write_text("0x10de\n")
            (d / "class").write_text(cls + "\n")
        (self.t / PCI / "0000:00:02.0").mkdir(parents=True, exist_ok=True)
        (self.t / PCI / "0000:00:02.0/vendor").write_text("0x8086\n")
        (self.t / PCI / "0000:00:02.0/class").write_text("0x030000\n")
        if driver:
            self.bind()
        if drm:
            self.make_drm()

    def bind(self):
        link = self.t / PCI / GPU / "driver"
        if not link.is_symlink():
            os.symlink("../../drivers/nvidia", link)

    def make_drm(self):
        (self.t / PCI / GPU / "drm/card1").mkdir(parents=True, exist_ok=True)
        (self.t / "sys/class/drm/card1/device").mkdir(parents=True, exist_ok=True)
        (self.t / "sys/class/drm/renderD129/device").mkdir(parents=True, exist_ok=True)
        for n in ("card1", "renderD129"):
            link = self.t / "sys/class/drm" / n / "device/driver"
            if not link.is_symlink():
                os.symlink("../../drivers/nvidia", link)
        # an iGPU card and a connector entry must be ignored
        (self.t / "sys/class/drm/card0/device").mkdir(parents=True, exist_ok=True)
        if not (self.t / "sys/class/drm/card0/device/driver").is_symlink():
            os.symlink("../../drivers/i915", self.t / "sys/class/drm/card0/device/driver")
        (self.t / "sys/class/drm/card1-eDP-1").mkdir(exist_ok=True)

    def modules(self, names=ALL_MODS):
        for m in names:
            (self.t / "sys/module" / m).mkdir(exist_ok=True)

    def hybrid(self):
        (self.t / "sys/devices/platform/asus-nb-wmi/dgpu_disable").write_text("0\n")
        self.dgpu()
        self.modules()
        conf(self.t).write_text(ORIG)

    def eco(self):
        (self.t / "sys/devices/platform/asus-nb-wmi/dgpu_disable").write_text("1\n")
        conf(self.t).write_text(INTEGRATED)

    def proc(self, pid, comm, *links, uid=None):
        d = self.t / "proc" / str(pid)
        (d / "fd").mkdir(parents=True)
        (d / "comm").write_text(comm + "\n")
        os.symlink("/usr/bin/" + comm, d / "exe")
        for i, target in enumerate(links):
            os.symlink(target, d / "fd" / str(i))

    # ---- fakes
    def key(self, cmd):
        name = os.path.basename(cmd[0])
        return name + " " + " ".join(cmd[1:])

    def fake_run(self, cmd, timeout):
        assert isinstance(cmd, list) and cmd[0].startswith(str(self.t)), cmd   # re-rooted, absolute
        assert timeout and timeout > 0
        k = self.key(cmd)
        self.ev.append(k)
        self.mask_seen.append((k, os.path.islink(self.t / MASK), os.path.exists(self.t / BL)))
        if k in self.fail:
            return 1
        if k == "systemctl is-active --quiet nvidia-persistenced.service":
            return 0 if self.persistenced_active else 3
        if k == "systemctl stop nvidia-persistenced.service" and self.hold_after_stop:
            self.proc(*self.hold_after_stop[0], *self.hold_after_stop[1])
        if os.path.basename(cmd[0]) == "modprobe":
            if cmd[1] == "-r":
                shutil.rmtree(self.t / "sys/module" / cmd[2], ignore_errors=True)
            else:
                m = cmd[1]
                (self.t / "sys/module" / m).mkdir(exist_ok=True)
                if m == "nvidia" and (self.t / PCI / GPU).exists():
                    self.bind()
                if m == "nvidia_drm" and (self.t / PCI / GPU).exists():
                    self.make_drm()
        return 0

    def fake_w(self, path, value):
        rel = os.path.relpath(path, str(self.t))
        self.ev.append("w %s=%s" % (rel, value))
        if path.endswith("/remove"):
            if self.remove_raises:
                raise OSError(5, "boom")
            shutil.rmtree(os.path.dirname(path))
            return
        if path.endswith("dgpu_disable"):
            if self.dgpu_disable_stuck:
                return
            self.real_w(path, value)
            if value == "0" and not self.appear_on_rescan:
                self.dgpu(driver=False, drm=False)
            return
        if path.endswith("pci/rescan"):
            if self.appear_on_rescan:
                self.dgpu(driver=False, drm=False)
            return
        if path.endswith("drivers_probe"):
            if value == AUDIO:
                os.symlink("../../drivers/snd_hda_intel", self.t / PCI / AUDIO / "driver")
            return
        self.real_w(path, value)

    # ---- helpers
    def go(self, cmd, fake_root=True):
        return run(self.t, [cmd], fake_root=fake_root)

    def dgpu_disable(self):
        return int((self.t / "sys/devices/platform/asus-nb-wmi/dgpu_disable").read_text())

    def clean(self):
        assert not os.path.lexists(self.t / MASK)
        assert not os.path.lexists(self.t / BL)

    def reloads(self):
        return self.ev.count("udevadm control --reload")


@pytest.fixture
def w(tree, monkeypatch):
    return World(tree, monkeypatch)


def last_json(out):
    return json.loads(out.strip().splitlines()[-1])


# ------------------------------------------------------------------ live-eco

def test_live_eco_success_sequence(w):
    w.hybrid()
    rc, out, err = w.go("live-eco")
    assert rc == 0, err
    assert last_json(out) == {"ok": True, "mode": "Integrated", "changed": True}
    assert conf(w.t).read_text() == INTEGRATED
    assert w.dgpu_disable() == 1
    assert not (w.t / PCI / GPU).exists() and not (w.t / PCI / AUDIO).exists()
    # exact order of the proven reference procedure
    ev = [e for e in w.ev if e != "udevadm control --reload"]
    assert ev == [
        "systemctl stop supergfxd.service",
        "systemctl is-active --quiet nvidia-persistenced.service",
        "systemctl stop nvidia-persistenced.service",
        "modprobe -r nvidia_drm", "modprobe -r nvidia_modeset",
        "modprobe -r nvidia_uvm", "modprobe -r nvidia",
        "w %s/%s/remove=1" % (PCI, AUDIO), "w %s/%s/remove=1" % (PCI, GPU),
        "w sys/devices/platform/asus-nb-wmi/dgpu_disable=1",
        "systemctl reset-failed supergfxd.service", "systemctl start supergfxd.service",
    ]
    # mask + blacklist were active during every hardware step, and are gone after
    for k, mask, bl in w.mask_seen:
        if k.startswith(("modprobe", "systemctl stop")) and k != "systemctl stop supergfxd.service":
            assert mask and bl, k
    assert w.ev[0] == "udevadm control --reload"        # reload after creating the mask
    assert w.reloads() == 2                              # and after removing it
    assert w.ev.index("udevadm control --reload", 1) < w.ev.index("systemctl reset-failed supergfxd.service")
    w.clean()
    assert (w.t / "etc/supergfxd.conf.alaz.bak").read_text() == ORIG


def test_live_eco_mask_is_symlink_to_devnull_and_blacklist_text(w):
    w.hybrid()
    seen = {}
    orig = w.fake_run

    def spy(cmd, timeout):
        if w.key(cmd) == "modprobe -r nvidia_drm":
            seen["link"] = os.readlink(w.t / MASK)
            seen["bl"] = (w.t / BL).read_text()
            seen["mode"] = oct(os.stat(w.t / BL).st_mode & 0o777)
        return orig(cmd, timeout)
    w.mp.setattr(H, '_run', spy)
    assert w.go("live-eco")[0] == 0
    assert seen["link"] == "/dev/null"
    assert seen["bl"] == ("blacklist nvidia\nblacklist nvidia_drm\n"
                          "blacklist nvidia_modeset\nblacklist nvidia_uvm\n")
    assert seen["mode"] == "0o644"


def test_live_eco_persistenced_not_active_is_not_touched(w):
    w.hybrid()
    w.persistenced_active = False
    assert w.go("live-eco")[0] == 0
    assert "systemctl stop nvidia-persistenced.service" not in w.ev


def test_live_eco_already_eco(w):
    w.eco()
    rc, out, _ = w.go("live-eco")
    assert rc == 0 and last_json(out) == {"ok": True, "mode": "Integrated", "changed": False}
    assert w.ev == []


def test_live_eco_needs_root(w):
    w.hybrid()
    rc, out, _ = w.go("live-eco", fake_root=False)
    assert rc == 5 and w.ev == [] and conf(w.t).read_text() == ORIG


def test_live_eco_mux_direct(w):
    w.hybrid()
    (w.t / "sys/devices/platform/asus-nb-wmi/gpu_mux_mode").write_text("0\n")
    rc, out, _ = w.go("live-eco")
    assert rc == 4 and last_json(out) == {"ok": False, "error": "mux"}
    assert w.ev == [] and conf(w.t).read_text() == ORIG


@pytest.mark.parametrize("what", ["rule", "rule_no_tag"])
def test_live_eco_precondition_rule_missing(w, what):
    w.hybrid()
    if what == "rule":
        (w.t / RULE).unlink()
    else:
        (w.t / RULE).write_text("# empty\n")
    rc, out, _ = w.go("live-eco")
    assert rc == 11
    j = last_json(out)
    assert j["error"] == "precondition" and j["missing"] == ["/" + RULE]
    assert w.ev == [] and conf(w.t).read_text() == ORIG
    w.clean()


def test_live_eco_precondition_mux_unreadable_and_no_modprobe(w):
    w.hybrid()
    (w.t / "sys/devices/platform/asus-nb-wmi/gpu_mux_mode").unlink()
    (w.t / "usr/sbin/modprobe").unlink()
    rc, out, _ = w.go("live-eco")
    assert rc == 11 and last_json(out)["missing"] == ["gpu_mux_mode", "modprobe"]


def test_live_eco_busy_initial_changes_nothing(w):
    w.hybrid()
    w.proc(4242, "firefox", "/dev/nvidia0", "/dev/nvidiactl", "/dev/dri/renderD129", "/dev/null")
    rc, out, _ = w.go("live-eco")
    assert rc == 9
    j = last_json(out)
    assert j["ok"] is False and j["error"] == "busy"
    assert j["holders"][0]["pid"] == 4242 and j["holders"][0]["comm"] == "firefox"
    assert w.ev == []                       # nothing run, no mask ever created
    assert conf(w.t).read_text() == ORIG and w.dgpu_disable() == 0
    w.clean()


def test_live_eco_busy_after_services_stopped_restores(w):
    w.hybrid()
    w.hold_after_stop = ((777, "late-app", "/dev/nvidia-uvm"), {})
    rc, out, _ = w.go("live-eco")
    assert rc == 9 and last_json(out)["holders"][0]["comm"] == "late-app"
    assert conf(w.t).read_text() == ORIG and w.dgpu_disable() == 0
    assert not any(e.startswith("modprobe") for e in w.ev)
    assert w.ev.index("systemctl start nvidia-persistenced.service") < w.ev.index("systemctl start supergfxd.service")
    assert (w.t / PCI / GPU).exists()
    w.clean()
    assert w.reloads() == 2


def test_live_eco_supergfxd_stop_fails(w):
    w.hybrid()
    w.fail.add("systemctl stop supergfxd.service")
    rc, out, _ = w.go("live-eco")
    assert rc == 7 and last_json(out) == {"ok": False, "error": "supergfxd"}
    assert conf(w.t).read_text() == ORIG and w.dgpu_disable() == 0
    assert not any(e.startswith("modprobe") for e in w.ev)
    w.clean()


@pytest.mark.parametrize("bad", ["nvidia_modeset", "nvidia_uvm", "nvidia", "nvidia_drm"])
def test_live_eco_modprobe_r_failure_rolls_back(w, bad):
    w.hybrid()
    w.fail.add("modprobe -r " + bad)
    rc, out, _ = w.go("live-eco")
    assert rc == 12
    assert last_json(out) == {"ok": False, "error": "aborted", "step": "modprobe-r:" + bad}
    assert conf(w.t).read_text() == ORIG and w.dgpu_disable() == 0
    assert (w.t / PCI / GPU).exists() and (w.t / PCI / AUDIO).exists()
    # modules already removed were loaded back, in forward (load) order
    removed = [m for m in ("nvidia_drm", "nvidia_modeset", "nvidia_uvm", "nvidia")[
        :("nvidia_drm", "nvidia_modeset", "nvidia_uvm", "nvidia").index(bad)]]
    loads = [e.split()[1] for e in w.ev if e.startswith("modprobe ") and not e.startswith("modprobe -r")]
    assert loads == [m for m in ALL_MODS if m in removed]
    for m in ALL_MODS:
        assert (w.t / "sys/module" / m).exists() or m == bad  # bad never got removed
    assert "systemctl start nvidia-persistenced.service" in w.ev
    assert "systemctl start supergfxd.service" in w.ev
    assert not any(e.endswith("remove=1") for e in w.ev)
    w.clean()
    assert w.reloads() == 2


def test_live_eco_modprobe_reload_failure_reported(w):
    w.hybrid()
    w.fail.update({"modprobe -r nvidia", "modprobe nvidia_drm"})
    rc, out, _ = w.go("live-eco")
    assert rc == 12 and last_json(out)["reload_failed"] == ["nvidia_drm"]
    w.clean()


def test_live_eco_skips_modules_not_loaded(w):
    w.hybrid()
    shutil.rmtree(w.t / "sys/module/nvidia_uvm")
    assert w.go("live-eco")[0] == 0
    assert "modprobe -r nvidia_uvm" not in w.ev


def test_live_eco_config_write_failure_aborts_with_rollback(w, monkeypatch):
    w.hybrid()
    monkeypatch.setattr(H, "_atomic_write", lambda *a: (_ for _ in ()).throw(OSError(30, "ro fs")))
    rc, out, _ = w.go("live-eco")
    assert rc == 12 and last_json(out)["step"] == "config"
    assert "modprobe nvidia" in w.ev                 # modules back
    assert "systemctl start supergfxd.service" in w.ev
    assert (w.t / PCI / GPU).exists() and w.dgpu_disable() == 0
    w.clean()


def test_live_eco_failure_after_config_is_exit10(w):
    w.hybrid()
    w.remove_raises = True
    rc, out, _ = w.go("live-eco")
    assert rc == 10
    assert last_json(out) == {"ok": False, "error": "failed", "step": "pci-remove", "reboot_required": True}
    assert conf(w.t).read_text() == INTEGRATED
    assert "systemctl start supergfxd.service" not in w.ev   # no restart on a half-done state
    w.clean()
    assert w.reloads() == 2


def test_live_eco_dgpu_disable_not_verified(w):
    w.hybrid()
    w.dgpu_disable_stuck = True
    rc, out, _ = w.go("live-eco")
    assert rc == 10 and last_json(out)["step"] == "dgpu_disable"
    assert last_json(out)["reboot_required"] is True
    assert conf(w.t).read_text() == INTEGRATED
    w.clean()


def test_live_eco_stale_mask_symlink_replaced_regular_file_refused(w):
    w.hybrid()
    (w.t / "run/udev/rules.d").mkdir(parents=True)
    os.symlink("/dev/null", w.t / MASK)                 # leftover of a crashed run
    assert w.go("live-eco")[0] == 0
    w.clean()
    w.hybrid()
    (w.t / "sys/devices/platform/asus-nb-wmi/dgpu_disable").write_text("0\n")
    w.ev.clear()
    (w.t / MASK).write_text("# somebody's real rule\n")
    rc, out, _ = w.go("live-eco")
    assert rc == 12 and last_json(out)["step"] == "mask"
    assert (w.t / MASK).read_text() == "# somebody's real rule\n"   # untouched
    assert not any(e.startswith(("modprobe", "systemctl")) for e in w.ev)
    assert conf(w.t).read_text() == ORIG


def test_live_eco_mask_symlink_elsewhere_refused(w):
    w.hybrid()
    (w.t / "run/udev/rules.d").mkdir(parents=True)
    os.symlink("/etc/passwd", w.t / MASK)
    rc, out, _ = w.go("live-eco")
    assert rc == 12 and os.readlink(w.t / MASK) == "/etc/passwd"


def test_live_eco_interrupt_before_commit_rolls_back(w):
    w.hybrid()
    orig = w.fake_run

    def boom(cmd, timeout):
        if w.key(cmd) == "modprobe -r nvidia_modeset":
            raise H._Interrupted()
        return orig(cmd, timeout)
    w.mp.setattr(H, '_run', boom)
    rc, out, _ = w.go("live-eco")
    assert rc == 12 and conf(w.t).read_text() == ORIG
    assert "modprobe nvidia_drm" in w.ev
    w.clean()


# ---------------------------------------------------------------- live-hybrid

def test_live_hybrid_success_sequence(w):
    w.eco()
    rc, out, err = w.go("live-hybrid")
    assert rc == 0, err
    assert last_json(out) == {"ok": True, "mode": "Hybrid", "changed": True}
    assert conf(w.t).read_text() == ORIG and w.dgpu_disable() == 0
    assert (w.t / "sys/bus/pci/drivers_autoprobe").read_text() == "1"
    ev = [e for e in w.ev if e not in ("udevadm control --reload", "sleep")]
    assert ev == [
        "systemctl stop supergfxd.service",
        "w sys/bus/pci/drivers_autoprobe=0",
        "w sys/devices/platform/asus-nb-wmi/dgpu_disable=0",
        "udevadm settle --timeout=30",
        "w sys/bus/pci/drivers_autoprobe=1",
        "modprobe nvidia", "udevadm settle --timeout=30",
        "modprobe nvidia_modeset", "udevadm settle --timeout=30",
        "modprobe nvidia_drm", "udevadm settle --timeout=30",
        "modprobe nvidia_uvm", "udevadm settle --timeout=30",
        "w sys/bus/pci/drivers_probe=" + AUDIO,
        "systemctl reset-failed nvidia-persistenced.service",
        "systemctl start nvidia-persistenced.service",
        "systemctl reset-failed supergfxd.service", "systemctl start supergfxd.service",
    ]
    for k, mask, bl in w.mask_seen:
        if k.startswith("modprobe"):
            assert mask and bl
    assert w.reloads() == 2
    w.clean()
    assert os.path.basename(os.readlink(w.t / PCI / GPU / "driver")) == "nvidia"


def test_live_hybrid_waits_with_rescan(w):
    w.eco()
    w.appear_on_rescan = True
    rc, out, _ = w.go("live-hybrid")
    assert rc == 0
    assert w.ev.count("sleep") == 6                    # 0..5 polls, rescan at i == 5
    assert "w sys/bus/pci/rescan=1" in w.ev
    w.clean()


def test_live_hybrid_gpu_never_appears(w):
    w.eco()
    w.appear_on_rescan = True
    orig = w.fake_w
    w.mp.setattr(H, '_write_sysfs', lambda p, v: None if p.endswith("pci/rescan") else orig(p, v))
    rc, out, _ = w.go("live-hybrid")
    assert rc == 10 and last_json(out) == {"ok": False, "error": "failed", "step": "pci-wait", "reboot_required": True}
    assert w.ev.count("sleep") == 15
    assert conf(w.t).read_text() == ORIG           # boot config already Hybrid
    assert not any(e.startswith("modprobe") for e in w.ev)
    w.clean()


@pytest.mark.parametrize("bad,step", [("modprobe nvidia", "modprobe:nvidia"),
                                      ("modprobe nvidia_drm", "modprobe:nvidia_drm"),
                                      ("modprobe nvidia_uvm", "modprobe:nvidia_uvm")])
def test_live_hybrid_modprobe_failure(w, bad, step):
    w.eco()
    w.fail.add(bad)
    rc, out, _ = w.go("live-hybrid")
    assert rc == 10 and last_json(out) == {"ok": False, "error": "failed", "step": step,
                                           "reboot_required": True}
    assert conf(w.t).read_text() == ORIG
    assert "systemctl start supergfxd.service" not in w.ev
    w.clean()
    assert w.reloads() == 2


def test_live_hybrid_module_vanishes(w, monkeypatch):
    w.eco()
    orig = w.fake_run

    def run2(cmd, timeout):
        rc = orig(cmd, timeout)
        if w.key(cmd) == "udevadm settle --timeout=30" and "modprobe nvidia_modeset" in w.ev:
            shutil.rmtree(w.t / "sys/module/nvidia_modeset", ignore_errors=True)
        return rc
    w.mp.setattr(H, '_run', run2)
    rc, out, _ = w.go("live-hybrid")
    assert rc == 10 and last_json(out)["step"] == "module-vanished:nvidia_modeset"
    w.clean()


def test_live_hybrid_driver_not_bound(w):
    w.eco()
    orig = w.fake_run

    def run2(cmd, timeout):
        rc = orig(cmd, timeout)
        link = w.t / PCI / GPU / "driver"
        if link.is_symlink():
            link.unlink()
        return rc
    w.mp.setattr(H, '_run', run2)
    rc, out, _ = w.go("live-hybrid")
    assert rc == 10 and last_json(out)["step"] == "driver-bind"
    w.clean()


def test_live_hybrid_no_drm_card(w):
    w.eco()
    orig = w.fake_run

    def run2(cmd, timeout):
        rc = orig(cmd, timeout)
        shutil.rmtree(w.t / PCI / GPU / "drm", ignore_errors=True)
        return rc
    w.mp.setattr(H, '_run', run2)
    rc, out, _ = w.go("live-hybrid")
    assert rc == 10 and last_json(out)["step"] == "drm-card"
    w.clean()


def test_live_hybrid_supergfxd_stop_fails_rolls_config_back(w):
    w.eco()
    w.fail.add("systemctl stop supergfxd.service")
    rc, out, _ = w.go("live-hybrid")
    assert rc == 7 and last_json(out) == {"ok": False, "error": "supergfxd"}
    assert conf(w.t).read_text() == INTEGRATED and w.dgpu_disable() == 1
    w.clean()


def test_live_hybrid_dgpu_disable_write_fails(w):
    w.eco()
    w.dgpu_disable_stuck = True
    rc, out, _ = w.go("live-hybrid")
    assert rc == 10 and last_json(out)["step"] == "dgpu_disable"
    assert conf(w.t).read_text() == ORIG
    assert (w.t / "sys/bus/pci/drivers_autoprobe").read_text() == "1"   # eco-exit restored it
    w.clean()


def test_live_hybrid_already_hybrid(w):
    w.hybrid()
    rc, out, _ = w.go("live-hybrid")
    assert rc == 0 and last_json(out) == {"ok": True, "mode": "Hybrid", "changed": False}
    assert w.ev == []


def test_live_hybrid_dgpu_on_but_driver_missing_finishes_the_job(w):
    w.hybrid()
    shutil.rmtree(w.t / "sys/module")
    (w.t / "sys/module").mkdir()
    (w.t / PCI / GPU / "driver").unlink()
    conf(w.t).write_text(INTEGRATED)
    rc, out, _ = w.go("live-hybrid")
    assert rc == 0 and last_json(out)["changed"] is True
    assert conf(w.t).read_text() == ORIG
    assert not any("dgpu_disable" in e for e in w.ev)
    w.clean()


def test_live_hybrid_mux_direct_and_precondition_and_root(w):
    w.eco()
    assert w.go("live-hybrid", fake_root=False)[0] == 5
    (w.t / RULE).unlink()
    rc, out, _ = w.go("live-hybrid")
    assert rc == 11 and last_json(out)["missing"] == ["/" + RULE]
    (w.t / RULE).write_text("mutter-device-ignore")
    (w.t / "sys/devices/platform/asus-nb-wmi/gpu_mux_mode").write_text("0\n")
    rc, out, _ = w.go("live-hybrid")
    assert rc == 4 and last_json(out) == {"ok": False, "error": "mux"}
    assert w.ev == [] and conf(w.t).read_text() == INTEGRATED and w.dgpu_disable() == 1


def test_live_hybrid_does_not_hardcode_address(w):
    w.eco()
    # card appears at 0000:65:00.0 instead: rename after creation
    real_fw = w.fake_w

    def fw(path, value):
        real_fw(path, value)
        if path.endswith("dgpu_disable") and value == "0":
            for a, b in ((GPU, "0000:65:00.0"), (AUDIO, "0000:65:00.1")):
                os.rename(w.t / PCI / a, w.t / PCI / b)
    w.mp.setattr(H, '_write_sysfs', fw)
    orig_run = w.fake_run

    def run2(cmd, timeout):
        rc = orig_run(cmd, timeout)
        if w.key(cmd) == "modprobe nvidia":
            link = w.t / PCI / "0000:65:00.0" / "driver"
            if not link.is_symlink():
                os.symlink("../../drivers/nvidia", link)
        if w.key(cmd) == "modprobe nvidia_drm":
            (w.t / PCI / "0000:65:00.0/drm/card1").mkdir(parents=True, exist_ok=True)
        return rc
    w.mp.setattr(H, '_run', run2)
    rc, out, err = w.go("live-hybrid")
    assert rc == 0, (out, err)
    assert "w sys/bus/pci/drivers_probe=0000:65:00.1" in w.ev


# ---------------------------------------------------------------- holders / status

def test_discovery_picks_nvidia_display_function_and_siblings(w):
    w.dgpu()
    paths, _ = H.resolve_env({H.ENV_ROOT: str(w.t)}, 1000)
    assert H._find_nvidia(paths) == GPU
    assert H._siblings(paths, GPU) == [AUDIO]


def test_holders_json_shape(w):
    w.hybrid()
    w.proc(100, "gnome-shell", "/dev/dri/card0", "/dev/null")                # iGPU only: no holder
    w.proc(200, "nvidia-persistenced", "/dev/nvidiactl", "/dev/nvidia0")      # excluded
    w.proc(300, "blender", "/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/dri/renderD129",
           "/dev/dri/renderD129", "/dev/nvidia0 (deleted)")
    w.proc(250, "mutter", "/dev/dri/card1")                                  # NVIDIA card node
    (w.t / "proc/self").mkdir()
    (w.t / "proc/notapid").mkdir()
    rc, out, _ = w.go("holders", fake_root=False)
    assert rc == 0
    j = last_json(out)
    assert set(j) == {"ok", "dgpu_present", "holders"} and j["ok"] is True and j["dgpu_present"] is True
    assert [h["pid"] for h in j["holders"]] == [250, 300]
    h300 = j["holders"][1]
    assert set(h300) == {"pid", "comm", "user", "exe", "nodes"}
    assert h300["comm"] == "blender" and h300["exe"] == "/usr/bin/blender"
    assert isinstance(h300["user"], str) and h300["user"]
    assert h300["nodes"] == ["/dev/dri/renderD129", "/dev/nvidia-uvm", "/dev/nvidia0", "/dev/nvidiactl"]
    assert j["holders"][0]["nodes"] == ["/dev/dri/card1"]


def test_holders_no_card_and_no_exe(w):
    w.eco()
    d = w.t / "proc/55"
    (d / "fd").mkdir(parents=True)
    (d / "comm").write_text("tool\n")
    os.symlink("/dev/nvidia0", d / "fd/3")
    j = last_json(w.go("holders", fake_root=False)[1])
    assert j["dgpu_present"] is False
    assert j["holders"][0]["exe"] is None            # unreadable exe -> null


def test_holders_changes_nothing_and_runs_nothing(w):
    w.hybrid()
    before = conf(w.t).read_text()
    assert w.go("holders", fake_root=False)[0] == 0
    assert w.ev == [] and conf(w.t).read_text() == before
    w.clean()


def test_status_new_keys(w):
    w.hybrid()
    w.proc(9, "app", "/dev/nvidia0")
    rc, out, _ = w.go("status", fake_root=False)
    j = last_json(out)
    assert rc == 0 and j["configured_mode"] == "Hybrid" and j["dgpu_disable"] == 0
    assert j["gpu_mux_mode"] == 1 and j["live_ready"] is True
    assert [h["pid"] for h in j["holders"]] == [9]


def test_status_eco_has_no_holders_and_live_ready_rules(w):
    w.eco()
    w.proc(9, "app", "/dev/nvidia0")
    j = last_json(w.go("status", fake_root=False)[1])
    assert j["holders"] == [] and j["live_ready"] is True
    (w.t / RULE).unlink()
    assert last_json(w.go("status", fake_root=False)[1])["live_ready"] is False
    (w.t / RULE).write_text("mutter-device-ignore")
    (w.t / "sys/devices/platform/asus-nb-wmi/gpu_mux_mode").write_text("0\n")
    assert last_json(w.go("status", fake_root=False)[1])["live_ready"] is False


# ---------------------------------------------------------------- misc / safety

def test_paths_rerooted_and_ignored_for_real_root(tree):
    paths, _ = H.resolve_env({H.ENV_ROOT: str(tree)}, 1000)
    for k, v in paths.items():
        assert v.startswith(str(tree)), k
    real, is_root = H.resolve_env({H.ENV_ROOT: str(tree), H.ENV_FAKE: "1"}, 0)
    assert is_root and all(v.startswith("/") and not v.startswith(str(tree)) for v in real.values())
    assert real["udevadm"] == "/usr/bin/udevadm" and real["proc"] == "/proc"
    assert real["modprobe"] in H.MODPROBE_CANDIDATES


def test_extra_args_are_usage_errors(tree):
    for args in (["live-eco", "x"], ["holders", "x"], ["live-hybrid", "x"]):
        assert run(tree, args)[0] == 2


def test_run_wrapper_is_the_only_subprocess_and_is_safe(monkeypatch):
    seen = {}

    class R:
        returncode = 3

    def fake(cmd, **kw):
        seen.update(cmd=cmd, kw=kw)
        return R()
    monkeypatch.setattr(H.subprocess, "run", fake)
    assert H._run(["/usr/sbin/modprobe", "-r", "nvidia"], 30) == 3
    assert seen["kw"]["timeout"] == 30 and seen["kw"]["env"] == H.CLEAN_ENV
    assert not seen["kw"].get("shell") and seen["kw"]["check"] is False
    monkeypatch.setattr(H.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        H.subprocess.TimeoutExpired("x", 1)))
    assert H._run(["/x"], 1) is None


def test_no_unsafe_calls_in_source():
    from tests.helper.test_gfx_helper import HELPER
    code = "\n".join(l for l in HELPER.read_text().splitlines() if not l.lstrip().startswith("#"))
    for bad in ("os.system", "shell=True", "Popen", "os.kill", "killpg", "pkill", "SIGKILL", "shutil.rmtree"):
        assert bad not in code
    assert code.count("subprocess.run(") == 1
