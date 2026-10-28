"""Connects the Qt UI to the card worker thread and the gas-safety supervisor.

Test mode always uses the simulated card; with the real instruments the card from the settings
(none when no address is set on this PC). All public methods are called from the UI thread.
"""

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..config import load_card_config
from ..core import card as rpc
from ..core.card_sim import FAULTS as CARD_FAULTS
from ..core.card_sim import SimCard
from ..core.card_worker import CardWorker
from ..core.safety import GasSupervisor
from ..core.vacuum import VALVE_BY_NAME, parse_register, to_sccm

READBACK_S = 2.0    # a valve command is checked against the valve register after this long


def _error_text(exc):
    return str(exc) or type(exc).__name__


class CardBridge(QObject):
    vacuum_updated = Signal(object)     # VacuumState, or None when stopped
    gas_status_changed = Signal(object)     # GasStatus
    event = Signal(str, str)            # level, message
    started = Signal()
    stopped = Signal()

    _state = Signal(object)

    def __init__(self, instruments, config_loader=load_card_config, transport_factory=None, parent=None):
        super().__init__(parent)
        self.instruments = instruments
        self.config_loader = config_loader
        self.transport_factory = transport_factory or (lambda config: rpc.HttpTransport(config.address,
                                                                                         config.timeout_s))
        self.config = config_loader()
        self.mode = "none"          # "none" (no card on this PC), "sim" or "real"
        self.worker = None
        self.supervisor = GasSupervisor(self.config, self.instruments.safety_zero, self.instruments.gas_flowing,
                                        self.event.emit, card_present=False)
        self.latest = None
        self.sim_card = None
        self._reachable = None
        self._gas_status = None
        self._state.connect(self._on_state)

    # --- state ------------------------------------------------------------------------------

    @property
    def running(self):
        return self.worker is not None

    @property
    def control_allowed(self):
        return self.worker is not None and self.worker.client.allow_control

    @property
    def where(self):
        if self.mode == "sim":
            return "simulated card"
        if self.mode == "real":
            return f"card {self.config.address}"
        return "no card"

    def gas_status(self):
        return self.supervisor.status()

    # --- start / stop -------------------------------------------------------------------------

    def start(self, simulated):
        """Starts reading the card that belongs to this session."""
        self.stop()
        self.config = self.config_loader()
        allow = False
        if simulated:
            self.sim_card = transport = SimCard()
            self.mode, allow = "sim", True
        elif self.config.address:
            try:
                transport = self.transport_factory(self.config)
            except Exception as e:
                self.event.emit("error", f"Vacuum card: {_error_text(e)}")
                transport = None
            self.mode, allow = ("real", self.config.control_enabled) if transport else ("none", False)
        else:
            transport, self.mode = None, "none"
        self.supervisor = GasSupervisor(self.config, self.instruments.safety_zero, self.instruments.gas_flowing,
                                        self.event.emit, card_present=self.mode != "none")
        self._reachable = None
        self._gas_status = None
        if transport is None:
            self.event.emit("warning", "No vacuum card set up on this PC: no chamber pressures, the vacuum "
                                       "protections are off (Vacuum → Advanced to set the card address).")
            self._emit_gas_status()
            return
        client = rpc.CardClient(transport, allow_control=allow)
        self.worker = CardWorker(client, self.config.poll_hz, self.config.stale_s)
        self.worker.add_listener(self._on_worker_state)
        self.worker.add_error_listener(lambda message: self.event.emit("error", message))
        self.worker.start()
        if self.mode == "sim":
            self.event.emit("warning", "TEST MODE: simulated vacuum card and chamber.")
        else:
            lock = "control enabled" if allow else "read-only (control locked on this PC)"
            self.event.emit("info", f"Reading the vacuum card at {self.config.address}, {lock}.")
        self.started.emit()

    def stop(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.stop()
            self.event.emit("info", "Vacuum card disconnected.")
        self.supervisor.reset()
        self.latest = None
        self.sim_card = None
        self.mode = "none"
        self.vacuum_updated.emit(None)
        self.stopped.emit()

    # --- polling --------------------------------------------------------------------------------

    def _on_worker_state(self, state):
        # Worker thread: the safety reacts at once, the UI gets the state through a signal.
        self.supervisor.on_state(state)
        self._state.emit(state)

    @Slot(object)
    def _on_state(self, state):
        if self.worker is None:
            return      # late delivery after stop
        self.latest = state
        if state.ok != self._reachable:
            if not state.ok:
                self.event.emit("error", f"Vacuum card: {state.error}")
            elif self._reachable is False:
                self.event.emit("info", "Vacuum card answering again.")
            self._reachable = state.ok
        self.vacuum_updated.emit(state)
        self._emit_gas_status()

    def _emit_gas_status(self):
        status = self.supervisor.status()
        if status != self._gas_status:
            self._gas_status = status
            self.gas_status_changed.emit(status)

    def feed_sim_flows(self, states, channels):
        """Test mode: the simulated chamber sees the simulated MFC flows."""
        if self.sim_card is None:
            return
        units = {c.address: c.unit for c in channels}
        self.sim_card.set_flow(sum(to_sccm(s.measure, units.get(s.address)) for s in states
                                   if s.ok and s.measure is not None and s.measure > 0))

    def set_sim_fault(self, name, on):
        if self.sim_card is not None:
            self.sim_card.set_fault(name, on)
            self.event.emit("warning", f"Test mode: “{CARD_FAULTS[name]}” {'on' if on else 'off'}.")

    # --- gas safety -----------------------------------------------------------------------------

    def set_override(self, rule, on):
        self.supervisor.set_override(rule, on)
        self._emit_gas_status()

    def acknowledge_trip(self):
        self.supervisor.acknowledge_trip()
        self._emit_gas_status()

    # --- commands -------------------------------------------------------------------------------

    def _run(self, func, args, text, success=None, level="info"):
        if self.worker is None:
            self.event.emit("error", f"{text}: no vacuum card.")
            return None
        if not self.control_allowed:
            self.event.emit("error", f"{text}: card control is locked on this PC.")
            return None
        future = self.worker.submit(func, *args)

        def done(f):
            error = f.exception()
            if error is not None:
                self.event.emit("error", f"Vacuum card: {text} failed: {_error_text(error)}")
            else:
                self.event.emit(level, success(f.result()) if success else f"Vacuum card: {text}.")
        future.add_done_callback(done)
        return future

    def _vent_guard(self, what, keep_gas=False):
        """Sets every flow to 0 before venting (unless overridden). False when that could not be confirmed."""
        zeroed = self.supervisor.before_vent(what, override=keep_gas)
        if hasattr(zeroed, "result"):
            try:
                zeroed.result(3.0)
            except Exception as e:
                self.event.emit("error", f"Not sent: could not confirm every flow at 0 before you {what} "
                                         f"({_error_text(e)}).")
                return False
        return True

    def open_valve(self, name, keep_gas=False):
        if VALVE_BY_NAME[name].function == "vent" and not self._vent_guard(f"open the vent valve {name}", keep_gas):
            return None
        future = self._run(self.worker.open_valve_job if self.worker else None, (name,), f"open {name}",
                           lambda _: f"Vacuum card: {name} opened.")
        if future is not None:
            QTimer.singleShot(int(READBACK_S * 1000), lambda: self._check_valve(name, True))
        return future

    def close_valve(self, name):
        future = self._run(self.worker.client.close_valve if self.worker else None, (name,), f"close {name}",
                           lambda _: f"Vacuum card: {name} closed.")
        if future is not None:
            QTimer.singleShot(int(READBACK_S * 1000), lambda: self._check_valve(name, False))
        return future

    def _check_valve(self, name, expected):
        state = self.latest
        if self.worker is None or state is None or state.register is None:
            return
        if parse_register(state.register)[name] != expected:
            self.event.emit("warning", f"{name} did not {'open' if expected else 'close'}: the valve register "
                                       f"still shows it {'closed' if expected else 'open'}.")

    def chamber(self, command, keep_gas=False):
        if command == "vent" and not self._vent_guard("vent the chamber", keep_gas):
            return None
        client = self.worker.client if self.worker else None
        return self._run(client.chamber if client else None, (command,), rpc.CHAMBER_COMMANDS[command],
                         lambda result: f"Vacuum card: {rpc.CHAMBER_COMMANDS[command]} → {result}", "warning")

    def gun(self, command, keep_gas=False):
        if command == "vent" and not self._vent_guard("vent the gun", keep_gas):
            return None
        client = self.worker.client if self.worker else None
        return self._run(client.gun if client else None, (command,), rpc.GUN_COMMANDS[command],
                         lambda result: f"Vacuum card: {rpc.GUN_COMMANDS[command]} → {result}", "warning")

    def gun_pump(self, hours):
        client = self.worker.client if self.worker else None
        text = rpc.gun_pump(hours).text
        return self._run(client.gun_pump if client else None, (hours,), text,
                         lambda result: f"Vacuum card: {text} → {result}", "warning")

    def beam(self, on):
        client = self.worker.client if self.worker else None
        return self._run(client.beam if client else None, (on,), f"beam {'on' if on else 'off'}",
                         lambda result: f"Vacuum card: beam {'on' if on else 'off'} → {result}", "warning")

    def ups(self):
        client = self.worker.client if self.worker else None
        if self.worker is None:
            self.event.emit("error", "UPS check: no vacuum card.")
            return None
        future = self.worker.submit(client.ups)      # a read: allowed while control is locked

        def done(f):
            if f.exception() is not None:
                self.event.emit("error", f"UPS check failed: {_error_text(f.exception())}")
            else:
                ac, battery = f.result()
                self.event.emit("info" if ac and battery else "warning",
                                f"UPS: AC {'OK' if ac else 'OFF'}, battery {'OK' if battery else 'LOW'}.")
        future.add_done_callback(done)
        return future

    def decontaminator(self, on):
        client = self.worker.client if self.worker else None
        return self._run(client.decontaminator if client else None, (on,), f"decontaminator {'on' if on else 'off'}",
                         lambda result: f"Vacuum card: decontaminator {'ON' if result else 'OFF'}.")

    def unlock(self, name):
        client = self.worker.client if self.worker else None
        return self._run(client.unlock if client else None, (name,), f"unlock {name}")

    def power_save(self):
        client = self.worker.client if self.worker else None
        return self._run(client.power_save if client else None, (), "valve supply to 12 V (power save)")
