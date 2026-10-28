"""Vacuum tab: live diagram of the UHV SEM vacuum system with valve control, pressures and Advanced commands.

The layout follows the card's own web page (docs/card_webpage/indexsvg.html) so it looks familiar, and adds:
chambers tinted by pressure, every gauge with its live value, the MFC gas inlet with the live flows, the
pumping path highlighted, valves blocked by an interlock drawn hatched with the reason in the tooltip.
This widget only shows and asks; the main window confirms and sends (through CardBridge).
"""

import json
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFrame, QGraphicsEllipseItem, QGraphicsItem,
                               QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget)

from ..core.safety import RULES
from ..core.vacuum import GAUGE_BY_KEY, GAUGES, VALVE_BY_NAME, VALVES, interlock_reason
from . import theme as th
from .graph import PressureAxis
from .vacuum_widgets import LEVEL_COLORS, fmt_pa

# --- topology, in the coordinates of the web page's drawing -------------------------------------------

CHAMBERS = {    # name: (shape, geometry, label)
    "main": ("circle", (155, 269, 51), "MAIN\nchamber"),
    "prep": ("circle", (279, 143, 37), "PREP"),
    "carousel": ("rect", (258, 247, 48, 44), "Carousel"),
    "loadlock": ("rect", (357, 249, 78, 41), "Load lock"),
    "airlock": ("rect", (387, 110, 16, 105), ""),
    "column": ("rect", (141, 150, 28, 66), ""),
    "gun": ("circle", (155, 136, 15), "FEG"),
}
PIPES = [   # (x1, y1, x2, y2, width) high-vacuum tubes
    (186, 240, 268, 158, 18), (200, 269, 360, 269, 22), (60, 189, 132, 258, 20), (216, 80, 266, 130, 10),
    (395, 215, 395, 250, 12), (395, 290, 395, 330, 10), (155, 216, 155, 218, 26),
]
LINES = [   # thin fore-vacuum / vent lines (polylines)
    [(203, 66), (170, 33), (170, 12), (503, 12), (503, 166), (522, 166)],
    [(395, 360), (395, 402), (503, 402), (503, 170)],
    [(403, 168), (503, 168)],
    [(403, 140), (440, 140)], [(240, 60), (272, 60)], [(406, 346), (452, 346)],
]
PUMPS = {   # name: (x, y, r, label)
    "tmp1": (216, 80, 18, "TMP1"), "tmp2": (395, 346, 16, "TMP2"), "ion_main": (50, 173, 17, "Ion"),
    "ion_carousel": (282, 220, 14, "Ion"), "fore": (544, 168, 18, "Fore"),
}
N2 = [(282, 60), (450, 140), (462, 346)]
VALVE_POS = {   # name: (x, y, pipe angle in degrees)
    "FV1": (186, 49, 45), "VV1": (252, 60, 0), "V04": (241, 105, 45), "V05": (422, 140, 0), "V06": (452, 168, 0),
    "V09": (430, 346, 0), "V10": (395, 380, 90), "V13": (395, 312, 90), "V14": (395, 231, 90),
    "V15": (334, 269, 0), "V16": (229, 269, 0), "V17": (227, 199, -45), "V19": (88, 216, 45),
}
VOLUME_POINTS = {"main": (155, 269), "prep": (279, 143), "carousel": (282, 269), "loadlock": (396, 269),
                 "airlock": (395, 160), "tmp1": (216, 80), "tmp2": (395, 346), "fore": (170, 20),
                 "ionpump": (50, 173), "n2": (282, 60)}
GAUGE_POS = {   # gauge key: (gauge x, y, tag x, y)
    "chamber_frg": (154, 309, 122, 334), "chamber_img": (106, 236, 2, 252), "chamber_hfig": (196, 300, 202, 314),
    "loadlock_frg": (422, 280, 440, 300), "gun": (140, 128, 2, 108), "column": (141, 180, 2, 124),
}
VENTED_BY = {"airlock": [("V05",)], "prep": [("VV1", "V04")], "loadlock": [("V09", "V13")]}   # vent valves into a part
ATMOSPHERE_PA = 1.0e5
INLET = (10, 350, 117, 306)     # gas inlet arrow into the main chamber


