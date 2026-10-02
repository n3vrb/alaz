"""Dark blue-tinted theme — palette + QSS, matching the HTML mockup."""

from __future__ import annotations

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

# ── Colour tokens (mirrors HTML :root vars) ─────────────────────────────────
BG         = "#0d0d11"
BG_CARD    = "#14141b"
BG_IN      = "#1c1c26"
BORDER     = "#272736"
BORDER_SUB = "#1f1f2c"
TX         = "#eaeaf0"
TX2        = "#8686a0"
TX3        = "#4a4a62"
ACCENT     = "#5080f0"
ACCENT_H   = "#6a95ff"
OK         = "#2dd49a"
WARN       = "#f5a623"
DANGER     = "#e74c3c"

_F = "'DM Sans','Inter','Noto Sans','Segoe UI',sans-serif"

QSS = f"""
/* ── Global ─────────────────────────────────────────────────────────── */
* {{
    font-family: {_F};
    font-size: 13px;
    color: {TX};
    outline: none;
}}
QWidget   {{ background: {BG};      color: {TX}; }}
QMainWindow {{ background: {BG};    color: {TX}; }}
QDialog   {{ background: {BG};      color: {TX}; }}

/* ── Scroll bars ─────────────────────────────────────────────────────── */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical   {{ width: 5px;  background: transparent; border: none; margin: 0; }}
QScrollBar:horizontal {{ height: 5px; background: transparent; border: none; margin: 0; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {BORDER}; border-radius: 3px; min-height: 24px; min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ── Title bar ───────────────────────────────────────────────────────── */
QFrame#TitleBar {{
    background: {BG_CARD};
    border-bottom: 1px solid {BORDER_SUB};
}}

/* ── Sensor bar ──────────────────────────────────────────────────────── */
QFrame#SensorBar {{
    background: {BG_CARD};
    border-bottom: 1px solid {BORDER};
}}

/* ── Card ────────────────────────────────────────────────────────────── */
QFrame#Card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#CardTitle {{
    font-size: 9.5px; font-weight: 700;
    color: {TX3}; letter-spacing: 1.1px;
}}
QLabel#SubLabel {{
    font-size: 9.5px; font-weight: 700;
    color: {TX3}; letter-spacing: 0.9px;
}}
QLabel#Hint  {{ font-size: 11.5px; color: {TX3}; }}
QLabel#Muted {{ color: {TX2}; }}
QLabel#WarnHint {{ font-size: 11px; color: {WARN}; }}

/* ── Segmented control ───────────────────────────────────────────────── */
QFrame#Seg {{
    background: {BG_IN};
    border: 1px solid {BORDER};
    border-radius: 9px;
}}
QFrame#SegThumb {{ background: {ACCENT}; border-radius: 6px; }}

QPushButton#SegOpt {{
    background: transparent; border: none;
    color: {TX2}; font-size: 13px; font-weight: 500;
    padding: 7px 8px; border-radius: 6px; text-align: center;
}}
QPushButton#SegOpt.sm {{ padding: 6px 5px; font-size: 12px; }}
QPushButton#SegOpt[selected="true"] {{ color: #ffffff; font-weight: 600; }}
QPushButton#SegOpt:hover:enabled       {{ color: {TX}; }}
QPushButton#SegOpt:disabled {{ color: {TX3}; }}

/* ── Toggle label ────────────────────────────────────────────────────── */
QLabel#TogLabel {{ font-size: 13px; color: {TX2}; }}

/* ── Tab bar ─────────────────────────────────────────────────────────── */
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar {{ background: {BG_CARD}; padding-left: 14px; }}
QTabBar::tab {{
    background: transparent; color: {TX2};
    font-size: 13.5px; font-weight: 500;
    padding: 11px 15px; border: none; margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{ color: {TX}; }}

/* ── Buttons ─────────────────────────────────────────────────────────── */
QPushButton {{
    background: {BG_IN}; color: {TX2};
    border: 1px solid {BORDER}; border-radius: 7px;
    padding: 7px 17px; font-size: 13px; font-weight: 500;
}}
QPushButton:hover   {{ color: {TX}; border-color: {TX3}; }}
QPushButton:pressed {{ background: #0e0e18; }}
QPushButton:disabled {{ color: {TX3}; border-color: {BORDER_SUB}; }}

QPushButton#Primary {{
    background: {ACCENT}; color: #fff; border: none; font-weight: 600;
}}
QPushButton#Primary:hover   {{ background: {ACCENT_H}; }}
QPushButton#Primary:pressed {{ background: #3a6acc; }}

QPushButton#OkBtn {{
    background: {OK}; color: #fff; border: none; font-weight: 600;
}}
QPushButton#DangerBtn {{
    background: {DANGER}; color: #fff; border: none; font-weight: 600;
}}

/* Mode chips (Aura tab) ─── */
QPushButton#ModeChip {{
    background: {BG_IN}; color: {TX2};
    border: 1px solid {BORDER}; border-radius: 20px;
    padding: 5px 13px; font-size: 12px; font-weight: 500;
}}
QPushButton#ModeChip:hover:enabled {{ color: {TX}; border-color: {TX3}; }}
QPushButton#ModeChip[active="true"] {{
    background: rgba(80,128,240,.14);
    border-color: {ACCENT}; color: {ACCENT};
}}
QPushButton#ModeChip:disabled {{ color: {TX3}; border-color: {BORDER_SUB}; }}

/* Tray / corner mini button ─── */
QPushButton#MiniBtn {{
    background: {BG_IN}; color: {TX2};
    border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 13px; font-size: 12px; font-weight: 500;
}}
QPushButton#MiniBtn:hover {{ color: {TX}; border-color: {TX3}; }}

/* ── Slider ──────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    height: 5px; background: {BG_IN}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #fff; width: 17px; height: 17px; margin: -6px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: #fff;
    border: 2px solid {ACCENT};
}}

/* ── Input fields ────────────────────────────────────────────────────── */
QSpinBox, QLineEdit {{
    background: {BG_IN}; color: {TX};
    border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 10px; font-size: 13px;
}}
QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}

/* ── Combo ───────────────────────────────────────────────────────────── */
QComboBox {{
    background: {BG_IN}; color: {TX};
    border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 10px;
}}
QComboBox:focus  {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {BG_CARD}; color: {TX};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
}}

/* ── Checkbox (fans tab) ─────────────────────────────────────────────── */
QCheckBox {{ spacing: 8px; color: {TX2}; font-size: 12.5px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1.5px solid {BORDER}; border-radius: 4px;
    background: {BG_IN};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}

/* ── Tooltips / dialogs ──────────────────────────────────────────────── */
QToolTip {{
    background: {BG_CARD}; color: {TX};
    border: 1px solid {BORDER}; padding: 4px 8px; border-radius: 4px;
}}
QMessageBox {{ background: {BG_CARD}; }}
QMessageBox QPushButton {{ min-width: 80px; }}
QDialogButtonBox QPushButton {{ min-width: 80px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")

    p = QPalette()
    p.setColor(QPalette.Window,           QColor(BG))
    p.setColor(QPalette.WindowText,       QColor(TX))
    p.setColor(QPalette.Base,             QColor(BG_IN))
    p.setColor(QPalette.AlternateBase,    QColor(BG_CARD))
    p.setColor(QPalette.ToolTipBase,      QColor(BG_CARD))
    p.setColor(QPalette.ToolTipText,      QColor(TX))
    p.setColor(QPalette.Text,             QColor(TX))
    p.setColor(QPalette.Button,           QColor(BG_IN))
    p.setColor(QPalette.ButtonText,       QColor(TX2))
    p.setColor(QPalette.BrightText,       QColor("#ff5555"))
    p.setColor(QPalette.Highlight,        QColor(ACCENT))
    p.setColor(QPalette.HighlightedText,  QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text,       QColor(TX3))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TX3))
    app.setPalette(p)
    app.setStyleSheet(QSS)
