"""Live graph: the flow panel plus two switchable lower panels (pressure, mixture %, valve %) on one time axis.

Each panel has a header with its title and unit and its own background, so the panels are easy to tell
apart; the pressure panel uses the gauge colours (not the MFC colours) on a log axis.
"""

import math
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.vacuum import GAUGES
from . import theme as th
from .history import PressureBuffer, SeriesBuffer
from .units import common_unit, decimals_for

WINDOWS = [("1 min", 60), ("5 min", 300), ("15 min", 900), ("60 min", 3600), ("All", None)]
MIXTURE_MIN_TOTAL = 0.002   # mixture % is blank while the total flow is below 0.2 % of the summed capacities
PANELS = {"pressure": "Chamber pressure", "mixture": "Mixture", "valve": "Valve drive", "off": "Off"}
PANEL_UNITS = {"pressure": "Pa, log scale", "mixture": "% of the total flow", "valve": "% of the MFC valve signal"}
DEFAULT_SLOTS = ("pressure", "mixture")


class PressureAxis(pg.AxisItem):
    """Log axis labelled 1e-5, 1e-4, … (only whole decades get a label)."""

    def logTickStrings(self, values, scale, spacing):
        return [f"1e{int(round(v))}" if abs(v - round(v)) < 1e-6 else "" for v in values]


def swatch(color, text):
    return f'<span style="color:{color}">■</span> {text}'


def fmt_pa(value):
    return "–" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:.2e}"