def pressure_color(p):
    """Log colour scale: UHV blue -> high vacuum teal -> rough amber -> atmosphere red."""
    if p is None:
        return QColor(150, 150, 150, 60)
    stops = [(-9, (42, 120, 214)), (-5, (40, 160, 170)), (-2, (240, 180, 40)), (1, (236, 120, 70)),
             (5, (208, 59, 59))]
    x = min(max(math.log10(p), stops[0][0]), stops[-1][0])
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x <= x1:
            f = (x - x0) / (x1 - x0)
            return QColor(*(round(a + (b - a) * f) for a, b in zip(c0, c1)), 95)
    return QColor(*stops[-1][1], 95)


class ValveItem(QGraphicsPathItem):
    """Bow-tie valve symbol; clicking reports the valve name."""

    def __init__(self, name, x, y, angle, on_click):
        path = QPainterPath()
        w, h = 11, 7
        path.addPolygon(QPolygonF([QPointF(-w, -h), QPointF(0, 0), QPointF(-w, h), QPointF(-w, -h)]))
        path.addPolygon(QPolygonF([QPointF(w, -h), QPointF(0, 0), QPointF(w, h), QPointF(w, -h)]))
        super().__init__(path)
        self.name = name
        self.on_click = on_click
        self.setPos(x, y)
        self.setRotation(angle)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(5)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_click(self.name)
        event.accept()

    def hoverEnterEvent(self, event):
        self.setScale(1.25)

    def hoverLeaveEvent(self, event):
        self.setScale(1.0)


