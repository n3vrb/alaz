"""Design tokens, fonts and the global QSS (source: docs/design/V2*.dc.html)."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase

# surfaces
BG = "#0E0F13"
PANEL = "#16181E"
PANEL_DARK = "#121419"
CONTROL = "#1E2129"
BORDER = "#2A2E38"
DIVIDER = "#23262E"
GRID_AXIS = "#3A3F4B"
# text
TEXT = "#ECEEF3"
TEXT2 = "#A3A9B6"
TEXT3 = "#8F96A3"
TEXT_TILE = "#C9CED8"
INK = "#0B0C0F"
# warning banner
WARN_BG = "#2A2112"
WARN_BORDER = "#5C4517"
WARN_TEXT = "#F7DDA8"
WARN_SUB = "#D9C29A"
WARN_ACCENT = "#F2A93B"

MODE_COLORS = {
    "Sessiz": "#34C08A", "Dengeli": "#4C8DFF", "Turbo": "#FF5A5F", "Özel": "#F2A93B",
    "Eco": "#34C08A", "Standart": "#4C8DFF", "Ultimate": "#FF5A5F", "Optimize": "#F2A93B",
}
DEFAULT_ACCENT = MODE_COLORS["Dengeli"]

_PREFERRED = ("IBM Plex Sans", "Inter", "Noto Sans", "Ubuntu", "Cantarell", "Open Sans", "Roboto", "DejaVu Sans")
_family_cache: str | None = None


def font_family() -> str:
    """IBM Plex Sans if installed, else the first available fallback, else system default."""
    global _family_cache
    if _family_cache is None:
        have = set(QFontDatabase.families())
        _family_cache = next((f for f in _PREFERRED if f in have), "") or QFont().family()
    return _family_cache


def ui_font(px: float = 13, weight: int = 400, spacing: float = 0.0) -> QFont:
    """Font sized in CSS pixels. `spacing` is letter spacing in px."""
    f = QFont(font_family())
    f.setPixelSize(int(round(px)))
    f.setWeight(QFont.Weight(max(100, min(900, weight))))
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def color(hex_or_color, alpha: float = 1.0) -> QColor:
    c = QColor(hex_or_color)
    if alpha < 1.0:
        c.setAlphaF(alpha)
    return c


def qss(accent: str = DEFAULT_ACCENT) -> str:
    """Application-wide stylesheet (plain controls: buttons, tooltips, scrollbars, sliders)."""
    return f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QToolTip {{ background: {CONTROL}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; border-radius: 6px; }}
QPushButton {{ height: 34px; padding: 0 14px; border: 1px solid {BORDER}; border-radius: 8px;
  background: {CONTROL}; color: {TEXT}; font-size: 13px; }}
QPushButton:hover {{ background: #272B35; }}
QPushButton:pressed {{ background: #2F3440; }}
QPushButton:disabled {{ color: {TEXT3}; background: {PANEL}; }}
QPushButton:focus {{ border-color: {TEXT}; }}
QPushButton[accent="true"] {{ background: {accent}; border: 0; color: {INK}; font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: {QColor(accent).lighter(112).name()}; }}
QPushButton[flat="true"], QToolButton {{ background: transparent; border: 0; border-radius: 8px; color: {TEXT2}; }}
QPushButton[flat="true"]:hover, QToolButton:hover {{ background: {CONTROL}; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {accent}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
  border: 2px solid {INK}; }}
QSlider::handle:horizontal:disabled {{ background: {TEXT3}; }}
QSlider::groove:horizontal:disabled {{ background: {DIVIDER}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollArea {{ border: 0; background: transparent; }}
"""


def apply(app, accent: str = DEFAULT_ACCENT) -> None:
    """Set the application font (13px; explicit widget fonts must not be overridden by QSS) and stylesheet."""
    app.setFont(ui_font(13, 400))
    app.setStyleSheet(qss(accent))
