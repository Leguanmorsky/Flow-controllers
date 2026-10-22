"""Top bar: port selection, connect/disconnect, connection status and ALL TO 0."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget

from ..core.ports import describe_ports
from . import theme as th
from .bridge import SIM_PORT


class ConnectionBar(QWidget):
    connect_clicked = Signal(str)       # "auto", "COMx" or SIM_PORT
    disconnect_clicked = Signal()
    all_zero_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "disconnected"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(230)
        self.port_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.refresh_button = QToolButton(text="⟳")
        self.refresh_button.setToolTip("Refresh the list of COM ports")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setMinimumWidth(100)
        self.status_label = QLabel()
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.sim_badge = QLabel("SIMULATOR")
        self.sim_badge.setStyleSheet(f"background: {th.SERIOUS}; color: #0b0b0b; font-weight: bold; "
                                     f"padding: 3px 8px; border-radius: 4px;")
        self.sim_badge.setToolTip("Simulated instruments: no real gas is flowing")
        self.sim_badge.hide()
        self.zero_button = QPushButton("ALL TO 0")
        self.zero_button.setToolTip("Cancel all ramps and set every flow to 0 (F12).\n"
                                    "This is a software command, not a hardware interlock.")
        self.zero_button.setStyleSheet(
            f"QPushButton {{ background: {th.CRITICAL}; color: white; font-weight: bold; padding: 6px 18px; "
            f"border-radius: 4px; }} QPushButton:disabled {{ background: #9b8f8f; color: #eeeeee; }}")
        layout.addWidget(QLabel("Port"))
        layout.addWidget(self.port_combo)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.connect_button)
        layout.addSpacing(8)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.sim_badge)
        layout.addSpacing(8)
        layout.addWidget(self.zero_button)

        self.refresh_button.clicked.connect(lambda: self.refresh_ports())
        self.connect_button.clicked.connect(self._on_connect_button)
        self.zero_button.clicked.connect(self.all_zero_clicked)
        self.set_state("disconnected", "Not connected")

    def refresh_ports(self, select=None):
        select = select or self.selected_port()
        self.port_combo.clear()
        self.port_combo.addItem("Auto-detect", "auto")
        for device, description, bluetooth in describe_ports():
            if bluetooth:
                self.port_combo.addItem(f"{device} – Bluetooth (skipped)", device)
                self.port_combo.model().item(self.port_combo.count() - 1).setEnabled(False)
            else:
                self.port_combo.addItem(f"{device} – {description}" if description else device, device)
        self.port_combo.addItem("Simulator (no hardware)", SIM_PORT)
        if select and self.port_combo.findData(select) < 0:
            self.port_combo.insertItem(1, f"{select} (not found now)", select)
        index = self.port_combo.findData(select) if select else 0
        self.port_combo.setCurrentIndex(max(index, 0))

    def selected_port(self):
        return self.port_combo.currentData()

    def set_state(self, state, text, error=False):
        """state: "disconnected", "connecting" or "connected"."""
        self.state = state
        self.connect_button.setText({"disconnected": "Connect", "connecting": "Cancel",
                                     "connected": "Disconnect"}[state])
        self.port_combo.setEnabled(state == "disconnected")
        self.refresh_button.setEnabled(state == "disconnected")
        self.zero_button.setEnabled(state == "connected")
        color = th.CRITICAL if error else {"connected": th.GOOD, "connecting": th.WARNING}.get(state, "#8a8984")
        self.status_label.setText(f'<span style="color:{color}">●</span> {text}')
        self.status_label.setToolTip(text)

    def set_simulated(self, on):
        self.sim_badge.setVisible(on)

    def _on_connect_button(self):
        if self.state == "disconnected":
            self.connect_clicked.emit(self.selected_port())
        else:
            self.disconnect_clicked.emit()
