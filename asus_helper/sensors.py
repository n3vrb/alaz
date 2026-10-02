"""Real-time telemetry: CPU/GPU temps, usage, RAM, fan RPM, power, battery.

Unprivileged sources only:
  * psutil       -> CPU %/temp, RAM, battery, fan RPM
  * nvidia-smi   -> GPU util/temp/power/mem  (NVIDIA)
  * sysfs        -> gpu_busy_percent fallback (non-NVIDIA)
  * RAPL         -> CPU package watts, best-effort (usually root-only)

`read_once()` returns a single synchronous snapshot (handy for tests / tray).
`SensorReader` runs a `QTimer` inside its own `QThread` and emits
`updated(SensorSnapshot)` once per interval for the UI.
"""

from __future__ import annotations

import glob
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

try:
    import psutil
except Exception:  # noqa: BLE001 — degrade gracefully if missing
    psutil = None  # type: ignore


@dataclass
class SensorSnapshot:
    cpu_pct: Optional[float] = None
    cpu_temp: Optional[float] = None
    ram_pct: Optional[float] = None
    ram_used_gb: Optional[float] = None
    battery_pct: Optional[float] = None
    battery_plugged: Optional[bool] = None
    battery_status: Optional[str] = None   # "Charging" / "Discharging" / "Full" / "Not charging"
    fan_rpm: dict[str, int] = field(default_factory=dict)  # 'cpu'/'gpu'/'mid'
    gpu_util: Optional[float] = None
    gpu_temp: Optional[float] = None
    gpu_power_w: Optional[float] = None
    gpu_mem_used_mb: Optional[float] = None
    gpu_mem_total_mb: Optional[float] = None
    cpu_power_w: Optional[float] = None


# ---------------------------------------------------------------------------
# Individual readers
# ---------------------------------------------------------------------------

def _cpu_temp() -> Optional[float]:
    if psutil is None:
        return None
    try:
        temps = psutil.sensors_temperatures()
    except Exception:  # noqa: BLE001
        return None
    if not temps:
        return None
    # Preferred chips/labels in priority order.
    for chip, label in (
        ("coretemp", "Package id 0"),
        ("k10temp", "Tctl"),
        ("zenpower", "Tdie"),
    ):
        for entry in temps.get(chip, []):
            if entry.label == label and entry.current:
                return float(entry.current)
    # Fallbacks: acpitz, then the hottest core seen anywhere.
    for entry in temps.get("acpitz", []):
        if entry.current:
            return float(entry.current)
    hottest = None
    for arr in temps.values():
        for entry in arr:
            if entry.current and (hottest is None or entry.current > hottest):
                hottest = entry.current
    return float(hottest) if hottest is not None else None


def _fan_rpm() -> dict[str, int]:
    out: dict[str, int] = {}
    if psutil is None or not hasattr(psutil, "sensors_fans"):
        return out
    try:
        fans = psutil.sensors_fans() or {}
    except Exception:  # noqa: BLE001
        return out
    for chip, arr in fans.items():
        for entry in arr:
            label = (entry.label or "").lower()
            if "cpu" in label:
                out["cpu"] = int(entry.current)
            elif "gpu" in label:
                out["gpu"] = int(entry.current)
            elif "mid" in label:
                out["mid"] = int(entry.current)
    return out


class _GpuReader:
    """NVIDIA via nvidia-smi, with a sysfs busy% fallback."""

    def __init__(self) -> None:
        self.nvidia = shutil.which("nvidia-smi") is not None

    def read(self, snap: SensorSnapshot) -> None:
        if self.nvidia and self._read_nvidia(snap):
            return
        self._read_sysfs(snap)

    def _read_nvidia(self, snap: SensorSnapshot) -> bool:
        try:
            proc = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=4,
            )
        except Exception:  # noqa: BLE001
            return False
        if proc.returncode != 0 or not proc.stdout.strip():
            return False
        first = proc.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        if len(parts) < 5:
            return False

        def _f(value: str) -> Optional[float]:
            try:
                return float(value)
            except ValueError:
                return None

        snap.gpu_util = _f(parts[0])
        snap.gpu_temp = _f(parts[1])
        snap.gpu_power_w = _f(parts[2])
        snap.gpu_mem_used_mb = _f(parts[3])
        snap.gpu_mem_total_mb = _f(parts[4])
        return snap.gpu_util is not None

    def _read_sysfs(self, snap: SensorSnapshot) -> None:
        for path in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    snap.gpu_util = float(fh.read().strip())
                    return
            except (OSError, ValueError):
                continue