class DiagramView(QGraphicsView):
    valve_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setScene(QGraphicsScene(self))
        self.setMinimumSize(420, 300)
        self.setFrameShape(QFrame.NoFrame)
        self.theme = th.LIGHT
        self.chambers = {}
        self.valves = {}
        self.valve_labels = {}
        self.gauge_tags = {}
        self.gauge_dots = {}
        self.path_items = []
        self._build()

    def _text(self, text, x, y, size=8, bold=False, center=False):
        item = QGraphicsSimpleTextItem(text)
        font = QFont()
        font.setPointSizeF(size)
        font.setBold(bold)
        item.setFont(font)
        rect = item.boundingRect()
        item.setPos(x - rect.width() / 2 if center else x, y - rect.height() / 2 if center else y)
        item.setZValue(6)
        self.scene().addItem(item)
        return item

    def _build(self):
        scene = self.scene()
        self.pipes = []
        for x1, y1, x2, y2, width in PIPES:
            path = QPainterPath(QPointF(x1, y1))
            path.lineTo(x2, y2)
            item = scene.addPath(path)
            item.setData(0, width)
            item.setZValue(0)
            self.pipes.append(item)
        self.lines = []
        for points in LINES:
            path = QPainterPath(QPointF(*points[0]))
            for p in points[1:]:
                path.lineTo(*p)
            item = scene.addPath(path)
            item.setZValue(0)
            self.lines.append(item)
        for name, (shape, geo, label) in CHAMBERS.items():
            if shape == "circle":
                x, y, r = geo
                item = QGraphicsEllipseItem(x - r, y - r, 2 * r, 2 * r)
                cx, cy = x, y
            else:
                x, y, w, h = geo
                item = QGraphicsRectItem(x, y, w, h)
                cx, cy = x + w / 2, y + h / 2
            item.setZValue(2)
            scene.addItem(item)
            self.chambers[name] = item
            if label:
                self._text(label, cx, cy, 8 if name != "main" else 9, bold=True, center=True)
        self._text("Air lock", 410, 186, 7)
        self._text("Column", 120, 182, 7).setRotation(-90)
        self.pumps = {}
        for name, (x, y, r, label) in PUMPS.items():
            item = QGraphicsEllipseItem(x - r, y - r, 2 * r, 2 * r)
            item.setZValue(3)
            scene.addItem(item)
            self.pumps[name] = item
            self._text(label, x, y, 7, bold=True, center=True)
        self.n2 = [self._text("N₂", x, y, 8, bold=True, center=True) for x, y in N2]
        for key, (gx, gy, tx, ty) in GAUGE_POS.items():
            dot = QGraphicsEllipseItem(gx - 5, gy - 5, 10, 10)
            dot.setZValue(4)
            scene.addItem(dot)
            self.gauge_dots[key] = dot
            tag = self._text(f"{GAUGE_BY_KEY[key].short} –", tx, ty, 8, bold=True)
            self.gauge_tags[key] = tag
        x1, y1, x2, y2 = INLET
        path = QPainterPath(QPointF(x1, y1))
        path.lineTo(x2, y2)
        self.inlet = scene.addPath(path)
        self.inlet.setZValue(1)
        head = QPolygonF([QPointF(x2, y2), QPointF(x2 - 11, y2 - 2), QPointF(x2 - 8, y2 + 8)])
        self.inlet_head = scene.addPolygon(head)
        self.inlet_label = self._text("Gas inlet (manual valve)", 2, 356, 7, bold=True)
        self.inlet_flows = self._text("", 2, 368, 7)
        for valve in VALVES:
            x, y, angle = VALVE_POS[valve.name]
            item = ValveItem(valve.name, x, y, angle, self.valve_clicked.emit)
            scene.addItem(item)
            self.valves[valve.name] = item
            dx, dy = (12, -16) if angle in (0, 180) else (12, -6)
            self.valve_labels[valve.name] = self._text(valve.name, x + dx, y + dy, 7)
        legend_y = 392
        self.legend = []
        for i, (label, kind) in enumerate((("open", "open"), ("closed", "closed"), ("blocked by interlock", "blocked"),
                                           ("pumping path", "path"))):
            x = 2 + i * 110
            swatch = QGraphicsRectItem(x, legend_y, 12, 9)
            scene.addItem(swatch)
            self.legend.append((swatch, kind))
            self._text(label, x + 16, legend_y - 2, 7)
        self.supply_text = self._text("", 2, 380, 7)
        self.setSceneRect(QRectF(-4, -2, 580, 410))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def showEvent(self, event):
        super().showEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    # --- updates ------------------------------------------------------------------------------

    def apply_theme(self, theme):
        self.theme = theme
        self.setBackgroundBrush(QColor(theme.surface))
        outline = QColor(theme.text_secondary)
        for item in self.pipes:
            item.setPen(QPen(QColor(theme.border), item.data(0), Qt.SolidLine, Qt.FlatCap))
        for item in self.lines:
            item.setPen(QPen(outline, 1.2))
        for item in self.pumps.values():
            item.setPen(QPen(outline, 1.2))
            item.setBrush(QColor(theme.panel))
        for item in self.scene().items():
            if isinstance(item, QGraphicsSimpleTextItem):
                item.setBrush(QColor(theme.text))
        for key, tag in self.gauge_tags.items():
            tag.setBrush(QColor(theme.gauge_color(key)))
            self.gauge_dots[key].setBrush(QColor(theme.gauge_color(key)))
            self.gauge_dots[key].setPen(QPen(outline, 0.8))
        self.inlet.setPen(QPen(QColor(th.SERIOUS), 3))
        self.inlet_head.setBrush(QColor(th.SERIOUS))
        self.inlet_head.setPen(QPen(QColor(th.SERIOUS), 1))
        for swatch, kind in self.legend:
            swatch.setPen(QPen(outline, 0.8))
            swatch.setBrush(self._valve_brush(kind))

    def _valve_brush(self, kind):
        if kind == "open":
            return QBrush(QColor(th.GOOD))
        if kind == "closed":
            return QBrush(QColor(th.CRITICAL))
        if kind == "blocked":
            return QBrush(QColor(self.theme.text_secondary), Qt.BDiagPattern)
        return QBrush(QColor(46, 204, 113, 110))

    def update_state(self, state, pump_path, control_allowed):
        valves = state.valves if state is not None and state.ok else {}
        known = bool(valves)
        for name, item in self.valves.items():
            is_open = valves.get(name)
            reason = interlock_reason(valves, name) if known and not is_open else None
            kind = "open" if is_open else "blocked" if reason else "closed"
            item.setBrush(self._valve_brush(kind) if known else QBrush(QColor(self.theme.border)))
            item.setPen(QPen(QColor(self.theme.text), 1.0))
            valve = VALVE_BY_NAME[name]
            lines = [f"{name}: {valve.label}", "open" if is_open else "closed" if known else "state unknown"]
            if reason:
                lines.append(f"Blocked: {reason}")
            if not control_allowed:
                lines.append("Card control is locked on this PC (read-only).")
            else:
                lines.append("Click to close." if is_open else "Click to open." if not reason else "")
            item.setToolTip("\n".join(line for line in lines if line))
            item.setCursor(Qt.PointingHandCursor if control_allowed and known else Qt.ArrowCursor)
        volume_pressure = {}
        if state is not None and state.ok:
            for key, item in self.gauge_tags.items():
                p = state.pressures.get(key)
                item.setText(f"{GAUGE_BY_KEY[key].short} {fmt_pa(p)} Pa" if p is not None
                             else f"{GAUGE_BY_KEY[key].short} – (off / out of range)")
                if p is not None:
                    volume_pressure.setdefault(GAUGE_BY_KEY[key].volume, p)
        else:
            for key, item in self.gauge_tags.items():
                item.setText(f"{GAUGE_BY_KEY[key].short} –")
        # Parts without a gauge share the pressure of a gauged part they are joined to.
        joins = {"carousel": ("V16", "main"), "prep": ("V17", "main")}
        for name, (valve, other) in joins.items():
            if valves.get(valve) and other in volume_pressure:
                volume_pressure.setdefault(name, volume_pressure[other])
        if valves.get("V15") and "loadlock" in volume_pressure:
            volume_pressure.setdefault("carousel", volume_pressure["loadlock"])
        if valves.get("V14") and "loadlock" in volume_pressure:
            volume_pressure.setdefault("airlock", volume_pressure["loadlock"])
        for name, combos in VENTED_BY.items():      # an open vent valve: that part is at atmosphere
            if any(all(valves.get(v) for v in combo) for combo in combos):
                volume_pressure.setdefault(name, ATMOSPHERE_PA)
        for name, item in self.chambers.items():
            item.setBrush(pressure_color(volume_pressure.get(name)))
            item.setPen(QPen(QColor(self.theme.text_secondary), 1.2))
        for item in self.path_items:
            self.scene().removeItem(item)
        self.path_items = []
        if known and all(valves.get(n) for n in pump_path):
            for name in pump_path:
                a, b = VALVE_BY_NAME[name].between
                path = QPainterPath(QPointF(*VOLUME_POINTS[a]))
                path.lineTo(*VOLUME_POINTS[b])
                item = self.scene().addPath(path, QPen(QColor(46, 204, 113, 110), 9, Qt.SolidLine, Qt.RoundCap))
                item.setZValue(1)
                self.path_items.append(item)
        supply = state.supply_24v if state is not None and state.ok else None
        self.supply_text.setText("" if supply is None else
                                 f"Valve supply: {'24 V (switching)' if supply else '12 V (power save, holding)'}")

    def set_flows(self, text):
        self.inlet_flows.setText(text)


