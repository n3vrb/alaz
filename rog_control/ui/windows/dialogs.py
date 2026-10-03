"""Confirmation dialogs. `ask()` is the single modal entry point (tests monkeypatch it)."""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from rog_control.ui import theme
from rog_control.ui.widgets import make_button

log = logging.getLogger(__name__)

GPU_NAMES = {"eco": "Eco", "standard": "Standart"}
ECO_EXIT_TEXT = ("dGPU şimdi yeniden etkinleştirilecek ve bilgisayarı hemen ardından yeniden başlatman "
                 "GEREKİYOR. Yeniden başlatana kadar yeni bir USB/Thunderbolt aygıtı takma. "
                 "Açık işlerini kaydetmeye hazır mısın?")


class ConfirmDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, text: str, ok_text: str, cancel_text: str,
                 accent: str = theme.DEFAULT_ACCENT):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self.setStyleSheet(f"ConfirmDialog {{ background:{theme.PANEL}; border:1px solid {theme.BORDER}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel(title)
        t.setStyleSheet(f"font-size:15px; font-weight:700; color:{theme.TEXT}; background:transparent")
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(f"font-size:13px; color:{theme.TEXT2}; background:transparent")
        lay.addWidget(t)
        lay.addWidget(body)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = make_button(cancel_text, "ghost")
        self.ok_btn = make_button(ok_text, "primary", accent)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)
        self.ok_btn.setDefault(True)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        lay.addLayout(row)


def ask(parent: QWidget | None, title: str, text: str, ok_text: str = "Tamam", cancel_text: str = "Vazgeç",
        accent: str = theme.DEFAULT_ACCENT) -> bool:
    dlg = ConfirmDialog(parent, title, text, ok_text, cancel_text, accent)
    return dlg.exec() == QDialog.DialogCode.Accepted


def confirm_gpu_change(parent: QWidget | None, mode: str, accent: str = theme.DEFAULT_ACCENT,
                       leaving_eco: bool = False) -> bool:
    name = GPU_NAMES.get(mode, mode)
    if leaving_eco:
        return ask(parent, "Eco modundan çık", ECO_EXIT_TEXT, "Devam", "Vazgeç", accent)
    return ask(parent, f"GPU modu: {name}",
               f"{name} moduna geçiş yeniden başlatınca uygulanır; şu an hiçbir şey değişmez. "
               "İstediğin zaman yeniden başlatmadan önce iptal edebilirsin.",
               "Devam", "Vazgeç", accent)


def confirm_reboot(parent: QWidget | None, accent: str = theme.DEFAULT_ACCENT) -> bool:
    return ask(parent, "Yeniden başlat",
               "Bilgisayar şimdi yeniden başlatılacak. Açık işlerini kaydettiğinden emin ol.",
               "Yeniden başlat", "Vazgeç", accent)


def confirm_reboot_after_eco_exit(parent: QWidget | None, accent: str = theme.DEFAULT_ACCENT) -> bool:
    return ask(parent, "Yeniden başlatma gerekli",
               "dGPU yeniden etkinleştirildi. Standart modun çalışması için bilgisayarı şimdi yeniden "
               "başlatman gerekiyor. Açık işlerini kaydettiğinden emin ol.",
               "Yeniden başlat", "Sonra", accent)


def request_gpu_mode(parent: QWidget | None, controller, mode: str, accent: str = theme.DEFAULT_ACCENT,
                     leaving_eco: bool = False) -> bool:
    """Confirm, then ask the controller for a boot-time GPU mode change. Returns True if requested."""
    if confirm_gpu_change(parent, mode, accent, leaving_eco):
        controller.request_gpu_mode(mode)
        return True
    return False


def reboot_now(parent: QWidget | None, controller, accent: str = theme.DEFAULT_ACCENT,
               after_eco_exit: bool = False) -> bool:
    confirm = confirm_reboot_after_eco_exit if after_eco_exit else confirm_reboot
    if confirm(parent, accent):
        controller.reboot_now()
        return True
    return False
