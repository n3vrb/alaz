"""Application-level dialogs shared across tabs and the tray."""

from __future__ import annotations

import os
import subprocess

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


COUNTDOWN_SECONDS = 20


def _current_user() -> str:
    return (
        os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        or "root"
    )


def _do_logout() -> None:
    user = _current_user()
    try:
        subprocess.Popen(["loginctl", "terminate-user", user])
    except Exception:  # noqa: BLE001
        pass


class LogoutCountdownDialog(QDialog):
    """20-second countdown dialog shown after a GPU mode switch that needs logout.

    Cancel  → stops the timer; the switch is complete but the user keeps the
              session — the new GPU mode will take effect on the *next* logout.
    Logout Now → immediately terminates the current session.
    Countdown → auto-logout when it reaches zero.
    """

    def __init__(
        self,
        from_label: str,
        to_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._remaining = COUNTDOWN_SECONDS
        self._from = from_label
        self._to = to_label

        self.setWindowTitle("Logout Required")
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowTitleHint
            | Qt.WindowCloseButtonHint
            | Qt.MSWindowsFixedSizeDialogHint
        )
        self.setMinimumWidth(380)

        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(20, 18, 20, 18)

        info = QLabel(
            f"GPU mode switched from <b>{from_label}</b> to <b>{to_label}</b>.\n\n"
            "A logout is required for the change to take effect."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        lay.addWidget(info)

        self._countdown_label = QLabel()
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setStyleSheet(
            "font-size: 28px; font-weight: 700; color: #4a90e2;"
        )
        self._update_countdown_label()
        lay.addWidget(self._countdown_label)

        self._status = QLabel("Logging out automatically…")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color: #9a9a9a; font-size: 12px;")
        lay.addWidget(self._status)

        btn_box = QDialogButtonBox()
        self._cancel_btn = btn_box.addButton("Cancel", QDialogButtonBox.RejectRole)
        self._logout_btn = btn_box.addButton("Logout Now", QDialogButtonBox.AcceptRole)
        self._logout_btn.setObjectName("Primary")
        self._logout_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; border-color: #c0392b; color: white; }"
            "QPushButton:hover { background-color: #e74c3c; }"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._logout_btn.clicked.connect(self._on_logout_now)
        lay.addWidget(btn_box)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ----- helpers -----

    def _update_countdown_label(self) -> None:
        self._countdown_label.setText(str(self._remaining))

    def _tick(self) -> None:
        self._remaining -= 1
        self._update_countdown_label()
        if self._remaining <= 0:
            self._timer.stop()
            self._status.setText("Logging out…")
            # Give the UI a moment to paint before terminating the session.
            QTimer.singleShot(200, _do_logout)
            self.accept()

    # ----- button slots -----

    def _on_cancel(self) -> None:
        self._timer.stop()
        self._status.setText("Cancelled — logout when ready to apply the GPU change.")
        self.reject()

    def _on_logout_now(self) -> None:
        self._timer.stop()
        _do_logout()
        self.accept()

    # ----- public factory -----

    @staticmethod
    def maybe_show(
        supergfx_result: str,
        from_label: str,
        to_label: str,
        parent: QWidget | None = None,
    ) -> None:
        """Show the dialog only when the supergfxctl result implies logout.

        If the action is "none" / "no action required", return immediately
        without any dialog so the UI update is silent.
        """
        lowered = supergfx_result.lower()
        if "logout" in lowered or "log out" in lowered:
            dlg = LogoutCountdownDialog(from_label, to_label, parent)
            dlg.exec_()