class PressureMiniGraph(pg.PlotWidget):
    """The last minutes of the chamber pressures (shares the buffer of the Flows graph)."""

    def __init__(self, window_s=300, parent=None):
        super().__init__(parent, axisItems={"bottom": pg.DateAxisItem(), "left": PressureAxis("left")})
        self.window_s = window_s
        self.buffer = None
        self.keys = [g.key for g in GAUGES]
        self.setLogMode(x=False, y=True)
        self.setMenuEnabled(False)
        self.hideButtons()
        self.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)
        self.setMinimumHeight(140)
        self.curves = {key: self.plot([], []) for key in self.keys}
        self.addLegend(offset=(8, 4), labelTextSize="8pt", colCount=6)
        for key, curve in self.curves.items():
            self.getPlotItem().legend.addItem(curve, GAUGE_BY_KEY[key].short)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.redraw)
        self._timer.start(500)

    def apply_theme(self, theme):
        self.setBackground(theme.surface)
        for key, curve in self.curves.items():
            curve.setPen(pg.mkPen(theme.gauge_color(key), width=2))
        for name in ("left", "bottom"):
            axis = self.getPlotItem().getAxis(name)
            axis.setPen(pg.mkPen(theme.border))
            axis.setTextPen(pg.mkPen(theme.text_secondary))
        self.getPlotItem().showGrid(x=True, y=True, alpha=0.18)
        self.getPlotItem().legend.setLabelTextColor(theme.text)

    def redraw(self):
        if self.buffer is None or len(self.buffer) == 0 or not self.isVisible():
            for curve in self.curves.values():
                curve.setData([], [])
            return
        t = self.buffer.t
        for key, curve in self.curves.items():
            y = self.buffer.series(key)
            if np.all(np.isnan(y)):
                curve.setData([], [])
            else:
                curve.setData(t, y, connect="finite")
        end = max(t[-1], time.time())
        self.setXRange(end - self.window_s, end, padding=0)


