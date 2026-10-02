"""Subprocess wrappers around asusctl and supergfxctl.

All shell-out happens here. UI code imports this module and never invokes
the CLIs directly. Privileged actions rely on the asusd/supergfxd polkit
policies — we do not prepend `pkexec`.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterable

ASUSCTL = "asusctl"
SUPERGFXCTL = "supergfxctl"

PROFILE_LABEL_TO_ASUSCTL = {"Silent": "Quiet", "Balanced": "Balanced", "Turbo": "Performance"}
ASUSCTL_TO_PROFILE_LABEL = {v: k for k, v in PROFILE_LABEL_TO_ASUSCTL.items()}

GPU_LABEL_TO_SUPERGFX = {
    "Eco": "Integrated",
    "Hybrid": "Hybrid",
    "Standard": "Hybrid",
    "Ultimate": "AsusMuxDgpu",
}
SUPERGFX_TO_GPU_LABEL = {"Integrated": "Eco", "Hybrid": "Hybrid", "AsusMuxDgpu": "Ultimate"}

FANS = ("cpu", "gpu", "mid")
BRIGHTNESS_LEVELS = ("off", "low", "med", "high")


class BackendError(RuntimeError):
    """Raised when an asusctl/supergfxctl invocation fails."""


@dataclass(frozen=True)
class Capabilities:
    asusd_available: bool
    supergfxd_available: bool
    aura_modes: tuple[str, ...]
    aura_zones: tuple[str, ...]
    brightness_levels: tuple[str, ...]
    core_functions: tuple[str, ...]
    panel_overdrive: bool = False
    has_panel_overdrive: bool = False
    flicker_free_iface: str | None = None
    aura_devices: tuple[str, ...] = ()
    have_nvidia: bool = False


def _run(cmd: list[str], *, timeout: float = 10.0) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise BackendError(f"{cmd[0]} not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"{' '.join(cmd)} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise BackendError(f"{' '.join(cmd)}: {msg}")
    return proc.stdout


def _strip_banner(text: str) -> str:
    """asusctl prints a 'Starting version X' banner on stdout — drop it."""
    return "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith("Starting version")
        and not line.startswith("Found aura device")
    )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def have_asusctl() -> bool:
    return shutil.which(ASUSCTL) is not None


def have_supergfxctl() -> bool:
    return shutil.which(SUPERGFXCTL) is not None


def asusd_running() -> bool:
    try:
        _run([ASUSCTL, "profile", "-p"])
        return True
    except BackendError:
        return False


def supergfxd_running() -> bool:
    try:
        _run([SUPERGFXCTL, "-g"])
        return True
    except BackendError:
        return False


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def list_profiles() -> list[str]:
    """Return asusctl profile names in the order asusctl reports them."""
    out = _strip_banner(_run([ASUSCTL, "profile", "-l"]))
    names = [ln.strip() for ln in out.splitlines() if ln.strip()]
    # Keep only known profile names defensively.
    known = {"Quiet", "Balanced", "Performance"}
    return [n for n in names if n in known]


def get_profile() -> str:
    out = _strip_banner(_run([ASUSCTL, "profile", "-p"]))
    match = re.search(r"Active profile is (\w+)", out)
    if not match:
        raise BackendError(f"could not parse profile from: {out!r}")
    return match.group(1)


def set_profile(asusctl_name: str) -> None:
    if asusctl_name not in {"Quiet", "Balanced", "Performance"}:
        raise BackendError(f"unknown profile {asusctl_name!r}")
    _run([ASUSCTL, "profile", "-P", asusctl_name])


# ---------------------------------------------------------------------------
# GPU mode (supergfxctl)
# ---------------------------------------------------------------------------

def get_gpu_mode() -> str:
    return _run([SUPERGFXCTL, "-g"]).strip()


def get_supported_gpu_modes() -> list[str]:
    out = _run([SUPERGFXCTL, "-s"]).strip()
    # Output looks like: [Integrated, Hybrid, AsusMuxDgpu]
    inner = out.strip().strip("[]")
    return [item.strip() for item in inner.split(",") if item.strip()]


def set_gpu_mode(mode: str) -> str:
    """Switch GPU mode. Returns the pending-action string from supergfxctl."""
    out = _run([SUPERGFXCTL, "-m", mode], timeout=20.0).strip()
    # supergfxctl usually echoes something like:
    #   "Switching mode requires: Reboot"
    # or "Pending action: none"
    return out


def get_pending_gpu_action() -> str:
    try:
        return _run([SUPERGFXCTL, "-p"]).strip()
    except BackendError:
        return ""


def get_pending_gpu_mode() -> str:
    try:
        return _run([SUPERGFXCTL, "-P"]).strip()
    except BackendError:
        return ""


# ---------------------------------------------------------------------------
# Battery charge limit
# ---------------------------------------------------------------------------

def set_charge_limit(percent: int) -> None:
    if not 20 <= percent <= 100:
        raise BackendError("charge limit must be in 20..100")
    _run([ASUSCTL, "-c", str(percent)])


def read_charge_limit() -> int:
    """Read charge_control_end_threshold from sysfs (no root needed)."""
    for path in glob.glob("/sys/class/power_supply/BAT*/charge_control_end_threshold"):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            continue
    return 100


# ---------------------------------------------------------------------------
# Fan curves
# ---------------------------------------------------------------------------

_FAN_BLOCK_RE = re.compile(
    r"\(\s*fan:\s*(?P<fan>\w+),\s*"
    r"pwm:\s*\((?P<pwm>[^)]*)\),\s*"
    r"temp:\s*\((?P<temp>[^)]*)\),\s*"
    r"enabled:\s*(?P<enabled>true|false)",
    re.IGNORECASE,
)


def _parse_tuple(text: str) -> list[int]:
    return [int(x.strip()) for x in text.split(",") if x.strip()]


@dataclass
class FanCurve:
    fan: str
    points: list[tuple[int, int]]  # (temp °C, pwm %)
    enabled: bool


def get_fan_curves(asusctl_profile: str) -> dict[str, FanCurve]:
    """Return all fan curves for a profile keyed by fan name (lowercase)."""
    out = _strip_banner(_run([ASUSCTL, "fan-curve", "-m", asusctl_profile]))
    curves: dict[str, FanCurve] = {}
    for match in _FAN_BLOCK_RE.finditer(out):
        fan_name = match.group("fan").lower()
        pwm_raw = _parse_tuple(match.group("pwm"))
        temp = _parse_tuple(match.group("temp"))
        # asusctl pwm values come back as 0-255 byte values. Convert to % for UI.
        pwm_pct = [round(p * 100 / 255) for p in pwm_raw]
        # asusctl sometimes emits 255 as a sentinel for the trailing "above" anchor.
        # Clamp to a sane upper bound so the editor doesn't plot it off-chart.
        temp = [min(t, 110) for t in temp]
        points = list(zip(temp, pwm_pct))
        curves[fan_name] = FanCurve(
            fan=fan_name,
            points=points,
            enabled=match.group("enabled").lower() == "true",
        )
    return curves


def get_fan_curve(asusctl_profile: str, fan: str) -> FanCurve:
    curves = get_fan_curves(asusctl_profile)
    if fan not in curves:
        raise BackendError(f"fan {fan!r} not present in profile {asusctl_profile!r}")
    return curves[fan]


def set_fan_curve(asusctl_profile: str, fan: str, points: Iterable[tuple[int, int]]) -> None:
    data = ",".join(f"{int(t)}c:{int(p)}%" for t, p in points)
    _run([
        ASUSCTL, "fan-curve",
        "-m", asusctl_profile,
        "-f", fan,
        "-D", data,
    ])


def enable_fan_curve(asusctl_profile: str, fan: str, enabled: bool) -> None:
    _run([
        ASUSCTL, "fan-curve",
        "-m", asusctl_profile,
        "-f", fan,
        "-E", "true" if enabled else "false",
    ])


def reset_fan_curves(asusctl_profile: str) -> None:
    _run([ASUSCTL, "fan-curve", "-d", "-m", asusctl_profile])


# ---------------------------------------------------------------------------
# Aura / keyboard backlight
# ---------------------------------------------------------------------------

def set_kbd_brightness(level: str) -> None:
    level = level.lower()
    if level not in BRIGHTNESS_LEVELS:
        raise BackendError(f"unknown brightness {level!r}")
    _run([ASUSCTL, "-k", level])


def set_aura_static(hex_color: str, zone: str | None = None) -> None:
    color = hex_color.lstrip("#").lower()
    if not re.fullmatch(r"[0-9a-f]{6}", color):
        raise BackendError(f"bad hex color {hex_color!r}")
    cmd = [ASUSCTL, "led-mode", "static", "-c", color]
    if zone:
        cmd += ["-z", zone]
    _run(cmd)


def list_aura_devices() -> list[str]:
    """Enumerate asusd Aura device object paths under /org/asuslinux.

    Best-effort: uses `busctl` if present. Returns the dynamic object paths
    (e.g. ``/org/asuslinux/19b6_3_6``). On this laptop there is a single
    built-in keyboard device.
    """
    if shutil.which("busctl") is None:
        return []
    try:
        out = _run(["busctl", "--system", "tree", "org.asuslinux.Daemon"], timeout=5)
    except BackendError:
        return []
    paths = []
    for line in out.splitlines():
        m = re.search(r"(/org/asuslinux/\S+)", line)
        if m:
            paths.append(m.group(1))
    return paths


# ---------------------------------------------------------------------------
# Panel overdrive (asusctl bios)
# ---------------------------------------------------------------------------

def get_panel_overdrive() -> bool:
    out = _strip_banner(_run([ASUSCTL, "bios", "-o"]))
    return "true" in out.lower()


def set_panel_overdrive(on: bool) -> None:
    _run([ASUSCTL, "bios", "-O", "true" if on else "false"])


def _panel_overdrive_supported() -> bool:
    try:
        out = _strip_banner(_run([ASUSCTL, "bios", "-o"]))
    except BackendError:
        return False
    return "panel overdrive" in out.lower()


# ---------------------------------------------------------------------------
# Flicker-free / panel dimming detection (auto-hide if unsupported)
# ---------------------------------------------------------------------------

_FLICKER_FREE_GLOBS = (
    "/sys/class/backlight/*/dimming_mode",
    "/sys/class/drm/card*/*/panel_dimming",
    "/sys/devices/platform/asus-nb-wmi/flicker_free*",
)


def detect_flicker_free() -> str | None:
    """Return a writable sysfs path for flicker-free dimming, else None.

    asusctl 6.0.12 does not expose this on the target laptop; we probe a few
    known sysfs nodes so the toggle only appears when a real interface exists.
    """
    for pattern in _FLICKER_FREE_GLOBS:
        for path in glob.glob(pattern):
            if os.access(path, os.R_OK):
                return path
    return None


def get_flicker_free(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() not in ("0", "off", "")
    except OSError:
        return False


def set_flicker_free(path: str, on: bool) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("1" if on else "0")
    except OSError as exc:
        raise BackendError(f"could not write {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Capability probe
# ---------------------------------------------------------------------------

def probe_capabilities() -> Capabilities:
    """Parse `asusctl -s` once to learn what the firmware exposes."""
    asusd = have_asusctl() and asusd_running()
    supergfx = have_supergfxctl() and supergfxd_running()
    aura_modes: tuple[str, ...] = ()
    aura_zones: tuple[str, ...] = ()
    levels: tuple[str, ...] = ()
    core: tuple[str, ...] = ()
    panel_od = False
    has_panel_od = False
    aura_devices: tuple[str, ...] = ()
    if asusd:
        try:
            out = _strip_banner(_run([ASUSCTL, "-s"]))
            core = tuple(_extract_list(out, "Supported Core Functions"))
            aura_modes = tuple(_extract_list(out, "Supported Aura Modes"))
            aura_zones = tuple(_extract_list(out, "Supported Aura Zones"))
            levels = tuple(s.lower() for s in _extract_list(out, "Supported Keyboard Brightness"))
        except BackendError:
            pass
        has_panel_od = _panel_overdrive_supported()
        if has_panel_od:
            try:
                panel_od = get_panel_overdrive()
            except BackendError:
                pass
        aura_devices = tuple(list_aura_devices())
    return Capabilities(
        asusd_available=asusd,
        supergfxd_available=supergfx,
        aura_modes=aura_modes,
        aura_zones=aura_zones,
        brightness_levels=levels or BRIGHTNESS_LEVELS,
        core_functions=core,
        panel_overdrive=panel_od,
        has_panel_overdrive=has_panel_od,
        flicker_free_iface=detect_flicker_free(),
        aura_devices=aura_devices,
        have_nvidia=shutil.which("nvidia-smi") is not None,
    )


def _extract_list(text: str, heading: str) -> list[str]:
    pattern = re.compile(re.escape(heading) + r":\s*\[(?P<body>[^\]]*)\]", re.DOTALL)
    match = pattern.search(text)
    if not match:
        return []
    body = match.group("body")
    return [item.strip().strip('"') for item in body.split(",") if item.strip()]
