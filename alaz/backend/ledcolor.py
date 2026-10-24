"""sRGB <-> linear conversion for RGB LEDs (ROG mouse, laptop keyboard).

LEDs drive their PWM linearly while UI colours are sRGB (gamma-encoded). Sent raw, mixed colours wash out
or shift: VERIFIED visually by the owner on the Harpe Ace Mini (#FF5A5F looked pink; FF 1A 1D matched) and on
the laptop keyboard (#FFD84D looked greenish; FF AF 13 matched).
"""
from __future__ import annotations


def _srgb_to_linear(c: int) -> int:
    x = c / 255.0
    lin = x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return round(lin * 255)


def _linear_to_srgb(c: int) -> int:
    x = c / 255.0
    enc = x * 12.92 if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
    return round(enc * 255)


def led_encode(rgb) -> tuple[int, int, int]:
    """UI (sRGB) colour -> value written to the LED."""
    return tuple(_srgb_to_linear(int(c)) for c in rgb)


def led_decode(rgb) -> tuple[int, int, int]:
    """Value read from the LED -> UI (sRGB) colour (lossy for very dark channels)."""
    return tuple(_linear_to_srgb(int(c)) for c in rgb)
