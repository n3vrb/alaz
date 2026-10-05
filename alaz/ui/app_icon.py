"""The Alaz application icon (window, title bar, tray fallback)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtGui import QIcon, QPixmap

ICON_DIR = Path(__file__).resolve().parent / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """Bundled PNGs at every size; falls back to the installed theme icon."""
    icon = QIcon()
    for s in SIZES:
        p = ICON_DIR / f"alaz-{s}.png"
        if p.exists():
            icon.addFile(str(p))
    if icon.isNull():
        icon = QIcon.fromTheme("alaz")
    return icon


def app_pixmap(size: int) -> QPixmap:
    return app_icon().pixmap(size, size)