class FlowGraph(QWidget):
    export_requested = Signal(str)      # "png" or "csv"
    slots_changed = Signal(object)      # tuple of the two lower panel kinds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = th.LIGHT
        self.channels = []
        self.names = {}
        self.colors = {}
        self.buffer = None
        self.pressures = None
        self.p_max = None
        self.pct_mode = False
        self.follow = True
        self.window_s = 300
        self.slots = list(DEFAULT_SLOTS)
        self._dirty = False
        self._curves = {}           # (kind, address or gauge key) -> (PlotItem, PlotDataItem)
        self._channel_checks = {}
        self._crosshair_x = None
        self._flow_unit = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        controls = QHBoxLayout()
        self._channel_row = QHBoxLayout()
        controls.addLayout(self._channel_row)
        controls.addSpacing(12)
        self.measure_check = QCheckBox("Measured")
        self.setpoint_check = QCheckBox("Setpoint (dashed)")
        self.total_check = QCheckBox("Total")
        for check in (self.measure_check, self.setpoint_check, self.total_check):
            check.setChecked(True)
            check.toggled.connect(self._mark_dirty)
            controls.addWidget(check)
        controls.addStretch(1)
        self.window_combo = QComboBox()
        for label, seconds in WINDOWS:
            self.window_combo.addItem(label, seconds)
        self.window_combo.setCurrentIndex(1)
        self.window_combo.currentIndexChanged.connect(self._window_changed)
        self.live_button = QPushButton("Pause")
        self.live_button.setToolTip("Pause: stop following new data. Zooming or panning with the mouse also pauses.")
        self.live_button.clicked.connect(lambda: self.set_follow(not self.follow))
        self.png_button = QPushButton("PNG…")
        self.png_button.setToolTip("Save the graph as an image")
        self.csv_button = QPushButton("CSV…")
        self.csv_button.setToolTip("Save all buffered data as CSV (flows and pressures)")
        self.png_button.clicked.connect(lambda: self.export_requested.emit("png"))
        self.csv_button.clicked.connect(lambda: self.export_requested.emit("csv"))
        controls.addWidget(QLabel("Window"))
        controls.addWidget(self.window_combo)
        controls.addWidget(self.live_button)
        controls.addWidget(self.png_button)
        controls.addWidget(self.csv_button)
        layout.addLayout(controls)

        panels = QHBoxLayout()
        panels.addWidget(QLabel("Lower panels"))
        self.slot_combos = []
        for index in range(2):
            combo = QComboBox()
            for kind, label in PANELS.items():
                combo.addItem(label, kind)
            combo.setCurrentIndex(combo.findData(self.slots[index]))
            combo.currentIndexChanged.connect(self._slot_combo_changed)
            combo.setToolTip(f"What the {'upper' if index == 0 else 'lower'} of the two small panels shows")
            self.slot_combos.append(combo)
            panels.addWidget(combo)
        panels.addSpacing(16)
        self.gauge_label = QLabel("Gauges")
        panels.addWidget(self.gauge_label)
        self.gauge_checks = {}
        for gauge in GAUGES:
            check = QCheckBox(gauge.short)
            check.setToolTip(gauge.label)
            check.toggled.connect(self._mark_dirty)
            self.gauge_checks[gauge.key] = check
            panels.addWidget(check)
        panels.addStretch(1)
        layout.addLayout(panels)

        self.readout = QLabel(" ")
        self.readout.setTextFormat(Qt.RichText)
        self.note = QLabel()
        self.note.hide()
        layout.addWidget(self.readout)
        layout.addWidget(self.note)

        self.view = pg.GraphicsLayoutWidget()
        self.view.ci.layout.setVerticalSpacing(10)
        self.flow_plot = pg.PlotItem(axisItems={"bottom": pg.DateAxisItem()})
        self.pressure_plot = pg.PlotItem(axisItems={"bottom": pg.DateAxisItem(), "left": PressureAxis("left")})
        self.valve_plot = pg.PlotItem(axisItems={"bottom": pg.DateAxisItem()})
        self.mix_plot = pg.PlotItem(axisItems={"bottom": pg.DateAxisItem()})
        self.plots = [self.flow_plot, self.pressure_plot, self.valve_plot, self.mix_plot]
        self.panel_plots = {"pressure": self.pressure_plot, "valve": self.valve_plot, "mixture": self.mix_plot}
        for plot in self.plots:
            plot.setClipToView(True)
            plot.setDownsampling(auto=True, mode="peak")
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.getAxis("left").setWidth(64)
            plot.titleLabel.setAttr("justify", "left")
            vb = plot.getViewBox()
            vb.setMouseEnabled(x=True, y=False)
            vb.sigRangeChangedManually.connect(lambda *_: self.set_follow(False))
            if plot is not self.flow_plot:
                plot.setXLink(self.flow_plot)
        self.flow_plot.getViewBox().setAutoVisible(y=True)
        self.flow_plot.enableAutoRange(y=True)
        for plot in (self.valve_plot, self.mix_plot):
            plot.setYRange(0, 100, padding=0.05)
        self.pressure_plot.setLogMode(x=False, y=True)
        self.pressure_plot.enableAutoRange(y=True)
        self.pressure_plot.getViewBox().setAutoVisible(y=True)
        self.p_max_line = pg.InfiniteLine(angle=0, movable=False,
                                          label="p max", labelOpts={"position": 0.03, "anchors": [(0, 1), (0, 1)]})
        self.pressure_plot.addItem(self.p_max_line, ignoreBounds=True)
        self.p_max_line.hide()
        self.crosshair = [pg.InfiniteLine(angle=90, movable=False) for _ in self.plots]
        for plot, line in zip(self.plots, self.crosshair):
            plot.addItem(line, ignoreBounds=True)
            line.hide()
        self.view.scene().sigMouseMoved.connect(self._mouse_moved)
        layout.addWidget(self.view, 1)

        for gauge in GAUGES:
            self._curves["pressure", gauge.key] = (self.pressure_plot, self.pressure_plot.plot([], []))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._redraw)
        self._timer.start(250)
        self.apply_theme(self.theme)
        self.set_slots(self.slots)
        self.set_gauges(["chamber_frg", "chamber_img", "chamber_hfig"])

    # --- setup ------------------------------------------------------------------------------

    def set_channels(self, channels, names, colors, history_samples):
        """Starts a new recording for `channels` (previous data is dropped)."""
        self.clear()
        self.channels = list(channels)
        self.buffer = SeriesBuffer([c.address for c in channels], history_samples)
        for c in self.channels:
            check = QCheckBox()
            check.setChecked(True)
            check.toggled.connect(self._mark_dirty)
            self._channel_checks[c.address] = check
            self._channel_row.addWidget(check)
            for kind, plot in (("measure", self.flow_plot), ("setpoint", self.flow_plot),
                               ("valve", self.valve_plot), ("mix", self.mix_plot)):
                self._curves[kind, c.address] = (plot, plot.plot([], []))
        self._curves["total", None] = (self.flow_plot, self.flow_plot.plot([], []))
        self.set_names_colors(names, colors)
        self.set_follow(True)

    def start_pressures(self, history_samples, p_max=None):
        """Starts recording pressures (a vacuum card is being read)."""
        self.pressures = PressureBuffer([g.key for g in GAUGES], history_samples)
        self.p_max = p_max
        if p_max:
            self.p_max_line.setPos(math.log10(p_max))
        self.p_max_line.setVisible(bool(p_max))
        self._mark_dirty()

    def stop_pressures(self):
        self.pressures = None
        self.p_max_line.hide()
        for gauge in GAUGES:
            self._curve("pressure", gauge.key).hide()
        self._mark_dirty()

    def clear(self):
        for key, (plot, curve) in list(self._curves.items()):
            if key[0] != "pressure":
                plot.removeItem(curve)
                del self._curves[key]
        for check in self._channel_checks.values():
            self._channel_row.removeWidget(check)
            check.deleteLater()
        self._channel_checks = {}
        self.channels = []
        self.buffer = None
        self.readout.setText(" ")

    def set_names_colors(self, names, colors):
        self.names, self.colors = dict(names), dict(colors)
        for c in self.channels:
            a = c.address
            color = colors[a]
            self._channel_checks[a].setText(names[a])
            self._channel_checks[a].setStyleSheet(
                f"QCheckBox::indicator:checked {{ background: {color}; border: 1px solid {color}; "
                f"border-radius: 2px; }}")
            self._curve("measure", a).setPen(pg.mkPen(color, width=2))
            self._curve("setpoint", a).setPen(pg.mkPen(color, width=1.5, style=Qt.DashLine))
            self._curve("valve", a).setPen(pg.mkPen(color, width=2))
            self._curve("mix", a).setPen(pg.mkPen(color, width=2))
        self._style_total()
        self._mark_dirty()

    def set_gauges(self, keys):
        for key, check in self.gauge_checks.items():
            check.setChecked(key in keys)

    def selected_gauges(self):
        return [key for key, check in self.gauge_checks.items() if check.isChecked()]

    def _curve(self, kind, key):
        item = self._curves.get((kind, key))
        return item[1] if item else None

    def _style_total(self):
        total = self._curve("total", None)
        if total is not None:
            total.setPen(pg.mkPen(self.theme.text_secondary, width=3))

    def apply_theme(self, theme):
        self.theme = theme
        self.view.setBackground(theme.surface)
        for plot in self.plots:
            for name in ("left", "bottom"):
                axis = plot.getAxis(name)
                axis.setPen(pg.mkPen(theme.border))
                axis.setTextPen(pg.mkPen(theme.text_secondary))
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.getViewBox().setBackgroundColor(theme.surface if plot is self.flow_plot else theme.tint)
        for line in self.crosshair:
            line.setPen(pg.mkPen(theme.text_secondary, width=1))
        self.p_max_line.setPen(pg.mkPen(th.CRITICAL, width=1.5, style=Qt.DashLine))
        self.p_max_line.label.setColor(th.CRITICAL)
        for gauge in GAUGES:
            color = theme.gauge_color(gauge.key)
            self._curve("pressure", gauge.key).setPen(pg.mkPen(color, width=2))
            self.gauge_checks[gauge.key].setStyleSheet(
                f"QCheckBox {{ color: {color}; font-weight: bold; }} QCheckBox::indicator {{ width: 12px; "
                f"height: 12px; border: 1px solid {color}; border-radius: 2px; }} "
                f"QCheckBox::indicator:checked {{ background: {color}; }}")
        self.note.setStyleSheet(f"color: {theme.text_secondary};")
        self._style_total()
        self._update_titles()
        self._mark_dirty()

    def _title(self, plot, title, unit):
        plot.setTitle(f"<b>{title.upper()}</b>&nbsp;&nbsp;<span style='color:{self.theme.text_secondary}'>"
                      f"{unit}</span>", color=self.theme.text, size="9pt")
        plot.layout.setRowFixedHeight(0, 20)

    def _update_titles(self):
        self._title(self.flow_plot, "Gas flow", self._flow_unit or "")
        for kind, plot in self.panel_plots.items():
            self._title(plot, PANELS[kind], PANEL_UNITS[kind])

    def set_pct_mode(self, on):
        self.pct_mode = on
        self._mark_dirty()

    def set_slots(self, kinds):
        """Shows the flow panel plus the chosen lower panels ("pressure", "mixture", "valve" or "off")."""
        kinds = [k if k in PANELS else "off" for k in list(kinds)[:2]] + ["off"] * (2 - len(list(kinds)[:2]))
        self.slots = kinds
        for combo, kind in zip(self.slot_combos, kinds):
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(kind))
            combo.blockSignals(False)
        layout = self.view.ci
        for plot in self.plots:
            if plot in layout.items:
                layout.removeItem(plot)
        shown = [self.flow_plot] + [self.panel_plots[k] for k in dict.fromkeys(kinds) if k != "off"]
        for row, plot in enumerate(shown):
            layout.addItem(plot, row=row, col=0)
            layout.layout.setRowStretchFactor(row, 3 if plot is self.flow_plot else 2)
        for plot in self.plots:
            plot.setVisible(plot in shown)
            plot.getAxis("bottom").setStyle(showValues=plot is shown[-1])
        pressure_on = "pressure" in kinds
        self.gauge_label.setVisible(pressure_on)
        for check in self.gauge_checks.values():
            check.setVisible(pressure_on)
        self._mark_dirty()

    def _slot_combo_changed(self):
        self.set_slots([combo.currentData() for combo in self.slot_combos])
        self.slots_changed.emit(tuple(self.slots))

    def set_follow(self, on):
        self.follow = on
        self.live_button.setText("Pause" if on else "Live")
        self.live_button.setToolTip("Stop following new data" if on else "Follow the newest data again")
        self._mark_dirty()

    def _window_changed(self):
        self.window_s = self.window_combo.currentData()
        self.set_follow(True)

    # --- data -------------------------------------------------------------------------------

    def append(self, states):
        if self.buffer is not None and states:
            self.buffer.append(states[0].t, states)
            self._dirty = True

    def append_pressures(self, state):
        if self.pressures is not None and state is not None:
            self.pressures.append(state)
            self._dirty = True

    def _mark_dirty(self, *_):
        self._dirty = True

    def _flows(self):
        """address -> measured / setpoint arrays in the displayed unit, plus the shared real unit (or None)."""
        unit = common_unit(self.channels)
        pct = self.pct_mode or unit is None
        data = {}
        for c in self.channels:
            m = self.buffer.series(c.address, "measure")
            s = self.buffer.series(c.address, "setpoint")
            if pct:
                m, s = m / c.capacity * 100, s / c.capacity * 100
            data[c.address] = (m, s)
        return data, unit, pct

    def _redraw(self):
        if not self._dirty or not self.isVisible():
            return
        self._dirty = False
        self._redraw_pressures()
        if self.buffer is None:
            return
        t = self.buffer.t
        flows, unit, pct = self._flows()
        show_measure, show_setpoint = self.measure_check.isChecked(), self.setpoint_check.isChecked()
        measured_real = []
        for c in self.channels:
            a = c.address
            on = self._channel_checks[a].isChecked()
            m, s = flows[a]
            self._set_curve(("measure", a), t, m, on and show_measure)
            self._set_curve(("setpoint", a), t, s, on and show_setpoint)
            self._set_curve(("valve", a), t, self.buffer.series(a, "valve"), on)
            measured_real.append(self.buffer.series(a, "measure"))

        notes = []
        if unit is None:
            notes.append("The instruments use different units: flows are shown in % of full scale; "
                         "total and mixture are hidden.")
        total = None
        if unit is not None and measured_real:
            stack = np.vstack(measured_real)
            all_nan = np.all(np.isnan(stack), axis=0)
            total = np.where(all_nan, np.nan, np.nansum(stack, axis=0))
        self._set_curve(("total", None), t, total, total is not None and not pct and self.total_check.isChecked())
        if total is not None and pct and self.total_check.isChecked():
            notes.append("Total flow is shown in real units only.")

        if total is not None:
            minimum = MIXTURE_MIN_TOTAL * sum(c.capacity for c in self.channels)
            with np.errstate(invalid="ignore", divide="ignore"):
                safe_total = np.where(total >= minimum, total, np.nan)
                for c, m in zip(self.channels, measured_real):
                    self._set_curve(("mix", c.address), t, m / safe_total * 100,
                                    self._channel_checks[c.address].isChecked())
        else:
            for c in self.channels:
                self._set_curve(("mix", c.address), t, None, False)

        flow_unit = "% of full scale" if pct else unit
        if flow_unit != self._flow_unit:
            self._flow_unit = flow_unit
            self._update_titles()
        if self.pressures is None and "pressure" in self.slots:
            notes.append("No chamber pressures: no vacuum card is read in this session.")
        self.note.setText(" ".join(notes))
        self.note.setVisible(bool(notes))

        if self.follow and len(t):
            if self.window_s is None:
                start, end = t[0], max(t[-1], t[0] + 1.0)
            else:   # a fixed-width window; new data starts at the left until the window is full
                start = max(t[0], t[-1] - self.window_s)
                end = start + self.window_s
            self.flow_plot.setXRange(start, end, padding=0)
        if self._crosshair_x is not None:
            self._update_readout(self._crosshair_x)

    def _redraw_pressures(self):
        if self.pressures is None:
            return
        t = self.pressures.t
        selected = set(self.selected_gauges())
        for gauge in GAUGES:
            y = self.pressures.series(gauge.key)
            self._set_curve(("pressure", gauge.key), t, y, gauge.key in selected and not np.all(np.isnan(y)))

    def _set_curve(self, key, t, y, visible):
        curve = self._curve(*key)
        if curve is None:
            return
        if visible and y is not None and len(t):
            curve.setData(t, y, connect="finite")
            curve.show()
        else:
            curve.hide()

    # --- crosshair --------------------------------------------------------------------------

    def _mouse_moved(self, pos):
        for plot in self.plots:
            if plot.isVisible() and plot.sceneBoundingRect().contains(pos):
                x = plot.getViewBox().mapSceneToView(pos).x()
                self._crosshair_x = x
                for line in self.crosshair:
                    line.setPos(x)
                    line.show()
                self._update_readout(x)
                return
        self._crosshair_x = None
        for line in self.crosshair:
            line.hide()
        self.readout.setText(" ")

    def _update_readout(self, x):
        parts = [datetime.fromtimestamp(x).strftime("%H:%M:%S")]
        if self.buffer is not None and len(self.buffer):
            for c in self.channels:
                a = c.address
                if not self._channel_checks[a].isChecked():
                    continue
                d = 1 if self.pct_mode else decimals_for(c.capacity)
                measure = self.buffer.value_at(a, "measure", x)
                setpoint = self.buffer.value_at(a, "setpoint", x)
                valve = self.buffer.value_at(a, "valve", x)
                if self.pct_mode:
                    measure, setpoint, unit = measure / c.capacity * 100, setpoint / c.capacity * 100, "%"
                else:
                    unit = c.unit
                text = (f"{self.names.get(a, a)} {measure:.{d}f} / {setpoint:.{d}f} {unit}, valve {valve:.0f} %"
                        if not np.isnan(measure) else f"{self.names.get(a, a)} no data")
                parts.append(swatch(self.colors.get(a, "#888"), text))
        if self.pressures is not None and "pressure" in self.slots:
            for key in self.selected_gauges():
                gauge = next(g for g in GAUGES if g.key == key)
                parts.append(swatch(self.theme.gauge_color(key),
                                    f"{gauge.short} {fmt_pa(self.pressures.value_at(key, x))} Pa"))
        self.readout.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts))

    # --- export -----------------------------------------------------------------------------

    def export_png(self, path):
        return self.view.grab().save(str(path))

    def export_csv(self, path):
        if self.buffer is None:
            raise RuntimeError("No data recorded yet.")
        units = {c.address: c.unit for c in self.channels}
        extra = []
        if self.pressures is not None:
            extra = [(f"{g.label} [Pa]", self.pressures.aligned(g.key, self.buffer.t)) for g in GAUGES]
        self.buffer.to_csv(path, self.names, units, extra)

    def sample_count(self):
        return 0 if self.buffer is None else len(self.buffer)

    def latest_time(self):
        return None if self.buffer is None or len(self.buffer) == 0 else self.buffer.t[-1]


def history_samples(settings):
    return int(settings.history_minutes * 60 * settings.poll_hz)
