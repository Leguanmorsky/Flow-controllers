"""One card per instrument: live values, setpoint controls and a ramp."""

import math

from PySide6.QtCore import QRectF, Qt, QTime, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (QAbstractSlider, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QSlider, QTimeEdit, QToolButton, QVBoxLayout,
                               QWidget)

from ..core import dde
from . import theme as th
from .units import decimals_for, fmt, fmt_duration

SLIDER_STEPS = 1000


def dot(color, text):
    return f'<span style="color:{color}">●</span> {text}'


class FlowBar(QWidget):
    """Measured flow as a bar (0..100 % of full scale) with a tick at the setpoint."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(12)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.measure_pct = None
        self.setpoint_pct = None
        self.color = QColor("#2a78d6")

    def set_values(self, measure_pct, setpoint_pct):
        self.measure_pct, self.setpoint_pct = measure_pct, setpoint_pct
        self.update()

    def set_color(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 2.5, -0.5, -2.5)
        p.setPen(Qt.NoPen)
        p.setBrush(self.palette().color(QPalette.Midlight))
        p.drawRoundedRect(r, 3, 3)
        if self.measure_pct is not None:
            w = r.width() * min(max(self.measure_pct, 0.0), 100.0) / 100.0
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(r.left(), r.top(), w, r.height()), 3, 3)
        if self.setpoint_pct is not None:
            x = r.left() + r.width() * min(max(self.setpoint_pct, 0.0), 100.0) / 100.0
            p.setPen(self.palette().color(QPalette.WindowText))
            p.drawLine(int(x), 0, int(x), self.height())


class Spin(QDoubleSpinBox):
    """Spin box that ignores the mouse wheel unless focused (so scrolling the card list changes nothing)
    and reports Enter separately (the arrows only edit, Enter sends)."""
    returnPressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.returnPressed.emit()


class Slider(QSlider):
    """Slider that never reacts to the mouse wheel: scrolling over it must not change a flow."""

    def wheelEvent(self, event):
        event.ignore()


class Banner(QFrame):
    """Coloured message strip inside a card, with an optional button."""

    def __init__(self, background, foreground, button_text=None, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setStyleSheet(f"#banner {{ background: {background}; border-radius: 4px; }}"
                           f"QLabel {{ color: {foreground}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.button = QPushButton(button_text) if button_text else None
        if self.button:
            layout.addWidget(self.button)
        self.hide()

    def show_text(self, text):
        self.label.setText(text)
        self.setVisible(bool(text))


class ChannelCard(QFrame):
    setpoint_requested = Signal(int, float)             # address, value in capacity units
    ramp_requested = Signal(int, float, object, object)  # address, target, rate per min or None, duration s or None
    ramp_stop_requested = Signal(int)
    identify_requested = Signal(int)
    settings_requested = Signal(int)
    control_mode_requested = Signal(int)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.address = info.address
        self.capacity = info.capacity
        self.limit = info.capacity
        self.step = info.capacity / 100
        self.pct_mode = False
        self.color = "#2a78d6"
        self.theme = th.LIGHT
        self.device_setpoint = None
        self.ramp_active = False
        self.setObjectName("card")
        self._build()

    # --- layout -----------------------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 10, 8)
        root.setSpacing(4)

        header = QHBoxLayout()
        self.name_label = QLabel()
        font = self.name_label.font()
        font.setPointSizeF(font.pointSizeF() + 2)
        font.setBold(True)
        self.name_label.setFont(font)
        self.address_label = QLabel(f"({self.address})")
        self.status_label = QLabel()
        self.identify_button = QToolButton(text="Identify")
        self.identify_button.setToolTip("Blink the LEDs of this instrument so you can find it on the gas panel")
        self.settings_button = QToolButton(text="⚙")
        self.settings_button.setToolTip("Name, colour, max flow and step of this channel")
        header.addWidget(self.name_label)
        header.addWidget(self.address_label)
        header.addStretch(1)
        header.addWidget(self.status_label)
        header.addWidget(self.identify_button)
        header.addWidget(self.settings_button)
        root.addLayout(header)

        self.info_label = QLabel()
        root.addWidget(self.info_label)

        values = QHBoxLayout()
        self.measure_label = QLabel("–")
        font = QFont(self.measure_label.font())
        font.setPointSizeF(font.pointSizeF() * 1.9)
        font.setBold(True)
        self.measure_label.setFont(font)
        self.unit_label = QLabel()
        self.setpoint_label = QLabel()
        values.addWidget(self.measure_label, 0, Qt.AlignBottom)
        values.addWidget(self.unit_label, 0, Qt.AlignBottom)
        values.addStretch(1)
        values.addWidget(self.setpoint_label, 0, Qt.AlignBottom)
        root.addLayout(values)

        bar_row = QHBoxLayout()
        self.bar = FlowBar()
        self.pct_label = QLabel()
        self.pct_label.setMinimumWidth(48)
        self.pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.valve_label = QLabel()
        self.valve_label.setMinimumWidth(78)
        self.valve_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar_row.addWidget(self.bar, 1)
        bar_row.addWidget(self.pct_label)
        bar_row.addWidget(self.valve_label)
        root.addLayout(bar_row)

        self.error_banner = Banner(th.CRITICAL, "#ffffff")
        self.mode_banner = Banner(th.WARNING, "#0b0b0b", "Switch to PC control")
        self.deviation_banner = Banner(th.WARNING, "#0b0b0b")
        for banner in (self.error_banner, self.mode_banner, self.deviation_banner):
            root.addWidget(banner)

        sp_row = QHBoxLayout()
        sp_row.addWidget(QLabel("Setpoint"))
        self.spin = Spin()
        self.spin.setKeyboardTracking(False)
        self.spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_button = QPushButton("Set")
        self.set_button.setToolTip("Send the setpoint (or press Enter in the field)")
        self.zero_button = QPushButton("0")
        self.zero_button.setToolTip("Set this channel to 0")
        self.zero_button.setFixedWidth(36)
        sp_row.addWidget(self.spin, 1)
        sp_row.addWidget(self.set_button)
        sp_row.addWidget(self.zero_button)
        root.addLayout(sp_row)

        slider_row = QHBoxLayout()
        self.minus_button = QToolButton(text="−")
        self.plus_button = QToolButton(text="+")
        self.slider = Slider(Qt.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setPageStep(SLIDER_STEPS // 20)
        slider_row.addWidget(self.minus_button)
        slider_row.addWidget(self.slider, 1)
        slider_row.addWidget(self.plus_button)
        root.addLayout(slider_row)

        ramp_header = QHBoxLayout()
        self.ramp_toggle = QToolButton(text="Ramp")
        self.ramp_toggle.setCheckable(True)
        self.ramp_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.ramp_toggle.setArrowType(Qt.RightArrow)
        self.ramp_toggle.setAutoRaise(True)
        self.ramp_status = QLabel()
        ramp_header.addWidget(self.ramp_toggle)
        ramp_header.addWidget(self.ramp_status, 1)
        root.addLayout(ramp_header)

        self.ramp_panel = QWidget()
        grid = QGridLayout(self.ramp_panel)
        grid.setContentsMargins(0, 0, 0, 0)
        self.ramp_target = Spin()
        self.ramp_mode = QComboBox()
        self.ramp_mode.addItems(["rate", "duration"])
        self.ramp_rate = Spin()
        self.ramp_duration = QTimeEdit()
        self.ramp_duration.setDisplayFormat("H:mm:ss")
        self.ramp_duration.setTime(QTime(0, 5, 0))
        self.ramp_duration.hide()
        self.ramp_eta = QLabel()
        self.ramp_start = QPushButton("Start")
        self.ramp_stop = QPushButton("Stop")
        grid.addWidget(QLabel("to"), 0, 0)
        grid.addWidget(self.ramp_target, 0, 1, 1, 2)
        grid.addWidget(self.ramp_mode, 1, 0)
        grid.addWidget(self.ramp_rate, 1, 1, 1, 2)
        grid.addWidget(self.ramp_duration, 1, 1, 1, 2)
        grid.addWidget(self.ramp_eta, 2, 0, 1, 1)
        grid.addWidget(self.ramp_start, 2, 1)
        grid.addWidget(self.ramp_stop, 2, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        self.ramp_panel.hide()
        root.addWidget(self.ramp_panel)

        self.identify_button.clicked.connect(lambda: self.identify_requested.emit(self.address))
        self.settings_button.clicked.connect(lambda: self.settings_requested.emit(self.address))
        self.mode_banner.button.clicked.connect(lambda: self.control_mode_requested.emit(self.address))
        self.spin.returnPressed.connect(self._send_spin)
        self.set_button.clicked.connect(self._send_spin)
        self.zero_button.clicked.connect(lambda: self._send(0.0))
        self.minus_button.clicked.connect(lambda: self._step(-1))
        self.plus_button.clicked.connect(lambda: self._step(+1))
        self.slider.sliderMoved.connect(self._slider_preview)
        self.slider.sliderReleased.connect(self._slider_send)
        self.slider.actionTriggered.connect(self._slider_action)
        self.ramp_toggle.toggled.connect(self._toggle_ramp_panel)
        self.ramp_mode.currentIndexChanged.connect(self._ramp_mode_changed)
        self.ramp_target.valueChanged.connect(self._update_eta)
        self.ramp_rate.valueChanged.connect(self._update_eta)
        self.ramp_duration.timeChanged.connect(self._update_eta)
        self.ramp_start.clicked.connect(self._start_ramp)
        self.ramp_stop.clicked.connect(lambda: self.ramp_stop_requested.emit(self.address))
        self.ramp_stop.setEnabled(False)

    # --- configuration ----------------------------------------------------------------------

    def configure(self, name, color, limit, step):
        self.name_label.setText(name)
        self.color = color
        self.limit = limit
        self.step = step
        self.bar.set_color(color)
        palette = self.slider.palette()
        palette.setColor(QPalette.Highlight, QColor(color))
        self.slider.setPalette(palette)
        self._apply_style()
        self._apply_ranges()
        self._update_info(None)

    def set_pct_mode(self, on):
        self.pct_mode = on
        self._apply_ranges()

    def apply_theme(self, theme):
        self.theme = theme
        self._apply_style()

    def _apply_style(self):
        t = self.theme
        self.setStyleSheet(f"#card {{ background: {t.panel}; border: 1px solid {t.border}; "
                           f"border-left: 5px solid {self.color}; border-radius: 6px; }}")
        secondary = f"color: {t.text_secondary};"
        for label in (self.address_label, self.info_label, self.unit_label, self.ramp_status, self.ramp_eta):
            label.setStyleSheet(secondary)

    def _to_display(self, value):
        return value / self.capacity * 100 if self.pct_mode and self.capacity else value

    def _to_real(self, shown):
        return shown / 100 * self.capacity if self.pct_mode else shown

    def _apply_ranges(self):
        decimals = 2 if self.pct_mode else decimals_for(self.capacity)
        suffix = " %" if self.pct_mode else ""
        for spin, maximum in ((self.spin, self.limit), (self.ramp_target, self.limit)):
            spin.blockSignals(True)
            spin.setDecimals(decimals)
            spin.setRange(0.0, self._to_display(maximum))
            spin.setSingleStep(self._to_display(self.step))
            spin.setSuffix(suffix)
            spin.blockSignals(False)
        self.ramp_rate.setDecimals(decimals)
        self.ramp_rate.setRange(10 ** -decimals, self._to_display(self.capacity) * 60)
        self.ramp_rate.setSuffix(" /min")
        self.ramp_rate.setToolTip("How fast the setpoint changes, in "
                                  + ("% of full scale" if self.pct_mode else self.info.unit) + " per minute")
        if self.ramp_rate.value() <= 10 ** -decimals:
            self.ramp_rate.setValue(self._to_display(self.capacity / 10))
        self.unit_label.setText("%" if self.pct_mode else self.info.unit)
        self._sync_controls()

    def _update_info(self, temperature):
        parts = [self.info.fluid or "?", f"0–{self.capacity:g} {self.info.unit}"]
        if temperature is not None:
            parts.append(f"{temperature:.1f} °C")
        self.info_label.setText(" · ".join(parts))
        tip = [f"Serial {self.info.serial}", f"Type {self.info.device_type}"]
        if self.info.firmware:
            tip.append(f"Firmware {self.info.firmware}")
        if self.info.setpoint_slope:
            tip.append(f"Instrument setpoint slope {self.info.setpoint_slope} (ramps internally)")
        self.info_label.setToolTip("\n".join(tip))

    # --- live values ------------------------------------------------------------------------

    def update_state(self, state, ramp=None, ramp_remaining=None, deviation=None):
        decimals = 2 if self.pct_mode else decimals_for(self.capacity)
        if state.ok:
            self.device_setpoint = state.setpoint
            measure = state.measure_pct if self.pct_mode else state.measure
            setpoint = state.setpoint_pct if self.pct_mode else state.setpoint
            self.measure_label.setText(fmt(measure, decimals))
            self.setpoint_label.setText(f"SP {fmt(setpoint, decimals)}")
            self.bar.set_values(state.measure_pct, state.setpoint_pct)
            self.pct_label.setText(fmt(state.measure_pct, 0, " %"))
            self.valve_label.setText(f"valve {fmt(state.valve_pct, 0, ' %')}")
            self._update_info(state.temperature)
            self.error_banner.show_text("")
        else:
            self.measure_label.setText("–")
            self.setpoint_label.setText("SP –")
            self.bar.set_values(None, None)
            self.pct_label.setText("")
            self.valve_label.setText("valve –")
            self.error_banner.show_text(f"✖ No answer from instrument ({state.error})")

        mode = state.control_mode if state.control_mode is not None else self.info.control_mode
        if mode is not None and mode not in dde.BUS_SETPOINT_MODES:
            self.mode_banner.show_text(f"⚠ In “{dde.control_mode_name(mode)}” mode: ignores setpoints from the PC")
        else:
            self.mode_banner.show_text("")

        if deviation == "low":
            self.deviation_banner.show_text("⚠ Flow stays below setpoint (gas supply closed?)")
        elif deviation == "high":
            self.deviation_banner.show_text("⚠ Flow stays above setpoint")
        else:
            self.deviation_banner.show_text("")

        if not state.ok:
            self.status_label.setText(dot(th.CRITICAL, "No answer"))
        elif self.mode_banner.isVisible():
            self.status_label.setText(dot(th.WARNING, "Local mode"))
        elif deviation:
            self.status_label.setText(dot(th.WARNING, "Check flow"))
        else:
            self.status_label.setText(dot(th.GOOD, "OK"))

        self.set_ramp(ramp, ramp_remaining)
        self._sync_controls()
        self._update_eta()

    def set_ramp(self, ramp, remaining):
        self.ramp_active = ramp is not None
        self.ramp_stop.setEnabled(self.ramp_active)
        if ramp is None:
            self.ramp_status.setText("")
            return
        decimals = 2 if self.pct_mode else decimals_for(self.capacity)
        target = fmt(self._to_display(ramp.target), decimals, " %" if self.pct_mode else f" {self.info.unit}")
        self.ramp_status.setText(f"running → {target} · {fmt_duration(remaining)} left")

    def _sync_controls(self):
        """Shows the device setpoint in the spin box and slider unless the user is editing them."""
        if self.device_setpoint is None:
            return
        if not self.spin.hasFocus():
            self.spin.blockSignals(True)
            self.spin.setValue(self._to_display(self.device_setpoint))
            self.spin.blockSignals(False)
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(self._slider_pos(self.device_setpoint))
            self.slider.blockSignals(False)

    # --- user actions -----------------------------------------------------------------------

    def _send(self, value):
        self.setpoint_requested.emit(self.address, float(value))

    def _send_spin(self):
        self._send(self._to_real(self.spin.value()))
        self.spin.clearFocus()

    def _step(self, direction):
        current = self.device_setpoint if self.device_setpoint is not None else self._to_real(self.spin.value())
        self._send(min(max(current + direction * self.step, 0.0), self.limit))

    def _slider_pos(self, value):
        return round(min(max(value / self.limit, 0.0), 1.0) * SLIDER_STEPS) if self.limit > 0 else 0

    def _slider_value(self, pos):
        return pos / SLIDER_STEPS * self.limit

    def _slider_preview(self, pos):
        self.spin.blockSignals(True)
        self.spin.setValue(self._to_display(self._slider_value(pos)))
        self.spin.blockSignals(False)

    def _slider_send(self):
        self._send(self._slider_value(self.slider.value()))

    def _slider_action(self, action):
        # Clicks on the groove and keyboard steps move the slider without press/release.
        action = QAbstractSlider.SliderAction(action)
        moved_by_click_or_key = action not in (QAbstractSlider.SliderMove, QAbstractSlider.SliderNoAction)
        if moved_by_click_or_key and not self.slider.isSliderDown():
            pos = self.slider.sliderPosition()
            self._slider_preview(pos)
            self._send(self._slider_value(pos))

    def _toggle_ramp_panel(self, on):
        self.ramp_panel.setVisible(on)
        self.ramp_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    def _ramp_mode_changed(self, index):
        self.ramp_rate.setVisible(index == 0)
        self.ramp_duration.setVisible(index == 1)
        self._update_eta()

    def _duration_s(self):
        return QTime(0, 0).secsTo(self.ramp_duration.time())

    def _update_eta(self, *_):
        if self.ramp_mode.currentIndex() == 1:
            self.ramp_eta.setText(f"takes {fmt_duration(self._duration_s())}")
            return
        if self.device_setpoint is None:
            self.ramp_eta.setText("takes ?")
            return
        distance = abs(self._to_display(self.device_setpoint) - self.ramp_target.value())
        rate = self.ramp_rate.value()
        self.ramp_eta.setText(f"takes {fmt_duration(distance / rate * 60 if rate > 0 else math.inf)}")

    def _start_ramp(self):
        target = self._to_real(self.ramp_target.value())
        if self.ramp_mode.currentIndex() == 0:
            self.ramp_requested.emit(self.address, target, self._to_real(self.ramp_rate.value()), None)
        else:
            self.ramp_requested.emit(self.address, target, None, float(self._duration_s()))
