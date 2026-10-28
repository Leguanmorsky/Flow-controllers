"""Small vacuum widgets shared by the Flows and Vacuum tabs."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core.vacuum import GAUGE_BY_KEY
from . import theme as th

STRIP_GAUGES = ("chamber_frg", "chamber_img", "chamber_hfig", "loadlock_frg")
LEVEL_COLORS = {"good": th.GOOD, "warning": th.WARNING, "critical": th.CRITICAL}


def fmt_pa(value):
    return "–" if value is None else f"{value:.2e}"


class PressureStrip(QFrame):
    """Live line: card status · main gauges · whether gas is allowed (and why not)."""
    acknowledge_requested = Signal()

    def __init__(self, gauges=STRIP_GAUGES, parent=None):
        super().__init__(parent)
        self.setObjectName("pressureStrip")
        self.theme = th.LIGHT
        self.gauges = list(gauges)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(16)
        self.card_label = QLabel()
        self.card_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.card_label)
        self.values = {}
        for key in self.gauges:
            box = QVBoxLayout()
            box.setSpacing(0)
            name = QLabel(GAUGE_BY_KEY[key].label)
            value = QLabel("–")
            value.setTextFormat(Qt.RichText)
            font = value.font()
            font.setPointSizeF(font.pointSizeF() * 1.35)
            font.setBold(True)
            value.setFont(font)
            box.addWidget(name)
            box.addWidget(value)
            layout.addLayout(box)
            self.values[key] = (name, value)
        layout.addStretch(1)
        self.gas_label = QLabel()
        self.gas_label.setTextFormat(Qt.RichText)
        self.gas_label.setWordWrap(True)
        self.gas_label.setMaximumWidth(460)
        layout.addWidget(self.gas_label)
        self.ack_button = QPushButton("Acknowledge trip")
        self.ack_button.setToolTip("The chamber pressure went above p max and every flow was set to 0. "
                                   "Acknowledge to allow gas again.")
        self.ack_button.clicked.connect(self.acknowledge_requested)
        self.ack_button.hide()
        layout.addWidget(self.ack_button)
        self.set_card(None, "none")

    def apply_theme(self, theme):
        self.theme = theme
        self.setStyleSheet(f"#pressureStrip {{ background: {theme.panel}; border: 1px solid {theme.border}; "
                           f"border-radius: 6px; }}")
        for key, (name, value) in self.values.items():
            name.setStyleSheet(f"color: {theme.text_secondary};")
            value.setStyleSheet(f"color: {theme.gauge_color(key)};")

    def set_card(self, state, mode):
        if mode == "none":
            dot, text = th.WARNING, "No vacuum card"
        elif state is None:
            dot, text = th.WARNING, "Vacuum card: connecting…"
        elif not state.ok:
            dot, text = th.CRITICAL, f"Vacuum card: no data for {state.age_s:.0f} s"
        else:
            dot, text = (th.SERIOUS, "Simulated vacuum card") if mode == "sim" else (th.GOOD, "Vacuum card")
        self.card_label.setText(f'<span style="color:{dot}">●</span> {text}')
        for key, (_, value) in self.values.items():
            p = state.pressures.get(key) if state is not None and state.ok else None
            value.setText(f"{fmt_pa(p)} <span style='font-weight:normal; font-size:small'>Pa</span>"
                          if p is not None else "–")

    def set_gas(self, status):
        if status is None:
            self.gas_label.setText("")
            self.ack_button.hide()
            return
        color = LEVEL_COLORS.get(status.level, th.WARNING)
        self.gas_label.setText(f'<span style="color:{color}">●</span> {status.reason}')
        self.ack_button.setVisible(status.rule == "trip")