class _CpuPower:
    """RAPL energy_uj delta -> watts. Disables itself on PermissionError."""

    def __init__(self) -> None:
        self.path = "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"
        self.max_path = "/sys/class/powercap/intel-rapl/intel-rapl:0/max_energy_range_uj"
        self.enabled = True
        self._last_energy: Optional[int] = None
        self._last_time: Optional[float] = None
        self._wrap: Optional[int] = None
        self._read_wrap()

    def _read_wrap(self) -> None:
        try:
            with open(self.max_path, "r", encoding="utf-8") as fh:
                self._wrap = int(fh.read().strip())
        except (OSError, ValueError):
            self._wrap = None

    def read(self) -> Optional[float]:
        if not self.enabled:
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                energy = int(fh.read().strip())
        except PermissionError:
            self.enabled = False
            return None
        except (OSError, ValueError):
            return None
        now = time.monotonic()
        watts = None
        if self._last_energy is not None and self._last_time is not None:
            delta_e = energy - self._last_energy
            if delta_e < 0 and self._wrap:  # counter wrapped
                delta_e += self._wrap
            delta_t = now - self._last_time
            if delta_t > 0 and delta_e >= 0:
                watts = (delta_e / 1e6) / delta_t
        self._last_energy = energy
        self._last_time = now
        return watts


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class _Sampler:
    def __init__(self) -> None:
        self._gpu = _GpuReader()
        self._cpu_power = _CpuPower()
        self._primed = False
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)  # prime
            except Exception:  # noqa: BLE001
                pass
            self._primed = True

    def sample(self, include_gpu: bool = True) -> SensorSnapshot:
        snap = SensorSnapshot()
        if psutil is not None:
            try:
                snap.cpu_pct = psutil.cpu_percent(interval=None)
            except Exception:  # noqa: BLE001
                pass
            try:
                vm = psutil.virtual_memory()
                snap.ram_pct = vm.percent
                snap.ram_used_gb = round(vm.used / 1e9, 2)
            except Exception:  # noqa: BLE001
                pass
            try:
                bat = psutil.sensors_battery()
                if bat is not None:
                    snap.battery_pct    = float(bat.percent)
                    snap.battery_plugged = bool(bat.power_plugged)
            except Exception:  # noqa: BLE001
                pass
            snap.cpu_temp = _cpu_temp()
            snap.fan_rpm  = _fan_rpm()
        # Battery status from sysfs (more accurate than psutil's plugged flag).
        # "Charging" / "Discharging" / "Full" / "Not charging"
        for _p in glob.glob("/sys/class/power_supply/BAT*/status"):
            try:
                with open(_p, "r", encoding="utf-8") as _f:
                    snap.battery_status = _f.read().strip()
            except OSError:
                pass
            break
        if include_gpu:
            self._gpu.read(snap)
        snap.cpu_power_w = self._cpu_power.read()
        return snap


_DEFAULT_SAMPLER: Optional[_Sampler] = None


def read_once() -> SensorSnapshot:
    """One synchronous snapshot (CPU% needs two calls to be meaningful)."""
    global _DEFAULT_SAMPLER
    if _DEFAULT_SAMPLER is None:
        _DEFAULT_SAMPLER = _Sampler()
        if psutil is not None:
            time.sleep(0.1)  # let cpu_percent accumulate a delta
    return _DEFAULT_SAMPLER.sample()


# ---------------------------------------------------------------------------
# Threaded reader for the UI
# ---------------------------------------------------------------------------
#
# A main-thread QTimer fires once per interval and dispatches a single sample
# onto a one-thread QThreadPool, so the (potentially blocking) nvidia-smi call
# never stalls the GUI. The pool worker emits the snapshot via a signal that is
# delivered back on the main thread. The timer itself stays in the main thread,
# avoiding cross-thread timer issues.

class _SampleRunnable(QRunnable):
    def __init__(self, sampler: "_Sampler", emit) -> None:
        super().__init__()
        self._sampler = sampler
        self._emit = emit

    def run(self) -> None:  # executed in a pool thread
        try:
            snap = self._sampler.sample()
        except Exception:  # noqa: BLE001 — never let a bad read crash the pool
            return
        self._emit(snap)


class SensorReader(QObject):
    """Polls sensors off the GUI thread and emits `updated(SensorSnapshot)`."""

    updated = pyqtSignal(object)  # SensorSnapshot

    def __init__(self, interval_ms: int = 1000, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sampler = _Sampler()  # primes cpu_percent in the main thread
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        # Paint psutil data (CPU/RAM/fans/battery) immediately (~70 ms),
        # skipping GPU: nvidia-smi has a ~2.6 s cold start on the first call
        # per process. The GPU fields fill in on the first background sample.
        try:
            self.updated.emit(self._sampler.sample(include_gpu=False))
        except Exception:  # noqa: BLE001
            pass
        self._timer.start()

    def _tick(self) -> None:
        if self._busy:
            return  # previous sample still running; skip this beat
        self._busy = True
        self._pool.start(_SampleRunnable(self._sampler, self._on_sample))

    def _on_sample(self, snap: SensorSnapshot) -> None:
        # Called from the pool thread; emit hops back to the main thread via
        # the queued signal connection on `updated`.
        self._busy = False
        self.updated.emit(snap)

    def stop(self) -> None:
        self._timer.stop()
        self._pool.waitForDone(2000)
