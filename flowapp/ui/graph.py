"""Live graph: flow, valve % and mixture % panels on a shared time axis."""

from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme as th
from .history import SeriesBuffer
from .units import common_unit, decimals_for

WINDOWS = [("1 min", 60), ("5 min", 300), ("15 min", 900), ("60 min", 3600), ("All", None)]
MIXTURE_MIN_TOTAL = 0.01    # mixture % is blank while the total flow is below 1 % of the summed capacities


def swatch(color, text):
    return f'<span style="color:{color}">■</span> {text}'


class FlowGraph(QWidget):
    export_requested = Signal(str)      # "png" or "csv"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = th.LIGHT
        self.channels = []
        self.names = {}
        self.colors = {}
        self.buffer = None
        self.pct_mode = False
        self.follow = True
        self.window_s = 300
        self._dirty = False
        self._curves = {}           # (kind, address) -> (PlotItem, PlotDataItem)
        self._channel_checks = {}
        self._crosshair_x = None
        self._flow_label = None

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
        self.csv_button.setToolTip("Save all buffered data as CSV")
        self.png_button.clicked.connect(lambda: self.export_requested.emit("png"))
        self.csv_button.clicked.connect(lambda: self.export_requested.emit("csv"))
        controls.addWidget(QLabel("Window"))
        controls.addWidget(self.window_combo)
        controls.addWidget(self.live_button)
        controls.addWidget(self.png_button)
        controls.addWidget(self.csv_button)
        layout.addLayout(controls)

        self.readout = QLabel(" ")
        self.readout.setTextFormat(Qt.RichText)
        self.note = QLabel()
        self.note.hide()
        layout.addWidget(self.readout)
        layout.addWidget(self.note)

        self.view = pg.GraphicsLayoutWidget()
        self.flow_plot = self.view.addPlot(row=0, col=0, axisItems={"bottom": pg.DateAxisItem()})
        self.valve_plot = self.view.addPlot(row=1, col=0, axisItems={"bottom": pg.DateAxisItem()})
        self.mix_plot = self.view.addPlot(row=2, col=0, axisItems={"bottom": pg.DateAxisItem()})
        self.plots = [self.flow_plot, self.valve_plot, self.mix_plot]
        rows = self.view.ci.layout
        for row, stretch in enumerate((3, 1, 1)):
            rows.setRowStretchFactor(row, stretch)
        for plot in self.plots:
            plot.setClipToView(True)
            plot.setDownsampling(auto=True, mode="peak")
            plot.setMenuEnabled(False)
            plot.hideButtons()
            plot.getAxis("left").setWidth(60)
            vb = plot.getViewBox()
            vb.setMouseEnabled(x=True, y=False)
            vb.sigRangeChangedManually.connect(lambda *_: self.set_follow(False))
            if plot is not self.flow_plot:
                plot.setXLink(self.flow_plot)
        self.flow_plot.getViewBox().setAutoVisible(y=True)
        self.flow_plot.enableAutoRange(y=True)
        for plot, label in ((self.valve_plot, "Valve [%]"), (self.mix_plot, "Mixture [%]")):
            plot.setYRange(0, 100, padding=0.05)
            plot.setLabel("left", label)
        self.crosshair = [pg.InfiniteLine(angle=90, movable=False) for _ in self.plots]
        for plot, line in zip(self.plots, self.crosshair):
            plot.addItem(line, ignoreBounds=True)
            line.hide()
        self.view.scene().sigMouseMoved.connect(self._mouse_moved)
        layout.addWidget(self.view, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._redraw)
        self._timer.start(250)
        self.apply_theme(self.theme)
        self.set_panels(True, True)

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

    def clear(self):
        for plot, curve in self._curves.values():
            plot.removeItem(curve)
        self._curves = {}
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

    def _curve(self, kind, address):
        item = self._curves.get((kind, address))
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
        for line in self.crosshair:
            line.setPen(pg.mkPen(theme.text_secondary, width=1))
        self.note.setStyleSheet(f"color: {theme.text_secondary};")
        self._style_total()
        self._mark_dirty()

    def set_pct_mode(self, on):
        self.pct_mode = on
        self._mark_dirty()

    def set_panels(self, valve, mixture):
        self.valve_plot.setVisible(valve)
        self.mix_plot.setVisible(mixture)
        visible = [p for p in self.plots if p.isVisible()]
        for plot in self.plots:
            plot.getAxis("bottom").setStyle(showValues=plot is visible[-1])

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
        if not self._dirty or self.buffer is None or not self.isVisible():
            return
        self._dirty = False
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

        label = "Flow [% of full scale]" if pct else f"Flow [{unit}]"
        if label != self._flow_label:
            self._flow_label = label
            self.flow_plot.setLabel("left", label)
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
        if self.buffer is None or len(self.buffer) == 0:
            return
        parts = [datetime.fromtimestamp(x).strftime("%H:%M:%S")]
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
        self.readout.setText("&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts))

    # --- export -----------------------------------------------------------------------------

    def export_png(self, path):
        return self.view.grab().save(str(path))

    def export_csv(self, path):
        if self.buffer is None:
            raise RuntimeError("No data recorded yet.")
        units = {c.address: c.unit for c in self.channels}
        self.buffer.to_csv(path, self.names, units)

    def sample_count(self):
        return 0 if self.buffer is None else len(self.buffer)

    def latest_time(self):
        return None if self.buffer is None or len(self.buffer) == 0 else self.buffer.t[-1]


def history_samples(settings):
    return int(settings.history_minutes * 60 * settings.poll_hz)
