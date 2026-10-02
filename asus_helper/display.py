"""Refresh-rate control.

Primary path: GNOME/Mutter D-Bus `org.gnome.Mutter.DisplayConfig`
(`GetCurrentState` + `ApplyMonitorsConfig`) — the only working method on
GNOME Wayland. X11 sessions fall back to `xrandr --rate`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

try:
    import gi

    gi.require_version("Gio", "2.0")
    gi.require_version("GLib", "2.0")
    from gi.repository import Gio, GLib

    _HAVE_GIO = True
except Exception:  # noqa: BLE001
    _HAVE_GIO = False


MUTTER_NAME = "org.gnome.Mutter.DisplayConfig"
MUTTER_PATH = "/org/gnome/Mutter/DisplayConfig"
APPLY_METHOD_PERSISTENT = 2  # 0=verify, 1=temporary, 2=persistent


class DisplayError(RuntimeError):
    pass


@dataclass
class DisplayState:
    connector: str
    current_hz: int
    rates: list[int] = field(default_factory=list)
    # internal: rounded rate -> Mutter mode id (only used by the Mutter path)
    _rate_to_mode: dict[int, str] = field(default_factory=dict)


def _is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


def available() -> bool:
    if _HAVE_GIO:
        return True
    return shutil.which("xrandr") is not None


# ---------------------------------------------------------------------------
# Mutter path
# ---------------------------------------------------------------------------

def _bus():
    if not _HAVE_GIO:
        raise DisplayError("Gio not available")
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def _get_current_state():
    bus = _bus()
    res = bus.call_sync(
        MUTTER_NAME, MUTTER_PATH, MUTTER_NAME, "GetCurrentState",
        None, None, Gio.DBusCallFlags.NONE, -1, None,
    )
    return res.unpack()  # (serial, monitors, logical_monitors, props)


def _mutter_state() -> DisplayState:
    serial, monitors, logical, props = _get_current_state()

    # Pick the primary monitor's connector (fallback: first monitor).
    primary_connector = None
    for lm in logical:
        x, y, scale, transform, primary, mons, lprops = lm
        if primary and mons:
            primary_connector = mons[0][0]
            break
    if primary_connector is None and monitors:
        primary_connector = monitors[0][0][0]

    state = DisplayState(connector=primary_connector or "", current_hz=0)

    for mon in monitors:
        (conn, vendor, product, ser), modes, mprops = mon
        if conn != primary_connector:
            continue
        # Determine current resolution from the current mode.
        cur_w = cur_h = None
        for m in modes:
            mode_id, w, h, refresh, pref_scale, supported_scales, mode_props = m
            if mode_props.get("is-current"):
                cur_w, cur_h = w, h
                state.current_hz = int(round(refresh))
        # Collect rates available at the current resolution.
        for m in modes:
            mode_id, w, h, refresh, pref_scale, supported_scales, mode_props = m
            if (w, h) == (cur_w, cur_h):
                rate = int(round(refresh))
                # First mode wins for a given rounded rate (keeps preferred).
                state._rate_to_mode.setdefault(rate, mode_id)
        break

    state.rates = sorted(state._rate_to_mode.keys())
    return state


def _mutter_set_rate(connector: str, hz: int) -> None:
    serial, monitors, logical, props = _get_current_state()

    # Map each monitor's current mode id, and find target mode for `connector`.
    current_mode: dict[str, str] = {}
    target_mode: Optional[str] = None
    for mon in monitors:
        (conn, vendor, product, ser), modes, mprops = mon
        cur_w = cur_h = None
        for m in modes:
            mode_id, w, h, refresh, pref_scale, supported_scales, mode_props = m
            if mode_props.get("is-current"):
                current_mode[conn] = mode_id
                cur_w, cur_h = w, h
        if conn == connector:
            for m in modes:
                mode_id, w, h, refresh, pref_scale, supported_scales, mode_props = m
                if (w, h) == (cur_w, cur_h) and int(round(refresh)) == hz:
                    target_mode = mode_id
                    break
    if target_mode is None:
        raise DisplayError(f"no {hz} Hz mode for {connector} at current resolution")

    # Rebuild logical monitors for ApplyMonitorsConfig: a(iiduba(ssa{sv})).
    lm_entries = []
    for lm in logical:
        x, y, scale, transform, primary, mons, lprops = lm
        mon_entries = []
        for mref in mons:
            conn = mref[0]
            mode_id = target_mode if conn == connector else current_mode.get(conn)
            if mode_id is None:
                continue
            mon_entries.append((conn, mode_id, {}))
        lm_entries.append((int(x), int(y), float(scale), int(transform), bool(primary), mon_entries))

    params = GLib.Variant(
        "(uua(iiduba(ssa{sv}))a{sv})",
        (serial, APPLY_METHOD_PERSISTENT, lm_entries, {}),
    )
    bus = _bus()
    bus.call_sync(
        MUTTER_NAME, MUTTER_PATH, MUTTER_NAME, "ApplyMonitorsConfig",
        params, None, Gio.DBusCallFlags.NONE, -1, None,
    )


# ---------------------------------------------------------------------------
# xrandr (X11) path
# ---------------------------------------------------------------------------

def _xrandr_state() -> DisplayState:
    out = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=5).stdout
    connector = ""
    rates: set[int] = set()
    current = 0
    in_connected = False
    for line in out.splitlines():
        m = re.match(r"^(\S+) connected", line)
        if m:
            if connector:  # only the first connected output
                break
            connector = m.group(1)
            in_connected = True
            continue
        if in_connected and re.match(r"^\s+\d+x\d+", line):
            for tok in re.findall(r"(\d+\.\d+)(\*?)", line):
                rate, star = tok
                r = int(round(float(rate)))
                rates.add(r)
                if star == "*":
                    current = r
    return DisplayState(connector=connector, current_hz=current, rates=sorted(rates))


def _xrandr_set_rate(connector: str, hz: int) -> None:
    subprocess.run(
        ["xrandr", "--output", connector, "--rate", str(hz)],
        capture_output=True, text=True, timeout=8, check=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_display_state() -> Optional[DisplayState]:
    try:
        if _HAVE_GIO and _is_wayland():
            return _mutter_state()
        if _HAVE_GIO:
            # X11 under GNOME still answers Mutter; prefer it.
            try:
                return _mutter_state()
            except Exception:  # noqa: BLE001
                pass
        if shutil.which("xrandr"):
            return _xrandr_state()
    except Exception:  # noqa: BLE001
        return None
    return None


def set_refresh_rate(connector: str, hz: int) -> None:
    if _HAVE_GIO:
        try:
            _mutter_set_rate(connector, hz)
            return
        except DisplayError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Fall through to xrandr only on X11.
            if not shutil.which("xrandr") or _is_wayland():
                raise DisplayError(str(exc)) from exc
    if shutil.which("xrandr"):
        try:
            _xrandr_set_rate(connector, hz)
            return
        except subprocess.CalledProcessError as exc:
            raise DisplayError(exc.stderr or str(exc)) from exc
    raise DisplayError("no display backend available")
