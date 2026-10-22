"""Connects the Qt UI to the instrument worker thread.

All public methods are called from the UI thread. Callbacks from the worker thread only emit
signals, which Qt delivers to the UI thread.
"""

import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

from ..config import load_simulator
from ..core import dde
from ..core.bronkhorst import BronkhorstBus
from ..core.ramp import RampManager
from ..core.simulator import SimBus
from ..core.watch import SetpointWatch
from ..core.worker import InstrumentWorker
from .units import decimals_for

SIM_PORT = "SIM"


def default_bus_factory(port):
    return SimBus(**load_simulator()) if port == SIM_PORT else BronkhorstBus(port)


def _error_text(exc):
    return str(exc) or type(exc).__name__


class InstrumentBridge(QObject):
    connected = Signal(object)          # list[ChannelInfo]
    connect_failed = Signal(str)
    disconnected = Signal()
    states_updated = Signal(object)     # list[ChannelState]
    event = Signal(str, str)            # level ("info", "warning", "error"), message
    ramps_changed = Signal()

    _opened = Signal(object, object, int)   # bus, channels, attempt
    _open_failed = Signal(str, int)
    _polled = Signal(object)

    def __init__(self, settings, bus_factory=default_bus_factory, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.test_only = settings.simulate     # test session: hardware ports are refused
        self.bus_factory = bus_factory
        self.bus = None
        self.worker = None
        self.ramps = None
        self.channels = []
        self.names = {}         # address -> display name, set by the window
        self.max_flow = {}      # address -> soft limit in capacity units (None = capacity)
        self.deviation = {}     # address -> None, "low" or "high"
        self.last_poll = None   # time.monotonic() when the last states arrived
        self.poll_rate = 0.0
        self._attempt = 0
        self._connecting = False
        self._ok = {}
        self._modes = {}
        self._watches = {}
        self._reconnects = 0
        self._last_t = None
        self._opened.connect(self._on_opened)
        self._open_failed.connect(self._on_open_failed)
        self._polled.connect(self._on_polled)

    # --- state ------------------------------------------------------------------------------

    @property
    def is_connected(self):
        return self.worker is not None

    @property
    def is_connecting(self):
        return self._connecting

    @property
    def simulated(self):
        return isinstance(self.bus, SimBus)

    def channel(self, address):
        for info in self.channels:
            if info.address == address:
                return info
        raise KeyError(address)

    def name(self, address):
        if address in self.names:
            return self.names[address]
        try:
            return self.channel(address).fluid or f"Address {address}"
        except KeyError:
            return f"Address {address}"

    def limit(self, address):
        capacity = self.channel(address).capacity
        maximum = self.max_flow.get(address)
        return min(capacity, maximum) if maximum else capacity

    def ramp(self, address):
        return self.ramps.ramps.get(address) if self.ramps else None

    def ramp_remaining(self, address):
        ramp = self.ramp(address)
        return ramp.remaining(time.monotonic()) if ramp else None

    def _fmt(self, address, value):
        info = self.channel(address)
        return f"{value:.{decimals_for(info.capacity)}f} {info.unit}"

    # --- connection -------------------------------------------------------------------------

    def connect_to(self, port):
        """Opens the bus on a background thread; ends with `connected` or `connect_failed`."""
        if self.worker or self._connecting:
            return
        if self.test_only and port != SIM_PORT:
            message = "This is a test-mode session: real instruments are disabled. Start run.bat to use them."
            self.event.emit("error", message)
            self.connect_failed.emit(message)
            return
        try:
            bus = self.bus_factory(port)
        except Exception as e:      # e.g. an invalid config/simulator.json
            self.event.emit("error", f"Connection failed: {_error_text(e)}")
            self.connect_failed.emit(_error_text(e))
            return
        self._connecting = True
        self._attempt += 1
        attempt = self._attempt

        def open_bus():
            try:
                channels = bus.open()
                if not channels:
                    raise ConnectionError("No instruments found.")
            except Exception as e:
                try:
                    bus.close()
                except Exception:
                    pass
                self._open_failed.emit(_error_text(e), attempt)
            else:
                self._opened.emit(bus, channels, attempt)

        threading.Thread(target=open_bus, name="OpenBus", daemon=True).start()

    def cancel_connect(self):
        if self._connecting:
            self._attempt += 1      # the running attempt is ignored and its bus closed when it ends
            self._connecting = False
            self.event.emit("info", "Connection attempt cancelled.")
            self.disconnected.emit()

    @Slot(object, object, int)
    def _on_opened(self, bus, channels, attempt):
        if attempt != self._attempt:
            bus.close()
            return
        self._connecting = False
        self.bus = bus
        self.channels = list(channels)
        self.ramps = RampManager(bus, self._current_setpoint, on_event=self._on_ramp_event)
        self.worker = InstrumentWorker(bus, self.settings.poll_hz, self.settings.history_minutes)
        self.worker.add_listener(self._polled.emit)
        self.worker.add_tick(self.ramps.tick)
        self.worker.add_error_listener(lambda message: self.event.emit("error", message))
        self._ok = {}
        self._modes = {c.address: c.control_mode for c in self.channels}
        self._watches = {c.address: SetpointWatch() for c in self.channels}
        self.deviation = {}
        self._reconnects = bus.reconnects
        self.last_poll = self._last_t = None
        self.poll_rate = 0.0
        self.worker.start()
        if self.simulated:
            self.event.emit("warning", f"TEST MODE: {len(self.channels)} simulated instrument(s), no gas flows.")
        else:
            self.event.emit("info", f"Connected to {bus.port}: {len(self.channels)} instrument(s).")
        self.connected.emit(self.channels)
        for c in self.channels:
            if c.capacity <= 0:
                self.event.emit("error", f"{self.name(c.address)}: capacity unknown, setpoints cannot be sent.")
            if not c.accepts_bus_setpoint:
                self.event.emit("warning", f"{self.name(c.address)} is in “{dde.control_mode_name(c.control_mode)}” "
                                           f"mode: it ignores setpoints from the PC.")
            if c.setpoint_slope:
                self.event.emit("info", f"{self.name(c.address)}: the instrument's own setpoint slope is "
                                        f"{c.setpoint_slope}, so it ramps setpoint changes internally.")

    @Slot(str, int)
    def _on_open_failed(self, message, attempt):
        if attempt != self._attempt:
            return
        self._connecting = False
        self.event.emit("error", f"Connection failed: {message}")
        self.connect_failed.emit(message)

    def disconnect(self, zero=True, timeout=3.0):
        """Stops the worker. With zero=True all ramps are cancelled and every flow is set to 0 first.

        Returns None when done, or the error text when the flows could not be confirmed at 0
        (the connection then stays open; call force_disconnect() to drop it anyway).
        """
        if self._connecting:
            self.cancel_connect()
            return None
        if not self.worker:
            return None
        if zero:
            try:
                self.worker.submit(self._zero_everything).result(timeout)
            except Exception as e:
                message = _error_text(e)
                self.event.emit("error", f"Could not confirm that all flows are 0: {message}")
                return message
            self.event.emit("info", "All flows set to 0.")
        self._shutdown()
        return None

    def emergency_zero(self, timeout=3.0):
        """Thread-safe: cancels ramps and sets every flow to 0. Used when the console window is closed."""
        worker = self.worker
        if worker is None:
            return False
        try:
            worker.submit(self._zero_everything).result(timeout)
            return True
        except Exception:
            return False

    def force_disconnect(self):
        if self.worker:
            self.event.emit("warning", "Disconnected without confirming that all flows are 0.")
            self._shutdown()

    def _shutdown(self):
        worker, self.worker = self.worker, None
        worker.stop()
        self.ramps = None
        self.event.emit("info", "Disconnected.")
        self.disconnected.emit()

    # --- polling (UI thread) ----------------------------------------------------------------

    def _current_setpoint(self, address):
        # Called on the worker thread by RampManager.
        state = self.worker.latest.get(address) if self.worker else None
        return state.setpoint if state is not None and state.ok else None

    @Slot(object)
    def _on_polled(self, states):
        if self.worker is None or not states:
            return      # late delivery after a disconnect
        now = time.monotonic()
        t = states[0].t
        if self._last_t is not None and t > self._last_t:
            rate = 1.0 / (t - self._last_t)
            self.poll_rate = rate if not self.poll_rate else 0.8 * self.poll_rate + 0.2 * rate
        self._last_t = t
        self.last_poll = now
        for s in states:
            self._check_answer(s)
            self._check_mode(s)
            self._check_deviation(s, now)
        if self.bus.reconnects != self._reconnects:
            self._reconnects = self.bus.reconnects
            self.event.emit("warning", f"No instrument answered: reopened {self.bus.port} "
                                       f"(reconnect #{self._reconnects}).")
        self.states_updated.emit(states)

    def _check_answer(self, s):
        was_ok = self._ok.get(s.address)
        if s.ok != was_ok:
            if not s.ok:
                self.event.emit("error", f"{self.name(s.address)}: {s.error}")
            elif was_ok is False:
                self.event.emit("info", f"{self.name(s.address)} is answering again.")
        self._ok[s.address] = s.ok

    def _check_mode(self, s):
        if s.control_mode is None or s.control_mode == self._modes.get(s.address):
            return
        self._modes[s.address] = s.control_mode
        name = dde.control_mode_name(s.control_mode)
        if s.control_mode in dde.BUS_SETPOINT_MODES:
            self.event.emit("info", f"{self.name(s.address)} is in “{name}” mode: accepts setpoints from the PC.")
        else:
            self.event.emit("warning", f"{self.name(s.address)} switched to “{name}” mode: "
                                       f"setpoints from the PC are ignored.")

    def _check_deviation(self, s, now):
        watch = self._watches.get(s.address)
        if watch is None:
            return
        result = watch.update(s, now, suspended=self.ramp(s.address) is not None)
        previous = self.deviation.get(s.address)
        if result == previous:
            return
        self.deviation[s.address] = result
        if result == "low":
            self.event.emit("warning", f"{self.name(s.address)}: flow stays below the setpoint "
                                       f"(gas supply closed?).")
        elif result == "high":
            self.event.emit("warning", f"{self.name(s.address)}: flow stays above the setpoint.")
        elif previous:
            self.event.emit("info", f"{self.name(s.address)}: flow matches the setpoint again.")

    # --- commands ---------------------------------------------------------------------------

    def _report(self, future, failure, success=None, level="info"):
        """Logs the outcome of a worker command (runs on the worker thread; only emits signals)."""
        def done(f):
            error = f.exception()
            if error is not None:
                self.event.emit("error", f"{failure}: {_error_text(error)}")
            elif success:
                self.event.emit(level, success(f.result()))
        future.add_done_callback(done)
        return future

    def _clamp(self, address, value):
        limit = self.limit(address)
        if value > limit:
            self.event.emit("warning", f"{self.name(address)}: {self._fmt(address, value)} limited to "
                                       f"{self._fmt(address, limit)} (max flow).")
            return limit
        return max(value, 0.0)

    def set_setpoint(self, address, value, source="user"):
        if not self.worker:
            return None
        value = self._clamp(address, value)
        name = self.name(address)
        return self._report(self.worker.submit(self._apply_setpoint, address, value),
                            f"{name}: setpoint not sent",
                            lambda sent: f"{name} setpoint → {self._fmt(address, sent)} ({source})")

    def _apply_setpoint(self, address, value):
        # Worker thread: a manual setpoint ends a running ramp of that channel.
        self.ramps.cancel(address)
        return self.bus.set_setpoint(address, value)

    def all_to_zero(self):
        if not self.worker:
            return None
        return self._report(self.worker.submit(self._zero_everything), "ALL TO 0 failed",
                            lambda _: "ALL TO 0: ramps cancelled, every flow set to 0.", level="warning")

    def _zero_everything(self):
        # Worker thread: one command, so no ramp step can slip in between.
        self.ramps.cancel_all()
        self.bus.zero_all()

    def start_ramp(self, address, target, rate_per_min=None, duration_s=None):
        if not self.worker:
            return None
        target = self._clamp(address, target)
        rate = rate_per_min / 60.0 if rate_per_min is not None else None
        return self._report(self.worker.submit(self.ramps.start, address, target, rate, duration_s),
                            f"{self.name(address)}: ramp not started")

    def stop_ramp(self, address):
        if self.worker:
            self.worker.submit(self.ramps.cancel, address)

    def _on_ramp_event(self, kind, ramp, detail=""):
        # Worker thread.
        name, a = self.name(ramp.address), ramp.address
        if kind == "started":
            self.event.emit("info", f"{name}: ramp {self._fmt(a, ramp.start)} → {self._fmt(a, ramp.target)} "
                                    f"started, {ramp.rate * 60:.4g} {self.channel(a).unit} per minute.")
        elif kind == "finished":
            self.event.emit("info", f"{name}: ramp finished at {self._fmt(a, ramp.target)}.")
        elif kind == "cancelled":
            self.event.emit("info", f"{name}: ramp cancelled.")
        elif kind == "failed":
            self.event.emit("error", f"{name}: ramp stopped, setpoint not accepted: {detail}")
        self.ramps_changed.emit()

    def switch_to_bus_control(self, address):
        if not self.worker:
            return None
        name = self.name(address)
        return self._report(self.worker.set_control_mode(address, dde.BUS_CONTROL),
                            f"{name}: control mode not changed",
                            lambda mode: f"{name} switched to “{dde.control_mode_name(mode)}” mode (PC control).")

    def wink(self, address):
        if not self.worker:
            return None
        return self._report(self.worker.wink(address), f"{self.name(address)}: identify failed",
                            lambda _: f"{self.name(address)}: LEDs blinking.")
