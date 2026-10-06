"""The Alaz application icon (window, title bar, tray fallback), coloured per GPU mode."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtGui import QIcon, QPixmap

ICON_DIR = Path(__file__).resolve().parent / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
# active GPU modes with their own logo colour (tools/make_logo.py); "eco" and unknown/None use the base logo
MODE_VARIANTS = ("standard", "ultimate", "optimize")


def _load(prefix: str) -> QIcon:
    icon = QIcon()
    for s in SIZES:
        p = ICON_DIR / f"{prefix}-{s}.png"
        if p.exists():
            icon.addFile(str(p))
    return icon


@lru_cache(maxsize=None)
def app_icon(mode: str | None = None) -> QIcon:
    """Bundled PNGs at every size for `mode`; falls back to the base logo, then the installed theme icon."""
    icon = _load(f"alaz-{mode}") if mode in MODE_VARIANTS else QIcon()
    if icon.isNull():
        icon = _load("alaz")
    if icon.isNull():
        icon = QIcon.fromTheme("alaz")
    return icon


def app_pixmap(size: int, mode: str | None = None) -> QPixmap:
    return app_icon(mode).pixmap(size, size)
