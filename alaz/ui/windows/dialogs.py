"""Confirmation dialogs. `ask()` is the single modal entry point (tests monkeypatch it)."""
from __future__ import annotations

import logging
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from alaz.i18n import tr
from alaz.ui import theme
from alaz.ui.widgets import make_button

log = logging.getLogger(__name__)

GPU_NAMES = {"eco": "Eco", "standard": "Standart"}   # Turkish source texts; translated via tr() on use
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
        if len(text) > 300:                  # long texts (Ultimate risk): wider, and size to the wrapped text
            self.setFixedWidth(480)
            lay.setSizeConstraint(lay.SizeConstraint.SetFixedSize)


def ask(parent: QWidget | None, title: str, text: str, ok_text: str = "", cancel_text: str = "",
        accent: str = theme.DEFAULT_ACCENT) -> bool:
    """Shows the dialog. Callers pass already translated texts (the defaults are translated here)."""
    dlg = ConfirmDialog(parent, title, text, ok_text or tr("Tamam"), cancel_text or tr("Vazgeç"), accent)
    return dlg.exec() == QDialog.DialogCode.Accepted


def confirm_gpu_change(parent: QWidget | None, mode: str, accent: str = theme.DEFAULT_ACCENT,
                       leaving_eco: bool = False) -> bool:
    name = tr(GPU_NAMES.get(mode, mode))
    if leaving_eco:
        return ask(parent, tr("Eco modundan çık"), tr(ECO_EXIT_TEXT), tr("Devam"), tr("Vazgeç"), accent)
    return ask(parent, tr("GPU modu: {name}", name=name),
               tr("{name} moduna geçiş yeniden başlatınca uygulanır; şu an hiçbir şey değişmez. "
                  "İstediğin zaman yeniden başlatmadan önce iptal edebilirsin.", name=name),
               tr("Devam"), tr("Vazgeç"), accent)


def confirm_reboot(parent: QWidget | None, accent: str = theme.DEFAULT_ACCENT) -> bool:
    return ask(parent, tr("Yeniden başlat"),
               tr("Bilgisayar şimdi yeniden başlatılacak. Açık işlerini kaydettiğinden emin ol."),
               tr("Yeniden başlat"), tr("Vazgeç"), accent)


def confirm_reboot_after_eco_exit(parent: QWidget | None, accent: str = theme.DEFAULT_ACCENT) -> bool:
    return ask(parent, tr("Yeniden başlatma gerekli"),
               tr("dGPU yeniden etkinleştirildi. Standart modun çalışması için bilgisayarı şimdi yeniden "
                  "başlatman gerekiyor. Açık işlerini kaydettiğinden emin ol."),
               tr("Yeniden başlat"), tr("Sonra"), accent)


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


# ------------------------------------------------------------------ live GPU switching (P4)
ULTIMATE_TITLE = "Ultimate moduna geç"
ULTIMATE_TEXT = (
    "Ultimate (MUX) modunda dahili ekran doğrudan NVIDIA dGPU’ya bağlanır; en yüksek oyun performansı budur. "
    "Geçiş için bilgisayarı yeniden başlatman GEREKİR.\n\n"
    "Risk: NVIDIA sürücüsü açılışta başarısız olursa iGPU’ya geri düşüş yoktur ve dahili ekran siyah kalır. "
    "Kurtarma: TTY’ye geç (Ctrl+Alt+F3) ya da Windows’taki G-Helper ile MUX’u geri al.\n\n"
    "Ultimate modundayken Eco ve Optimize kullanılamaz.")


def confirm_ultimate(parent: QWidget | None, accent: str = theme.DEFAULT_ACCENT) -> bool:
    return ask(parent, tr(ULTIMATE_TITLE), tr(ULTIMATE_TEXT), tr("Devam"), tr("Vazgeç"), accent)


def holder_names(holders) -> list[str]:
    """App names (exe basename, else comm) from Holder objects/dicts, de-duplicated, order kept."""
    names: list[str] = []
    for h in holders or []:
        get = (lambda k: h.get(k)) if isinstance(h, dict) else (lambda k: getattr(h, k, None))
        name = os.path.basename(str(get("exe") or "")) or str(get("comm") or "")
        if name and name not in names:
            names.append(name)
    return names


class BusyDialog(QDialog):
    """The dGPU is held by running apps: wait for them / apply at reboot / cancel. `choice` is set on close."""

    def __init__(self, parent: QWidget | None, names: list[str], accent: str = theme.DEFAULT_ACCENT):
        super().__init__(parent)
        self.setWindowTitle(tr("dGPU kullanımda"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(f"BusyDialog {{ background:{theme.PANEL}; border:1px solid {theme.BORDER}; }}")
        self.choice = "cancel"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel(tr("dGPU kullanımda"))
        t.setStyleSheet(f"font-size:15px; font-weight:700; color:{theme.TEXT}; background:transparent")
        self.apps_label = QLabel(", ".join(names) if names else tr("Bilinmeyen uygulama"))
        self.apps_label.setWordWrap(True)
        self.apps_label.setStyleSheet(f"font-size:13px; font-weight:600; color:{theme.TEXT}; background:transparent")
        body = QLabel(tr("Bu uygulamalar dGPU’yu kullanıyor. Hiçbiri otomatik kapatılmayacak. "
                         "Kapanınca geçilmesini bekleyebilir ya da geçişi bir sonraki yeniden başlatmaya bırakabilirsin."))
        body.setWordWrap(True)
        body.setStyleSheet(f"font-size:13px; color:{theme.TEXT2}; background:transparent")
        for w in (t, self.apps_label, body):
            lay.addWidget(w)
        lay.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.cancel_btn = make_button(tr("Vazgeç"), "ghost")
        self.reboot_btn = make_button(tr("Yeniden başlatınca uygula"), "secondary")
        self.wait_btn = make_button(tr("Kapatınca geç"), "primary", accent)
        for btn, ch in ((self.cancel_btn, "cancel"), (self.reboot_btn, "reboot"), (self.wait_btn, "wait")):
            btn.clicked.connect(lambda _=False, c=ch: self._done(c))
        self.wait_btn.setDefault(True)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        row.addWidget(self.reboot_btn)
        row.addWidget(self.wait_btn)
        lay.addLayout(row)

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.accept()


def ask_busy(parent: QWidget | None, holders, accent: str = theme.DEFAULT_ACCENT) -> str:
    """Single modal entry point for the busy dialog (tests monkeypatch it). Returns wait | reboot | cancel."""
    dlg = BusyDialog(parent, holder_names(holders), accent)
    dlg.exec()
    return dlg.choice


def gpu_choose(parent: QWidget | None, controller, gfx, key: str, accent: str = theme.DEFAULT_ACCENT) -> None:
    """A GPU mode was picked (main window tile or tray entry). Shared click rules."""
    if getattr(gfx, "switching", False):
        return
    selected = getattr(gfx, "selected", None) or gfx.active
    if key == selected:
        if gfx.pending or getattr(gfx, "waiting", None):
            controller.cancel_gpu_pending()
        return
    if key in ("eco", "standard") and not getattr(gfx, "live_ready", False):
        request_gpu_mode(parent, controller, key, accent, leaving_eco=(key == "standard" and gfx.active == "eco"))
        return
    controller.request_gpu_mode(key)    # live switch / optimize / ultimate (the controller asks what it needs)
