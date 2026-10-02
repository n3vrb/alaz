"""Periodic hardware sensor sampling (off the GUI thread).

Hard rule: the NVIDIA dGPU is never woken. ``nvidia-smi`` runs only when the
PCI device's ``power/runtime_status`` reads ``active`` AND a /proc scan shows a
real user holding ``/dev/nvidia[0-9]*`` open (every nvidia-smi run resets the
runtime-PM autosuspend timer, so polling it would keep the GPU awake forever).
Only ``power/runtime_status`` of the device is ever read.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field

import psutil
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

log = logging.getLogger(__name__)

SYSFS_PCI = "/sys/bus/pci/devices"
SYSFS_HWMON = "/sys/class/hwmon"
SYSFS_POWER = "/sys/class/power_supply"
NVIDIA_VENDOR = 0x10DE
SMI_BACKOFF_S = 30.0
SMI_MIN_INTERVAL_S = 5.0
USER_SCAN_INTERVAL_S = 5.0
PROC_ROOT = "/proc"
_NVIDIA_DEV = re.compile(r"^/dev/nvidia\d+$")
FAN_LABELS = {"cpu_fan": "cpu", "gpu_fan": "gpu", "mid_fan": "mid"}


@dataclass
class SensorSnapshot:
    cpu_temp: float | None = None
    cpu_load: float | None = None
    ram_pct: float | None = None
    gpu_state: str = "unknown"  # "sleep" | "active" | "off" | "unknown"
    gpu_temp: float | None = None
    gpu_load: float | None = None
    gpu_power_w: float | None = None
    fans_rpm: dict[str, int] = field(default_factory=dict)
    battery_pct: float | None = None
    battery_status: str | None = None
    on_ac: bool | None = None
    battery_power_w: float | None = None


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _read_num(path: str) -> float | None:
    s = _read(path)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_nvidia_pci(root: str = SYSFS_PCI) -> str | None:
    """Find the NVIDIA display controller by scanning sysfs (vendor/class only)."""
    for dev in sorted(glob.glob(os.path.join(root, "*"))):
        vendor = _read(os.path.join(dev, "vendor"))
        cls = _read(os.path.join(dev, "class"))
        if vendor is None or cls is None:
            continue
        try:
            if int(vendor, 16) == NVIDIA_VENDOR and (int(cls, 16) >> 16) == 0x03:
                return dev
        except ValueError:
            continue
    return None


def read_cpu_temp(root: str = SYSFS_HWMON) -> float | None:
    for hw in sorted(glob.glob(os.path.join(root, "hwmon*"))):
        if _read(os.path.join(hw, "name")) != "coretemp":
            continue
        fallback = None
        for lab in sorted(glob.glob(os.path.join(hw, "temp*_label"))):
            val = _read_num(lab.replace("_label", "_input"))
            if val is None:
                continue
            if (_read(lab) or "").startswith("Package id"):
                return val / 1000.0
            if fallback is None:
                fallback = val / 1000.0
        return fallback
    return None


def read_fans(root: str = SYSFS_HWMON) -> dict[str, int]:
    out: dict[str, int] = {}
    for hw in sorted(glob.glob(os.path.join(root, "hwmon*"))):
        if _read(os.path.join(hw, "name")) != "asus":
            continue
        for lab in sorted(glob.glob(os.path.join(hw, "fan*_label"))):
            key = FAN_LABELS.get(_read(lab) or "")
            val = _read_num(lab.replace("_label", "_input"))
            if key and val is not None:
                out[key] = int(val)
    return out


def read_power(root: str = SYSFS_POWER) -> tuple[float | None, str | None, bool | None, float | None]:
    """Return (battery_pct, status, on_ac, battery_watts)."""
    pct = status = on_ac = watts = None
    for sup in sorted(glob.glob(os.path.join(root, "*"))):
        typ = _read(os.path.join(sup, "type"))
        if typ == "Battery" and pct is None:
            pct = _read_num(os.path.join(sup, "capacity"))
            status = _read(os.path.join(sup, "status"))
            cur = _read_num(os.path.join(sup, "current_now"))
            volt = _read_num(os.path.join(sup, "voltage_now"))
            pw = _read_num(os.path.join(sup, "power_now"))
            if pw is not None:
                watts = abs(pw) / 1e6
            elif cur is not None and volt is not None:
                watts = abs(cur) * volt / 1e12
        elif typ == "Mains" and on_ac is None:
            v = _read(os.path.join(sup, "online"))
            if v in ("0", "1"):
                on_ac = v == "1"
    return pct, status, on_ac, watts


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def query_nvidia_smi(timeout: float = 3.0) -> tuple[float | None, float | None, float | None]:
    """Raises on failure. Caller must have verified the GPU is active."""
    res = subprocess.run(
        ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,power.draw",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=timeout,
    )
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or f"exit {res.returncode}")
    parts = [p.strip() for p in res.stdout.strip().splitlines()[0].split(",")]
    if len(parts) < 3:
        raise RuntimeError(f"unexpected output: {res.stdout!r}")
    return _num(parts[0]), _num(parts[1]), _num(parts[2])


# Processes that keep /dev/nvidiaN open permanently without keeping the GPU awake:
# the compositor/X servers open every GPU at startup (verified: gnome-shell and
# Xwayland hold it while runtime_status stays "suspended"). Counting them would
# make every wake-up look like real use and poll nvidia-smi forever.
_IGNORED_GPU_HOLDERS = ("nvidia-persist", "gnome-shell", "Xwayland", "Xorg", "mutter", "kwin_wayland")


def has_gpu_users(proc_root: str = PROC_ROOT, own_pid: int | None = None) -> bool:
    """True if any other process (not us, not nvidia-persistenced) holds /dev/nvidiaN open.

    Unreadable fd dirs (other users' processes) are skipped.
    """
    own = os.getpid() if own_pid is None else own_pid
    for pdir in glob.glob(os.path.join(proc_root, "[0-9]*")):
        pid = os.path.basename(pdir)
        if not pid.isdigit() or int(pid) == own:
            continue
        try:
            fds = os.listdir(os.path.join(pdir, "fd"))
        except OSError:
            continue
        hit = False
        for fd in fds:
            try:
                target = os.readlink(os.path.join(pdir, "fd", fd))
            except OSError:
                continue
            if _NVIDIA_DEV.match(target):
                hit = True
                break
        if not hit:
            continue
        comm = _read(os.path.join(pdir, "comm")) or ""
        if comm.startswith(_IGNORED_GPU_HOLDERS):
            continue
        return True
    return False


class Sampler:
    """Synchronous sampler; all paths injectable for tests."""

    def __init__(self, pci_root: str = SYSFS_PCI, hwmon_root: str = SYSFS_HWMON,
                 power_root: str = SYSFS_POWER, smi=query_nvidia_smi, clock=time.monotonic,
                 proc_root: str = PROC_ROOT, own_pid: int | None = None):
        self.pci_root, self.hwmon_root, self.power_root = pci_root, hwmon_root, power_root
        self._smi = smi
        self._clock = clock
        self._smi_retry_at = 0.0
        self._smi_next_at = 0.0
        self._smi_last: tuple[float | None, float | None, float | None] = (None, None, None)
        self.proc_root, self.own_pid = proc_root, own_pid
        self._users_checked_at: float | None = None
        self._users = False

    def _gpu_has_users(self) -> bool:
        now = self._clock()
        if self._users_checked_at is None or now - self._users_checked_at >= USER_SCAN_INTERVAL_S:
            self._users_checked_at = now
            self._users = has_gpu_users(self.proc_root, self.own_pid)
        return self._users

    def gpu(self) -> tuple[str, float | None, float | None, float | None]:
        dev = find_nvidia_pci(self.pci_root)
        if dev is None:
            return "off", None, None, None
        status = _read(os.path.join(dev, "power/runtime_status"))
        if status == "suspended":
            return "sleep", None, None, None
        if status != "active":
            return ("sleep" if status == "suspending" else "unknown"), None, None, None
        if not self._gpu_has_users():
            self._smi_last = (None, None, None)
            self._smi_next_at = 0.0
            return "active", None, None, None
        now = self._clock()
        if now < self._smi_retry_at:
            return "active", None, None, None
        if now < self._smi_next_at:
            return ("active", *self._smi_last)
        try:
            self._smi_next_at = now + SMI_MIN_INTERVAL_S
            self._smi_last = self._smi()
            return ("active", *self._smi_last)
        except Exception as exc:  # noqa: BLE001
            log.warning("nvidia-smi failed, backing off %ss: %s", SMI_BACKOFF_S, exc)
            self._smi_retry_at = self._clock() + SMI_BACKOFF_S
            self._smi_last = (None, None, None)
            return "active", None, None, None

    def sample(self) -> SensorSnapshot:
        snap = SensorSnapshot()
        try:
            snap.cpu_load = psutil.cpu_percent(interval=None)
            snap.ram_pct = psutil.virtual_memory().percent
        except Exception:  # noqa: BLE001
            log.debug("psutil failed", exc_info=True)
        snap.cpu_temp = read_cpu_temp(self.hwmon_root)
        snap.fans_rpm = read_fans(self.hwmon_root)
        (snap.battery_pct, snap.battery_status,
         snap.on_ac, snap.battery_power_w) = read_power(self.power_root)
        (snap.gpu_state, snap.gpu_temp, snap.gpu_load, snap.gpu_power_w) = self.gpu()
        return snap


class _Bridge(QObject):
    done = pyqtSignal(object)


class _Task(QRunnable):
    def __init__(self, reader: "SensorReader"):
        super().__init__()
        self._r = reader

    def run(self) -> None:
        try:
            snap = self._r._sampler.sample()
            self._r._bridge.done.emit(snap)
        except Exception:  # noqa: BLE001
            log.exception("sensor sample failed")
        finally:
            self._r._busy = False


class SensorReader(QObject):
    updated = pyqtSignal(object)  # SensorSnapshot

    def __init__(self, sampler: Sampler | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._sampler = sampler or Sampler()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._busy = False
        self._bridge = _Bridge(self)
        self._bridge.done.connect(self.updated)  # queued across threads
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self, interval_ms: int = 1000) -> None:
        self._timer.start(interval_ms)
        self._tick()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._pool.start(_Task(self))
