from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import backend
from .sensors import SensorSnapshot
from .widgets.sensor_bar import SensorBar
from .widgets.segmented import SegmentedControl
from .widgets.titlebar import TitleBar
from .theme import TX3


class MiniWindow(QWidget):
    """Compact always-on-top window — matches the HTML .win.mini layout."""

    closed = pyqtSignal()

    def __init__(
        self, capabilities: backend.Capabilities, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self._caps = capabilities
        self.setWindowTitle("Asus Helper — Mini")
        self.setFixedWidth(480)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(TitleBar(self, "Asus Helper — Mini"))

        self.sensor_bar = SensorBar()
        col.addWidget(self.sensor_bar)

        body = QVBoxLayout()
        body.setContentsMargins(16, 14, 16, 16)
        body.setSpacing(14)

        body.addLayout(self._section("PROFILE"))
        self.profile_seg = SegmentedControl(["Silent", "Balanced", "Turbo"])
        self.profile_seg.selected.connect(self._on_profile)
        body.addWidget(self.profile_seg)

        if self._caps.supergfxd_available:
            try:
                supported = backend.get_supported_gpu_modes()
            except backend.BackendError:
                supported = []
        else:
            supported = []
        gpu_labels = [backend.SUPERGFX_TO_GPU_LABEL.get(m, m) for m in supported]

        if gpu_labels:
            body.addLayout(self._section("GPU MODE"))
            self.gpu_seg = SegmentedControl(gpu_labels)
            self.gpu_seg.selected.connect(self._on_gpu)
            body.addWidget(self.gpu_seg)
        else:
            self.gpu_seg = None

        row = QHBoxLayout()
        row.addStretch()
        full_btn = QPushButton("Full window")
        full_btn.clicked.connect(self.closed.emit)
        row.addWidget(full_btn)
        body.addLayout(row)

        col.addLayout(body)
        self.refresh_states()

    def _section(self, text: str) -> QHBoxLayout:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size:9.5px; font-weight:700; color:{TX3}; "
            "text-transform:uppercase; letter-spacing:1.1px; "
            "background:transparent;"
        )
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(lbl)
        return lay

    def _on_profile(self, label: str) -> None:
        try:
            backend.set_profile(backend.PROFILE_LABEL_TO_ASUSCTL[label])
        except backend.BackendError:
            pass
        QTimer.singleShot(400, self.refresh_states)

    def _on_gpu(self, label: str) -> None:
        target = backend.GPU_LABEL_TO_SUPERGFX.get(label, label)
        try:
            backend.set_gpu_mode(target)
        except backend.BackendError:
            pass
        QTimer.singleShot(400, self.refresh_states)

    def refresh_states(self) -> None:
        if self._caps.asusd_available:
            try:
                cur   = backend.get_profile()
                label = backend.ASUSCTL_TO_PROFILE_LABEL.get(cur, cur)
                self.profile_seg.set_value(label)
            except backend.BackendError:
                pass
        if self.gpu_seg is not None and self._caps.supergfxd_available:
            try:
                cur   = backend.get_gpu_mode()
                label = backend.SUPERGFX_TO_GPU_LABEL.get(cur, cur)
                self.gpu_seg.set_value(label)
            except backend.BackendError:
                pass

    def update_snapshot(self, snap: SensorSnapshot) -> None:
        self.sensor_bar.update_snapshot(snap)

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.closed.emit()
