"""Live power-draw text: one pure formatter plus a tiny moving-average smoother.

With RAPL psys: "Sistem N W" always (+ " · Şarj +M W" while charging). Fallback without psys:
Discharging -> whole-system draw ("Sistem 26 W"); charging -> battery charge power ("Şarj +65 W");
anything else (full / not charging / unknown) -> no watts. Never invents a value.
"""
from __future__ import annotations

from collections import deque

from rog_control.i18n import tr


def power_kind(status: str | None, watts: float | None) -> str | None:
    """'system' (discharging), 'charge' (charging) or None when no watts should be shown."""
    if watts is None:
        return None
    if status == "Discharging":
        return "system"
    if status == "Charging":
        return "charge"
    return None


def power_text(watts: float | None, status: str | None) -> str | None:
    """'Sistem 26 W' / 'Şarj +65 W' / None."""
    kind = power_kind(status, watts)
    if kind == "system":
        return tr("Sistem {w} W", w=f"{watts:.0f}")
    if kind == "charge":
        return tr("Şarj +{w} W", w=f"{watts:.0f}")
    return None


def source_text(on_ac: bool | None) -> str | None:
    return None if on_ac is None else (tr("Prizde") if on_ac else tr("Pilde"))


def power_line(watts: float | None, status: str | None, on_ac: bool | None, sep: str = " · ") -> str:
    """'Pilde · Sistem 26 W' / 'Prizde · Şarj +65 W' / 'Prizde' / '' (unknown)."""
    return sep.join(p for p in (source_text(on_ac), power_text(watts, status)) if p)


def compose_power(system_w: float | None, charge_w: float | None) -> str | None:
    """'Sistem 48 W · Şarj +40 W' / 'Sistem 31 W' / 'Şarj +65 W' / None."""
    parts = []
    if system_w is not None:
        parts.append(tr("Sistem {w} W", w=f"{system_w:.0f}"))
    if charge_w is not None:
        parts.append(tr("Şarj +{w} W", w=f"{charge_w:.0f}"))
    return " · ".join(parts) or None


class PowerSmoother:
    """Moving average over the last `n` samples; resets when the battery status changes."""

    def __init__(self, n: int = 5):
        self._buf: deque[float] = deque(maxlen=n)
        self._status: str | None = None

    def push(self, watts: float | None, status: str | None) -> float | None:
        if status != self._status:
            self._buf.clear()
            self._status = status
        if watts is None:
            return None
        self._buf.append(watts)
        return sum(self._buf) / len(self._buf)


class PowerView:
    """Smooths both numbers (5 samples) and picks the source.

    system: RAPL psys when available (AC or battery); otherwise the battery discharge power
    (which on battery equals system draw). charge: battery power while charging.
    """

    def __init__(self, n: int = 5):
        self._sys = PowerSmoother(n)
        self._chg = PowerSmoother(n)

    def push(self, system_w: float | None, battery_w: float | None,
             status: str | None) -> tuple[float | None, float | None]:
        if system_w is None and status == "Discharging":
            system_w = battery_w
        charge = battery_w if status == "Charging" else None
        return self._sys.push(system_w, status), self._chg.push(charge, status)
