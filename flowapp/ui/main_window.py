"""Main window: start screen, or connection bar + channel cards (left) + graph (right); log at the bottom."""

import html
import sys
import threading
import time
from collections import deque
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QPlainTextEdit, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..config import CONFIG_DIR, ROOT, ChannelConfig, load_card_config, load_channels, save_channels
from ..core.card_sim import FAULTS as CARD_FAULTS
from ..core.report import save_report
from ..core.safety import GasBlocked
from ..core.simulator import CHANNEL_FAULTS, FAULTS
from ..desktop import create_desktop_shortcut
from . import dialogs
from . import theme as th
from .bridge import SIM_PORT, InstrumentBridge, default_bus_factory
from .card_bridge import CardBridge
from .channel_card import ChannelCard
from .connection_bar import ConnectionBar
from .graph import DEFAULT_SLOTS, MIXTURE_MIN_TOTAL, PANELS, FlowGraph, history_samples, swatch
from .start_page import StartPage
from .units import common_unit, decimals_for
from .vacuum_widgets import PressureStrip

EXPORT_DIR = ROOT / "exports"
LOG_LINES = 2000
STALE_S = 2.0       # the status bar turns red when no poll arrived for this long
THEME_LABELS = {"system": "Follow Windows", "light": "Light", "dark": "Dark"}
PANEL_PRESETS = [("pressure", "mixture"), ("pressure", "valve"), ("mixture", "valve"), ("pressure", "off"),
                 ("off", "off")]


def _package_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return "?"


