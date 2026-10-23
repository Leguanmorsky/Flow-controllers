"""Start screen: connect to the real instruments or start test mode."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from ..config import ASSETS_DIR, load_simulator
from ..core.ports import describe_ports
from ..core.simulator import DEFAULT_CHANNELS
from . import theme as th
from .bridge import SIM_PORT


def simulated_gases():
    """Short description of the instruments in config/simulator.json."""
    try:
        channels = load_simulator().get("channels", DEFAULT_CHANNELS)
    except Exception as e:      # shown on the start screen; connecting reports it again
        return f"config/simulator.json is invalid: {e}"
    return " · ".join(f"{gas} {capacity:g} {unit}" for _, gas, capacity, unit, *_ in channels)


class StartPage(QWidget):
    connect_requested = Signal(str)     # "auto" or a COM port
    test_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, test_only=False, parent=None):
        super().__init__(parent)
        self.test_only = test_only
        self.busy = False

        logo = QLabel()
        logo.setPixmap(QPixmap(str(ASSETS_DIR / "logo.png")).scaled(
            96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        title = QLabel("Flow controllers")
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 2.0)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        self.subtitle = QLabel("Bronkhorst mass flow controllers. How do you want to start?")
        self.subtitle.setAlignment(Qt.AlignCenter)

        # Real instruments
        self.device_card = QFrame()
        self.device_card.setObjectName("startCard")
        device = QVBoxLayout(self.device_card)
        device.setContentsMargins(18, 16, 18, 16)
        device_title = QLabel("Connect to the instruments")
        device_title.setFont(self._heading_font())
        device_text = QLabel("Uses the real flow controllers: setpoints you send make gas flow.")
        device_text.setWordWrap(True)
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_button = QToolButton(text="⟳")
        self.refresh_button.setToolTip("Refresh the list of COM ports")
        port_row.addWidget(QLabel("Port"))
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_button)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setMinimumHeight(36)
        self.test_only_note = QLabel("This session was started in test mode (run.bat --sim). Start run.bat "
                                     "without --sim to use the instruments.")
        self.test_only_note.setWordWrap(True)
        device.addWidget(device_title)
        device.addWidget(device_text)
        device.addSpacing(6)
        device.addLayout(port_row)
        device.addStretch(1)
        device.addWidget(self.test_only_note)
        device.addWidget(self.connect_button)

        # Test mode
        self.test_card = QFrame()
        self.test_card.setObjectName("startCard")
        test = QVBoxLayout(self.test_card)
        test.setContentsMargins(18, 16, 18, 16)
        test_title = QLabel("Test mode")
        test_title.setFont(self._heading_font())
        test_text = QLabel("Simulated instruments: try setpoints, ramps and mixtures. "
                           "Nothing is sent to the real flow controllers, no gas flows.")
        test_text.setWordWrap(True)
        self.gases_label = QLabel()
        self.gases_label.setWordWrap(True)
        self.gases_label.setToolTip("Set the simulated instruments in config/simulator.json")
        self.test_button = QPushButton("Start test mode")
        self.test_button.setMinimumHeight(36)
        test.addWidget(test_title)
        test.addWidget(test_text)
        test.addSpacing(6)
        test.addWidget(self.gases_label)
        test.addStretch(1)
        test.addWidget(self.test_button)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        for card in (self.device_card, self.test_card):
            card.setFixedWidth(330)
            card.setMinimumHeight(210)
            cards.addWidget(card)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.hide()
        status_row = QHBoxLayout()
        status_row.addStretch(1)
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.cancel_button)
        status_row.addStretch(1)

        column = QVBoxLayout()
        column.addStretch(1)
        column.addWidget(logo)
        column.addWidget(title)
        column.addWidget(self.subtitle)
        column.addSpacing(18)
        column.addLayout(cards)
        column.addSpacing(12)
        column.addLayout(status_row)
        column.addStretch(2)
        outer = QHBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(column)
        outer.addStretch(1)

        self.refresh_button.clicked.connect(lambda: self.refresh_ports())
        self.connect_button.clicked.connect(lambda: self.connect_requested.emit(self.selected_port()))
        self.test_button.clicked.connect(self.test_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.set_idle()

    @staticmethod
    def _heading_font():
        font = QLabel().font()
        font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setBold(True)
        return font

    def apply_theme(self, theme):
        card = f"background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 8px;"
        self.device_card.setStyleSheet(f"#startCard {{ {card} border-top: 4px solid {theme.series[0]}; }}")
        self.test_card.setStyleSheet(f"#startCard {{ {card} border-top: 4px solid {th.SERIOUS}; }}")
        self.subtitle.setStyleSheet(f"color: {theme.text_secondary};")
        self.gases_label.setStyleSheet(f"color: {theme.text_secondary};")
        self.test_only_note.setStyleSheet(f"color: {theme.text_secondary};")

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
        if select and select != SIM_PORT and self.port_combo.findData(select) < 0:
            self.port_combo.insertItem(1, f"{select} (not found now)", select)
        index = self.port_combo.findData(select) if select else 0
        self.port_combo.setCurrentIndex(max(index, 0))
        self.gases_label.setText(simulated_gases())

    def selected_port(self):
        return self.port_combo.currentData()

    def set_busy(self, text):
        self.busy = True
        self._update_enabled()
        self.status_label.setText(text)
        self.cancel_button.show()

    def set_idle(self, message="", error=False):
        self.busy = False
        self._update_enabled()
        color = f"color: {th.CRITICAL};" if error else ""
        self.status_label.setStyleSheet(color)
        self.status_label.setText(message)
        self.cancel_button.hide()

    def _update_enabled(self):
        device_ok = not self.busy and not self.test_only
        for widget in (self.port_combo, self.refresh_button, self.connect_button):
            widget.setEnabled(device_ok)
        self.test_button.setEnabled(not self.busy)
        self.test_only_note.setVisible(self.test_only)
