"""Top bar while connected: connection status, Disconnect and ALL TO 0."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from . import theme as th


class ConnectionBar(QWidget):
    disconnect_clicked = Signal()
    all_zero_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.status_label = QLabel()
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setToolTip("Set every flow to 0 and go back to the start screen")
        self.disconnect_button.setMinimumWidth(100)
        self.zero_button = QPushButton("ALL TO 0")
        self.zero_button.setToolTip("Cancel all ramps and set every flow to 0 (F12).\n"
                                    "This is a software command, not a hardware interlock.")
        self.zero_button.setStyleSheet(
            f"QPushButton {{ background: {th.CRITICAL}; color: white; font-weight: bold; padding: 6px 18px; "
            f"border-radius: 4px; }} QPushButton:disabled {{ background: #9b8f8f; color: #eeeeee; }}")
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.disconnect_button)
        layout.addSpacing(8)
        layout.addWidget(self.zero_button)
        self.disconnect_button.clicked.connect(self.disconnect_clicked)
        self.zero_button.clicked.connect(self.all_zero_clicked)

    def set_status(self, text, color=th.GOOD):
        self.status_label.setText(f'<span style="color:{color}">●</span> {text}')
        self.status_label.setToolTip(text)
