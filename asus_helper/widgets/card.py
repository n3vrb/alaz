from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """Dark card container matching the HTML .card element."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 14, 15, 15)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title_label = QLabel(title.upper())
        title_label.setObjectName("CardTitle")
        header.addWidget(title_label)
        header.addStretch()

        self._header = header
        layout.addLayout(header)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(10)
        layout.addLayout(self._body)

    def add_header_widget(self, widget: QWidget) -> None:
        self._header.addWidget(widget)

    def add(self, widget: QWidget, *, stretch: int = 0) -> None:
        self._body.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self._body.addLayout(layout)
