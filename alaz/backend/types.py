"""Shared enums and dataclasses used across the backend and UI."""
from __future__ import annotations

import enum
from dataclasses import dataclass


class Profile(enum.IntEnum):
    """asusd ThrottleThermalPolicy values."""

    BALANCED = 0
    PERFORMANCE = 1
    QUIET = 2


class Epp(enum.IntEnum):
    """asusd Throttle*Epp values."""

    DEFAULT = 0
    PERFORMANCE = 1
    BALANCE_PERFORMANCE = 2
    BALANCE_POWER = 3
    POWER = 4


class GfxMode(enum.IntEnum):
    """supergfxd Mode() values."""

    HYBRID = 0
    INTEGRATED = 1
    NVIDIA_NO_MODESET = 2
    VFIO = 3
    ASUS_EGPU = 4
    ASUS_MUX_DGPU = 5
    NONE = 6


class GfxPower(enum.IntEnum):
    """supergfxd Power() values."""

    ACTIVE = 0
    SUSPENDED = 1
    OFF = 2
    ASUS_DISABLED = 3
    ASUS_MUX_DISCRETE = 4
    UNKNOWN = 5


@dataclass(frozen=True)
class FanCurve:
    fan: str                       # "CPU" | "GPU" | "MID"
    temps: tuple[int, ...]         # 8 values, degrees C (255 = last point "and above")
    pwm: tuple[int, ...]           # 8 values, 0-255
    enabled: bool

    def percent(self) -> tuple[int, ...]:
        """PWM values converted to percent (0-100)."""
        return tuple(round(p * 100 / 255) for p in self.pwm)