class MainWindow(QMainWindow):
    _shortcut_done = Signal(str, str)   # level, message (from the background thread)

    def __init__(self, settings, bus_factory=default_bus_factory, channels_path=CONFIG_DIR / "channels.json",
                 qsettings=None, make_shortcut=create_desktop_shortcut, card_config_loader=load_card_config):
        super().__init__()
        self.settings = settings
        self.make_shortcut = make_shortcut     # None: never create a desktop shortcut (tests)
        self.channels_path = Path(channels_path)
        self.qsettings = qsettings if qsettings is not None else QSettings("FlowControllers", "FlowApp")
        self.channel_config = load_channels(self.channels_path)
        self.bridge = InstrumentBridge(settings, bus_factory, self)
        self.card = CardBridge(self.bridge, card_config_loader, parent=self)
        self.bridge.gas_guard = lambda value: self.card.supervisor.check_setpoint(value)
        self.cards = {}
        self.theme = th.LIGHT
        self.theme_mode = str(self.qsettings.value("theme", "system"))
        self.pct_mode = self.qsettings.value("pct_mode", False, type=bool)
        self._sim_actions = []
        self._log_entries = deque(maxlen=LOG_LINES)     # (time, level, message), re-rendered on theme change
        self._applying_theme = False
        self._build_ui()
        self._build_menus()
        self._connect_signals()
        self._restore_state()
        self.apply_theme(self.theme_mode if self.theme_mode in th.MODES else "system")
        self._update_title()
        self._show_start_page()
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(500)
        if settings.auto_connect:       # a port or --sim on the command line skips the start screen
            QTimer.singleShot(0, lambda: self._connect_port(SIM_PORT if settings.simulate else settings.port))
        if self.make_shortcut and not self.qsettings.value("desktop_shortcut_created", False, type=bool):
            QTimer.singleShot(1000, self.create_shortcut)

    # --- layout -----------------------------------------------------------------------------

    def _build_ui(self):
        self.bar = ConnectionBar()
        self.start = StartPage(test_only=self.settings.simulate)
        self.start.refresh_ports(self.settings.port)
        self.test_strip = QLabel("TEST MODE  ·  simulated instruments  ·  nothing is sent to the real flow "
                                 "controllers, no gas flows")
        self.test_strip.setAlignment(Qt.AlignCenter)
        self.test_strip.setStyleSheet(f"background: {th.SERIOUS}; color: #0b0b0b; font-weight: bold; padding: 4px;")
        self.test_strip.hide()

        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(6, 6, 6, 6)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.cards_widget)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumWidth(370)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setContentsMargins(8, 4, 8, 4)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.scroll, 1)
        left_layout.addWidget(self.summary)

        self.graph = FlowGraph()
        self.strip = PressureStrip()
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 4, 4, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.strip)
        right_layout.addWidget(self.graph, 1)
        self.h_split = QSplitter(Qt.Horizontal)
        self.h_split.addWidget(left)
        self.h_split.addWidget(right)
        self.h_split.setStretchFactor(1, 1)
        self.h_split.setSizes([390, 1000])

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(LOG_LINES)
        self.log.setPlaceholderText("Log: connections, setpoints, ramps, warnings and errors appear here.")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start)
        self.stack.addWidget(self.h_split)
        self.v_split = QSplitter(Qt.Vertical)
        self.v_split.addWidget(self.stack)
        self.v_split.addWidget(self.log)
        self.v_split.setStretchFactor(0, 1)
        self.v_split.setSizes([700, 150])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.bar)
        layout.addWidget(self.test_strip)
        layout.addWidget(self.v_split, 1)
        self.setCentralWidget(central)

        self.rate_label = QLabel()
        self.reconnect_label = QLabel()
        self.age_label = QLabel()
        for label in (self.rate_label, self.reconnect_label, self.age_label):
            self.statusBar().addPermanentWidget(label)

    def _build_menus(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        file_menu.addAction("Export graph as PNG…", lambda: self.export("png"))
        file_menu.addAction("Export data as CSV…", lambda: self.export("csv"))
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)

        view_menu = menu.addMenu("&View")
        self.pct_action = view_menu.addAction("Flows in % of full scale")
        self.pct_action.setCheckable(True)
        self.pct_action.setChecked(self.pct_mode)
        self.pct_action.toggled.connect(self.set_pct_mode)
        view_menu.addSeparator()
        panels_menu = view_menu.addMenu("Lower graph panels")
        for preset in PANEL_PRESETS:
            label = " + ".join(PANELS[k] for k in preset if k != "off") or "None (flow only)"
            panels_menu.addAction(label, lambda p=preset: self.graph.set_slots(p))
        theme_menu = view_menu.addMenu("Theme")
        group = QActionGroup(self)
        self.theme_actions = {}
        for mode in th.MODES:
            action = theme_menu.addAction(THEME_LABELS[mode])
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _=False, m=mode: self.apply_theme(m))
            self.theme_actions[mode] = action

        instruments_menu = menu.addMenu("&Instruments")
        self.zero_action = instruments_menu.addAction("ALL TO 0")
        self.zero_action.setShortcut(QKeySequence("F12"))
        self.zero_action.setShortcutContext(Qt.ApplicationShortcut)
        self.zero_action.triggered.connect(self.all_to_zero)
        self.zero_action.setEnabled(False)
        self.report_action = instruments_menu.addAction("Instrument report…")
        self.report_action.setToolTip("Read-only report of the connected instruments, saved in logs/")
        self.report_action.triggered.connect(self.bridge.instrument_report)
        self.report_action.setEnabled(False)
        instruments_menu.addSeparator()
        self.disconnect_action = instruments_menu.addAction("Disconnect")
        self.disconnect_action.triggered.connect(self._disconnect)
        self.disconnect_action.setEnabled(False)

        self.sim_menu = menu.addMenu("&Test mode")
        self.sim_menu.aboutToShow.connect(self._sync_sim_menu)
        self.sim_menu.menuAction().setVisible(False)

        help_menu = menu.addMenu("&Help")
        help_menu.addAction("Create desktop shortcut", self.create_shortcut)
        help_menu.addAction("About", self._about)

    def _connect_signals(self):
        self.start.connect_requested.connect(self._connect_port)
        self.start.test_requested.connect(lambda: self._connect_port(SIM_PORT))
        self.start.cancel_requested.connect(self.bridge.cancel_connect)
        self.bar.disconnect_clicked.connect(self._disconnect)
        self.bar.all_zero_clicked.connect(self.all_to_zero)
        self._shortcut_done.connect(self._on_shortcut_done)
        b = self.bridge
        b.report_ready.connect(self._show_report)
        b.connected.connect(self._on_connected)
        b.connect_failed.connect(self._on_connect_failed)
        b.disconnected.connect(self._on_disconnected)
        b.states_updated.connect(self._on_states)
        b.event.connect(self.log_event)
        b.ramps_changed.connect(self._refresh_ramps)
        self.graph.export_requested.connect(self.export)
        c = self.card
        c.vacuum_updated.connect(self._on_vacuum)
        c.gas_status_changed.connect(self.strip.set_gas)
        c.event.connect(self.log_event)
        self.strip.acknowledge_requested.connect(c.acknowledge_trip)
        QApplication.styleHints().colorSchemeChanged.connect(self._system_theme_changed)

    def _show_start_page(self, message="", error=False):
        self.stack.setCurrentWidget(self.start)
        self.bar.hide()
        self.start.set_idle(message, error)

    def _update_title(self):
        test = self.bridge.simulated or self.settings.simulate
        self.setWindowTitle("Flow controllers" + (" [TEST MODE]" if test else ""))
        self.test_strip.setVisible(test)

    # --- connection -------------------------------------------------------------------------

    def _connect_port(self, port):
        label = {"auto": "the instruments (auto-detect)", SIM_PORT: "test mode"}.get(port, port)
        self.start.set_busy(f"Starting {label}…" if port == SIM_PORT else f"Connecting to {label}…")
        self.bridge.connect_to(port)

    def _on_connected(self, channels):
        self._build_cards(channels)
        self.card.start(self.bridge.simulated)
        if self.card.running:
            self.graph.start_pressures(int(self.settings.history_minutes * 60 * self.card.config.poll_hz),
                                       self.card.config.p_max_pa)
        self.strip.set_card(None, self.card.mode)
        self.strip.set_gas(self.card.gas_status())
        if self.bridge.simulated:
            self.bar.set_status(f"Test mode · {len(channels)} simulated instrument(s)", th.SERIOUS)
        else:
            self.bar.set_status(f"Connected to {self.bridge.bus.port} · {len(channels)} instrument(s)")
        self.stack.setCurrentWidget(self.h_split)
        self.bar.show()
        for action in (self.zero_action, self.report_action, self.disconnect_action):
            action.setEnabled(True)
        self._build_sim_menu()
        self._update_title()

    def _on_connect_failed(self, message):
        self._show_start_page(f"Connection failed: {message}", error=True)

    def _on_disconnected(self):
        self.card.stop()
        self.graph.stop_pressures()
        self.strip.set_gas(None)
        self._clear_cards()
        for action in (self.zero_action, self.report_action, self.disconnect_action):
            action.setEnabled(False)
        self.sim_menu.menuAction().setVisible(False)
        self._update_title()
        self._show_start_page()
        self._update_status()

    def _disconnect(self):
        if self.bridge.is_connecting:
            self.bridge.cancel_connect()
        else:
            self.release_instruments("Disconnect")

    def release_instruments(self, action):
        """Cancels ramps, sets every flow to 0 and disconnects. Returns False if the user chose to stay."""
        while self.bridge.is_connected:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                error = self.bridge.disconnect(zero=True)
            finally:
                QApplication.restoreOverrideCursor()
            if error is None:
                break
            choice = dialogs.ask_zero_failed(self, error, action)
            if choice == "anyway":
                self.bridge.force_disconnect()
            elif choice == "cancel":
                return False
        return True

    def closeEvent(self, event):
        if self.bridge.is_connecting:
            self.bridge.cancel_connect()
        if not self.release_instruments("Close"):
            event.ignore()
            return
        self._save_state()
        event.accept()

    def all_to_zero(self):
        if self.bridge.is_connected:
            self.bridge.all_to_zero()

    # --- cards ------------------------------------------------------------------------------

    def _channel_style(self, index, info):
        cfg = self.channel_config.get(info.key, ChannelConfig())
        name = cfg.alias or info.fluid or f"Address {info.address}"
        color = self.theme.channel_color(index, cfg.color)
        limit = min(info.capacity, cfg.max_flow) if cfg.max_flow else info.capacity
        step = cfg.step or info.capacity / 100
        return cfg, name, color, limit, step

    def _configure_card(self, index, info):
        cfg, name, color, limit, step = self._channel_style(index, info)
        self.cards[info.address].configure(name, color, limit, step)
        self.bridge.names[info.address] = name
        self.bridge.max_flow[info.address] = cfg.max_flow
        return name, color

    def _build_cards(self, channels):
        self._clear_cards()
        names, colors = {}, {}
        for index, info in enumerate(channels):
            card = ChannelCard(info)
            card.apply_theme(self.theme)
            card.set_pct_mode(self.pct_mode)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self.cards[info.address] = card
            card.setpoint_requested.connect(self._request_setpoint)
            card.ramp_requested.connect(self._request_ramp)
            card.ramp_stop_requested.connect(self.bridge.stop_ramp)
            card.identify_requested.connect(self.bridge.wink)
            card.settings_requested.connect(self._edit_channel)
            card.control_mode_requested.connect(self._switch_control)
            names[info.address], colors[info.address] = self._configure_card(index, info)
        self.graph.set_channels(channels, names, colors, history_samples(self.settings))
        self._update_summary(None)
        # The column must be wide enough for the widest card (it never scrolls sideways).
        widest = max(card.minimumSizeHint().width() for card in self.cards.values())
        margins = self.cards_layout.contentsMargins()
        self.scroll.setMinimumWidth(widest + margins.left() + margins.right()
                                    + self.scroll.verticalScrollBar().sizeHint().width())

    def _clear_cards(self):
        for card in self.cards.values():
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self.cards = {}
        self.summary.setText("")

    def _restyle_cards(self):
        names, colors = {}, {}
        for index, info in enumerate(self.bridge.channels):
            if info.address in self.cards:
                self.cards[info.address].apply_theme(self.theme)
                names[info.address], colors[info.address] = self._configure_card(index, info)
        if names:
            self.graph.set_names_colors(names, colors)

    def _edit_channel(self, address):
        info = self.bridge.channel(address)
        index = self.bridge.channels.index(info)
        cfg = self.channel_config.get(info.key, ChannelConfig())
        dialog = dialogs.ChannelSettingsDialog(info, cfg, self.theme.channel_color(index), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.channel_config[info.key] = dialog.result_config()
        try:
            save_channels(self.channel_config, self.channels_path)
        except OSError as e:
            self.log_event("error", f"Could not save {self.channels_path.name}: {e}")
        self._restyle_cards()
        self.log_event("info", f"Settings of {self.bridge.name(address)} saved.")

    def _switch_control(self, address):
        name = self.bridge.name(address)
        if dialogs.confirm(self, "Switch to PC control",
                           f"Switch {name} to bus/RS232 control?\n\nThe instrument will then follow setpoints "
                           f"from this app instead of its analog input or local setting."):
            self.bridge.switch_to_bus_control(address)

    def _on_states(self, states):
        for s in states:
            card = self.cards.get(s.address)
            if card:
                card.update_state(s, self.bridge.ramp(s.address), self.bridge.ramp_remaining(s.address),
                                  self.bridge.deviation.get(s.address))
        self.graph.append(states)
        self.card.feed_sim_flows(states, self.bridge.channels)
        self._update_summary(states)

    def _on_vacuum(self, state):
        self.graph.append_pressures(state)
        self.strip.set_card(state, self.card.mode)

    # --- gas safety ---------------------------------------------------------------------------

    def _with_gas_check(self, send):
        """Runs `send()`; when a safety rule refuses the gas, asks whether to override (or acknowledge a trip)."""
        try:
            return send()
        except GasBlocked as blocked:
            self.log_event("warning", f"Not sent: {blocked.reason}")
            choice = dialogs.gas_blocked(self, blocked)
            if choice == "acknowledge":
                self.card.acknowledge_trip()
            elif choice == "override" and blocked.overridable:
                self.card.set_override(blocked.rule, True)
                try:
                    return send()
                except GasBlocked as again:
                    self.log_event("error", f"Not sent: {again.reason}")
        return None

    def _request_setpoint(self, address, value):
        return self._with_gas_check(lambda: self.bridge.set_setpoint(address, value))

    def _request_ramp(self, address, target, rate_per_min=None, duration_s=None):
        return self._with_gas_check(lambda: self.bridge.start_ramp(address, target, rate_per_min, duration_s))

    def _refresh_ramps(self):
        for address, card in self.cards.items():
            card.set_ramp(self.bridge.ramp(address), self.bridge.ramp_remaining(address))

    def _update_summary(self, states):
        channels = self.bridge.channels
        unit = common_unit(channels)
        if unit is None:
            self.summary.setText("Total: the instruments use different units.")
            return
        ok = [s for s in states or [] if s.ok and s.measure is not None]
        if not ok:
            self.summary.setText("")
            return
        total = sum(s.measure for s in ok)
        decimals = max(decimals_for(c.capacity) for c in channels)
        parts = [f"<b>Total {total:.{decimals}f} {unit}</b>"]
        if total >= MIXTURE_MIN_TOTAL * sum(c.capacity for c in channels):
            for s in ok:
                parts.append(swatch(self.cards[s.address].color,
                                    f"{html.escape(self.bridge.name(s.address))} {s.measure / total * 100:.0f} %"))
        self.summary.setText(" · ".join(parts))

    # --- simulator menu ---------------------------------------------------------------------

    def _build_sim_menu(self):
        self.sim_menu.clear()
        self._sim_actions = []
        self.sim_menu.menuAction().setVisible(self.bridge.simulated)
        if not self.bridge.simulated:
            return
        for name in ("unplugged", "noisy"):
            self._add_sim_action(self.sim_menu, name, None)
        if self.card.sim_card is not None:
            card_menu = self.sim_menu.addMenu("Vacuum card")
            for name, label in CARD_FAULTS.items():
                action = card_menu.addAction(label)
                action.setCheckable(True)
                action.toggled.connect(lambda on, n=name: self.card.set_sim_fault(n, on))
                self._sim_actions.append((action, name, "card"))
        self.sim_menu.addSeparator()
        for info in self.bridge.channels:
            sub = self.sim_menu.addMenu(self.bridge.name(info.address))
            for name in CHANNEL_FAULTS:
                self._add_sim_action(sub, name, info.address)

    def _add_sim_action(self, menu, name, address):
        action = menu.addAction(FAULTS[name])
        action.setCheckable(True)
        action.toggled.connect(lambda on, n=name, a=address: self._set_fault(n, a, on))
        self._sim_actions.append((action, name, address))

    def _set_fault(self, name, address, on):
        if not self.bridge.simulated:
            return
        self.bridge.bus.set_fault(name, address, on)
        where = f" on {self.bridge.name(address)}" if address is not None else ""
        self.log_event("warning", f"Test mode: “{FAULTS[name]}”{where} {'on' if on else 'off'}.")

    def _sync_sim_menu(self):
        if not self.bridge.simulated:
            return
        for action, name, address in self._sim_actions:
            action.blockSignals(True)
            if address == "card":
                action.setChecked(self.card.sim_card is not None and self.card.sim_card.has_fault(name))
            else:
                action.setChecked(self.bridge.bus.has_fault(name, address))
            action.blockSignals(False)

    # --- view -------------------------------------------------------------------------------

    def set_pct_mode(self, on):
        self.pct_mode = on
        for card in self.cards.values():
            card.set_pct_mode(on)
        self.graph.set_pct_mode(on)

    def apply_theme(self, mode):
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            self.theme_mode = mode
            self.theme = th.apply(QApplication.instance(), mode)
        finally:
            self._applying_theme = False
        self.theme_actions[mode].setChecked(True)
        self.graph.apply_theme(self.theme)
        self.strip.apply_theme(self.theme)
        self.start.apply_theme(self.theme)
        self._restyle_cards()
        self.log.clear()
        for entry in self._log_entries:
            self._append_log_line(*entry)

    def _system_theme_changed(self, *_):
        if self.theme_mode == "system":
            self.apply_theme("system")

    # --- status, log, export ----------------------------------------------------------------

    def _update_status(self):
        if not self.bridge.is_connected:
            for label in (self.rate_label, self.reconnect_label, self.age_label):
                label.setText("")
            return
        self.rate_label.setText(f"Polling {self.bridge.poll_rate:.1f} Hz")
        self.reconnect_label.setText(f"Reconnects {self.bridge.bus.reconnects}")
        last = self.bridge.last_poll
        age = None if last is None else time.monotonic() - last
        if age is None or age > STALE_S:
            since = f" for {age:.0f} s" if age is not None else ""
            self.age_label.setText(f'<span style="color:{th.CRITICAL}">●</span> no data{since}')
        else:
            self.age_label.setText(f"Last poll {age:.1f} s ago")

    def log_event(self, level, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        if sys.stdout is not None:
            line = f"{stamp} {level.upper():<7} {message}"
            encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            try:    # the console may not be able to show every character (e.g. → on cp1252)
                print(line.encode(encoding, errors="replace").decode(encoding), flush=True)
            except (OSError, ValueError, LookupError):
                pass
        self._log_entries.append((stamp, level, message))
        self._append_log_line(stamp, level, message)

    def _append_log_line(self, stamp, level, message):
        icon = {"warning": (th.WARNING, "⚠"), "error": (th.CRITICAL, "✖")}.get(level)
        icon_html = f'<span style="color:{icon[0]}">{icon[1]}</span> ' if icon else ""
        self.log.appendHtml(f'<span style="color:{self.theme.text_secondary}">{stamp}</span>&nbsp; '
                            f'{icon_html}{html.escape(message)}')

    def log_text(self):
        return "\n".join(f"{stamp} {level} {message}" for stamp, level, message in self._log_entries)

    def export(self, kind):
        if self.graph.sample_count() == 0:
            self.log_event("warning", "Nothing to export yet: connect and record some data first.")
            return
        EXPORT_DIR.mkdir(exist_ok=True)
        prefix = "TEST_flow" if self.bridge.simulated else "flow"     # simulated data must not pass for real data
        default = EXPORT_DIR / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.{kind}"
        filters = "PNG image (*.png)" if kind == "png" else "CSV file (*.csv)"
        path, _ = QFileDialog.getSaveFileName(self, "Export", str(default), filters)
        if not path:
            return
        try:
            if kind == "png":
                self.graph.export_png(path)
            else:
                self.graph.export_csv(path)
        except Exception as e:
            self.log_event("error", f"Export failed: {e}")
        else:
            self.log_event("info", f"Exported {path}")

    def _about(self):
        QMessageBox.about(self, "About Flow controllers",
                          f"<b>Flow controllers</b> {__version__}<br>"
                          f"Control software for Bronkhorst mass flow controllers.<br><br>"
                          f"bronkhorst-propar {_package_version('bronkhorst-propar')} · "
                          f"PySide6 {_package_version('PySide6-Essentials')} · "
                          f"pyqtgraph {_package_version('pyqtgraph')}<br>"
                          f"Config folder: {CONFIG_DIR}")

    # --- instrument report, desktop shortcut --------------------------------------------------

    def _show_report(self, lines):
        try:
            path = save_report(lines)
            self.log_event("info", f"Instrument report saved to {path}")
        except OSError as e:
            path = None
            self.log_event("error", f"Could not save the instrument report: {e}")
        dialogs.show_text(self, "Instrument report", "\n".join(lines), path)

    def create_shortcut(self):
        """Creates the desktop shortcut on a background thread (PowerShell takes a moment)."""
        if not self.make_shortcut:
            return

        def work():
            try:
                path = self.make_shortcut()
            except Exception as e:
                self._shortcut_done.emit("warning", f"Could not create the desktop shortcut: {e}")
            else:
                self._shortcut_done.emit("info", f"Desktop shortcut created: {path}")

        threading.Thread(target=work, name="DesktopShortcut", daemon=True).start()

    def _on_shortcut_done(self, level, message):
        self.log_event(level, message)
        if level == "info":
            self.qsettings.setValue("desktop_shortcut_created", True)
            self.qsettings.sync()

    # --- persistence ------------------------------------------------------------------------

    def _restore_state(self):
        q = self.qsettings
        geometry = q.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1400, 860)
        for key, splitter in (("h_split", self.h_split), ("v_split", self.v_split)):
            state = q.value(key)
            if state:
                splitter.restoreState(state)
        slots = q.value("graph_slots", ",".join(DEFAULT_SLOTS))
        self.graph.set_slots(str(slots).split(","))
        gauges = q.value("graph_gauges")
        if gauges is not None:
            self.graph.set_gauges([g for g in str(gauges).split(",") if g])
        self.graph.window_combo.setCurrentIndex(q.value("window_index", 1, type=int))
        self.graph.set_pct_mode(self.pct_mode)

    def _save_state(self):
        q = self.qsettings
        q.setValue("geometry", self.saveGeometry())
        q.setValue("h_split", self.h_split.saveState())
        q.setValue("v_split", self.v_split.saveState())
        q.setValue("theme", self.theme_mode)
        q.setValue("pct_mode", self.pct_mode)
        q.setValue("graph_slots", ",".join(self.graph.slots))
        q.setValue("graph_gauges", ",".join(self.graph.selected_gauges()))
        q.setValue("window_index", self.graph.window_combo.currentIndex())