class VacuumView(QWidget):
    """The Vacuum tab. Signals carry what the user asked for; the main window confirms and sends."""
    valve_requested = Signal(str)
    command_requested = Signal(str, object)     # kind, argument
    rule_toggled = Signal(str, bool)            # rule, protection on
    address_saved = Signal(str)
    control_toggled = Signal(bool)
    acknowledge_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = th.LIGHT
        self.state = None
        self.mode = "none"
        self.control_allowed = False
        self.pump_path = []

        self.lock_banner = QLabel()
        self.lock_banner.setWordWrap(True)
        self.lock_banner.hide()
        self.diagram = DiagramView()
        self.diagram.valve_clicked.connect(self.valve_requested)
        self.mini = PressureMiniGraph()

        left = QSplitter(Qt.Vertical)
        left.addWidget(self.diagram)
        left.addWidget(self.mini)
        left.setStretchFactor(0, 5)
        left.setStretchFactor(1, 1)
        left.setSizes([700, 130])
        self.left_split = left

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(6, 0, 6, 6)
        side_layout.addWidget(self._status_box())
        side_layout.addWidget(self._pressures_box())
        side_layout.addWidget(self._valves_box())
        self.advanced_button = QPushButton("Advanced…")
        self.advanced_button.setToolTip("Card address and control, gas protections, chamber / gun / other commands")
        self.advanced_button.clicked.connect(self.show_advanced)
        side_layout.addWidget(self.advanced_button)
        # Advanced lives in its own window, so the side panel stays narrow and the diagram large.
        self.advanced = self._advanced_box()
        self.advanced_dialog = QDialog(self)
        self.advanced_dialog.setWindowTitle("Vacuum – Advanced")
        dialog_layout = QVBoxLayout(self.advanced_dialog)
        dialog_layout.addWidget(self.advanced)
        side_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(330)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(left)
        self.split.addWidget(scroll)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.setSizes([1150, 350])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 0)
        layout.setSpacing(4)
        layout.addWidget(self.lock_banner)
        layout.addWidget(self.split, 1)

    # --- side panel -------------------------------------------------------------------------

    def _pressures_box(self):
        box = QGroupBox("Pressures")
        grid = QGridLayout(box)
        grid.setVerticalSpacing(2)
        self.pressure_labels = {}
        for row, gauge in enumerate(GAUGES):
            name = QLabel(gauge.label)
            value = QLabel("–")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self.pressure_labels[gauge.key] = (name, value)
        return box

    def _valves_box(self):
        box = QGroupBox("Valves")
        grid = QGridLayout(box)
        grid.setVerticalSpacing(2)
        self.valve_rows = {}
        for row, valve in enumerate(VALVES):
            name = QLabel(f"<b>{valve.name}</b>")
            name.setToolTip(valve.label)
            label = QLabel(valve.label)
            label.setToolTip(valve.label)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)    # shrinks; the buttons stay visible
            font = label.font()
            font.setPointSizeF(font.pointSizeF() * 0.9)
            label.setFont(font)
            state = QLabel("–")
            button = QPushButton("Open")
            button.setFixedWidth(64)
            button.clicked.connect(lambda _=False, n=valve.name: self.valve_requested.emit(n))
            grid.addWidget(name, row, 0)
            grid.addWidget(label, row, 1)
            grid.addWidget(state, row, 2)
            grid.addWidget(button, row, 3)
            self.valve_rows[valve.name] = (state, button)
        grid.setColumnStretch(1, 1)
        return box

    def _status_box(self):
        box = QGroupBox("Status")
        layout = QVBoxLayout(box)
        self.gas_label = QLabel()
        self.gas_label.setWordWrap(True)
        self.gas_label.setTextFormat(Qt.RichText)
        self.ack_button = QPushButton("Acknowledge pressure trip")
        self.ack_button.clicked.connect(self.acknowledge_requested)
        self.ack_button.hide()
        layout.addWidget(self.gas_label)
        layout.addWidget(self.ack_button)
        self.card_status = QLabel()
        self.card_status.setWordWrap(True)
        self.chamber_status = QLabel()
        self.gun_status = QLabel()
        for label in (self.card_status, self.chamber_status, self.gun_status):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(label)
        return box

    def _button(self, text, kind, argument=None, tip=""):
        button = QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(lambda: self.command_requested.emit(kind, argument() if callable(argument)
                                                                   else argument))
        self._command_buttons.append(button)
        return button

    def _advanced_box(self):
        self._command_buttons = []
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QGroupBox("Card connection (this PC)")
        card_layout = QGridLayout(card)
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("e.g. 192.168.1.10 (the address of the card's web page)")
        save = QPushButton("Save")
        save.clicked.connect(lambda: self.address_saved.emit(self.address_edit.text().strip()))
        self.control_check = QCheckBox("Allow this app to control the card (valves and commands)")
        self.control_check.setToolTip("Leave this off until the lab check (pressures and valve states match the "
                                      "web page). Saved for this PC only.")
        self.control_check.clicked.connect(self.control_toggled)
        card_layout.addWidget(QLabel("Address"), 0, 0)
        card_layout.addWidget(self.address_edit, 0, 1)
        card_layout.addWidget(save, 0, 2)
        card_layout.addWidget(self.control_check, 1, 0, 1, 3)
        layout.addWidget(card)

        rules = QGroupBox("Gas protections (untick to override, until you disconnect)")
        rules_layout = QVBoxLayout(rules)
        self.rule_checks = {}
        for rule, text in RULES.items():
            check = QCheckBox(text)
            check.setChecked(True)
            check.clicked.connect(lambda on, r=rule: self.rule_toggled.emit(r, on))
            rules_layout.addWidget(check)
            self.rule_checks[rule] = check
        layout.addWidget(rules)

        chamber = QGroupBox("Chamber")
        row = QHBoxLayout(chamber)
        row.addWidget(self._button("Vent", "chamber", "vent", "Vent the chamber (every flow goes to 0 first)"))
        row.addWidget(self._button("Pump", "chamber", "pump", "Start the chamber pumping sequence"))
        row.addWidget(self._button("Off", "chamber", "off"))
        row.addWidget(self._button("Clear error", "chamber", "clear"))
        layout.addWidget(chamber)

        gun = QGroupBox("SEM gun")
        grid = QGridLayout(gun)
        self.bake_spin = QDoubleSpinBox()
        self.bake_spin.setRange(0.0, 24.0)
        self.bake_spin.setSingleStep(0.25)
        self.bake_spin.setSuffix(" h bake-out")
        self.bake_spin.setToolTip("0 h: getter activation only (~10 h cycle); more: bake-out + ~12 h")
        grid.addWidget(self._button("Vent", "gun", "vent", "Vent the gun"), 0, 0)
        grid.addWidget(self._button("Off", "gun", "off"), 0, 1)
        grid.addWidget(self._button("Clear error", "gun", "clear"), 0, 2)
        grid.addWidget(self.bake_spin, 1, 0, 1, 2)
        grid.addWidget(self._button("Pump / bake-out", "gun_pump", lambda: self.bake_spin.value()), 1, 2)
        grid.addWidget(self._button("Beam on", "beam", True), 2, 0)
        grid.addWidget(self._button("Beam off", "beam", False), 2, 1)
        grid.addWidget(self._button("Ion pumps cold start", "gun", "ions"), 2, 2)
        layout.addWidget(gun)

        other = QGroupBox("Other")
        grid = QGridLayout(other)
        self.ups_button = self._button("UPS check", "ups")
        grid.addWidget(self.ups_button, 0, 0)
        grid.addWidget(self._button("Decontaminator on", "decontaminator", True), 0, 1)
        grid.addWidget(self._button("Decontaminator off", "decontaminator", False), 0, 2)
        grid.addWidget(self._button("Unlock FV1", "unlock", "FV1"), 1, 0)
        grid.addWidget(self._button("Unlock VV1", "unlock", "VV1"), 1, 1)
        grid.addWidget(self._button("Power save (12 V)", "power_save"), 1, 2)
        layout.addWidget(other)
        return box

    def show_advanced(self):
        self.advanced_dialog.show()
        self.advanced_dialog.raise_()
        self.advanced_dialog.activateWindow()

    # --- updates ----------------------------------------------------------------------------

    def apply_theme(self, theme):
        self.theme = theme
        self.diagram.apply_theme(theme)
        self.mini.apply_theme(theme)
        for key, (name, value) in self.pressure_labels.items():
            name.setStyleSheet(f"color: {theme.gauge_color(key)}; font-weight: bold;")
        self.lock_banner.setStyleSheet(f"background: {theme.panel}; border: 1px solid {th.WARNING}; "
                                       f"border-radius: 4px; padding: 6px;")
        self.update_state(self.state)

    def set_session(self, mode, control_allowed, pump_path, address, control_enabled):
        self.mode = mode
        self.control_allowed = control_allowed
        self.pump_path = list(pump_path)
        self.address_edit.setText(address or "")
        self.control_check.setChecked(control_enabled or mode == "sim")
        self.control_check.setEnabled(mode != "sim")
        self.control_check.setText("Allow this app to control the card (always on for the simulated card)"
                                   if mode == "sim" else "Allow this app to control the card (valves and commands)")
        if mode == "none":
            self.lock_banner.setText("No vacuum card on this PC: set its address in Advanced (it is used from the "
                                     "next connection). Without it there are no pressures and no vacuum protections.")
        elif not control_allowed:
            self.lock_banner.setText("Read-only: card control is locked on this PC. Compare the pressures and valve "
                                     "states with the card's web page first, then enable control in Advanced.")
        self.lock_banner.setVisible(mode == "none" or not control_allowed)
        for button in self._command_buttons:
            button.setEnabled(control_allowed or button is self.ups_button and mode != "none")
        self.update_state(self.state)

    def set_overrides(self, overrides):
        for rule, check in self.rule_checks.items():
            check.setChecked(rule not in overrides)

    def update_state(self, state):
        self.state = state
        self.diagram.update_state(state, self.pump_path, self.control_allowed)
        ok = state is not None and state.ok
        for key, (_, value) in self.pressure_labels.items():
            p = state.pressures.get(key) if ok else None
            value.setText(f"{fmt_pa(p)} Pa" if p is not None else "– (off / out of range)" if ok else "–")
        valves = state.valves if ok else {}
        for name, (label, button) in self.valve_rows.items():
            is_open = valves.get(name)
            reason = interlock_reason(valves, name) if valves and not is_open else None
            label.setText("–" if not valves else f'<span style="color:{th.GOOD}">● open</span>' if is_open
                          else f'<span style="color:{th.CRITICAL}">● closed</span>')
            button.setText("Close" if is_open else "Open")
            button.setEnabled(bool(valves) and self.control_allowed and reason is None)
            button.setToolTip(reason or "")
        if state is None:
            self.card_status.setText("Not reading a card." if self.mode == "none" else "Connecting…")
        elif not state.ok:
            self.card_status.setText(f"No data for {state.age_s:.0f} s: {state.error}")
        else:
            supply = "24 V" if state.supply_24v else "12 V (power save)"
            self.card_status.setText(f"{'Simulated card' if self.mode == 'sim' else 'Card'} OK · valve supply "
                                     f"{supply}")
        if ok or state is None:
            chamber = state.chamber_status if state is not None else None
            gun = state.gun_status if state is not None else None
            self.chamber_status.setText(f"Chamber status: {self._status_text(chamber)}")
            self.gun_status.setText(f"Gun status: {self._status_text(gun)}")

    @staticmethod
    def _status_text(value):
        """The card's raw status reply (its format is not documented): text as is, anything else as JSON."""
        if value is None:
            return "–"
        return value if isinstance(value, str) else json.dumps(value)

    def set_gas(self, status):
        if status is None:
            self.gas_label.setText("")
            self.ack_button.hide()
            return
        color = LEVEL_COLORS.get(status.level, th.WARNING)
        self.gas_label.setText(f'<span style="color:{color}">●</span> {status.reason}')
        self.ack_button.setVisible(status.rule == "trip")
