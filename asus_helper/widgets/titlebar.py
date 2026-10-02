"""Custom frameless title bar — macOS-style dots, icon, name, system-move drag."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from ..theme import BG_CARD, TX2

_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"


class _DotButton(QPushButton):
    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ background:{color}; border-radius:6px; border:none; }}"
            f"QPushButton:hover {{ background:{color}; opacity:.85; }}"
        )


class TitleBar(QFrame):
    """44 px title bar to be placed at the top of a frameless QMainWindow."""

    def __init__(
        self,
        window: QWidget,
        title: str = "Asus Helper",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent or window)
        self._win = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(44)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 0, 14, 0)
        outer.setSpacing(0)

        # ── macOS dots (left) ─────────────────────────────────────────────
        dots = QWidget()
        dots_lay = QHBoxLayout(dots)
        dots_lay.setContentsMargins(0, 0, 0, 0)
        dots_lay.setSpacing(7)

        self._close_btn    = _DotButton("#FF5F57")
        self._minimize_btn = _DotButton("#FEBC2E")
        self._maximize_btn = _DotButton("#28C840")

        dots_lay.addWidget(self._close_btn)
        dots_lay.addWidget(self._minimize_btn)
        dots_lay.addWidget(self._maximize_btn)
        outer.addWidget(dots)

        outer.addStretch()

        # ── centre: icon + name ──────────────────────────────────────────
        center = QWidget()
        center.setAttribute(Qt.WA_TransparentForMouseEvents)
        c_lay = QHBoxLayout(center)
        c_lay.setContentsMargins(0, 0, 0, 0)
        c_lay.setSpacing(9)

        icon_box = QFrame()
        icon_box.setFixedSize(26, 26)
        icon_box.setStyleSheet(
            "QFrame { background:#1a1a28; border:1px solid #2e2e48; border-radius:7px; }"
        )
        ib_lay = QHBoxLayout(icon_box)
        ib_lay.setContentsMargins(0, 0, 0, 0)
        svg = _ASSETS / "icon.svg"
        if svg.exists():
            ico_lbl = QLabel()
            ico_lbl.setPixmap(QIcon(str(svg)).pixmap(QSize(18, 18)))
            ico_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            ib_lay.addWidget(ico_lbl, 0, Qt.AlignCenter)

        name_lbl = QLabel(title)
        name_lbl.setStyleSheet(
            f"font-size:13px; font-weight:500; color:{TX2}; "
            "letter-spacing:0.1px; background:transparent;"
        )
        name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)

        c_lay.addWidget(icon_box)
        c_lay.addWidget(name_lbl)
        outer.addWidget(center)

        outer.addStretch()

        # ── right filler matches dot area width for symmetry ─────────────
        filler = QWidget()
        filler.setFixedWidth(dots.sizeHint().width() + 10)
        outer.addWidget(filler)

        # ── connect dots ─────────────────────────────────────────────────
        self._close_btn.clicked.connect(window.close)
        self._minimize_btn.clicked.connect(window.showMinimized)
        self._maximize_btn.clicked.connect(self._toggle_max)

    # ── drag support (works on both X11 and Wayland via startSystemMove) ─
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            wh = self._win.windowHandle()
            if wh:
                wh.startSystemMove()
        super().mousePressEvent(e)

    def _toggle_max(self) -> None:
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()
