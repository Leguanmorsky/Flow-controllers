"""Bronkhorst instruments on one COM port, via propar.

Not thread-safe: use a bus from a single thread only (InstrumentWorker does that).
SimBus in simulator.py has the same interface.
"""

import time

import propar

from . import dde
from .channel import ChannelInfo, ChannelState
from .ports import close_port, find_port, get_nodes

POLL_DDES = [dde.FMEASURE, dde.FSETPOINT, dde.MEASURE, dde.SETPOINT, dde.VALVE_OUTPUT]


def _clean(text):
    return text.strip() if isinstance(text, str) else ""


def _number(value):
    return value if isinstance(value, (int, float)) else None


class BronkhorstBus:
    def __init__(self, port="auto", max_failures=5):
        self.requested_port = port
        self.port = None
        self.max_failures = max_failures
        self.channels = []
        self.reconnects = 0
        self._instruments = {}
        self._temperature_ok = {}   # address -> True / False / None (not known yet)
        self._failures = 0

    # --- connection -------------------------------------------------------------------------

    def open(self):
        """Finds the instruments and reads their static info. Returns the list of ChannelInfo."""
        if self.requested_port in (None, "", "auto"):
            self.port, nodes = find_port()
        else:
            self.port = self.requested_port
            nodes = get_nodes(self.port)
            if not nodes:
                raise ConnectionError(f"No Bronkhorst device answered on {self.port}.")
        self._instruments = {n["address"]: propar.instrument(self.port, n["address"]) for n in nodes}
        self.channels = [self._read_info(n) for n in nodes]
        self._temperature_ok = {c.address: None for c in self.channels}
        return self.channels

    def close(self):
        if self.port:
            close_port(self.port)
        self._instruments = {}

    def _read_info(self, node):
        inst = self._instruments[node["address"]]
        read = inst.readParameter
        return ChannelInfo(
            address=node["address"],
            serial=_clean(node.get("serial")) or _clean(read(dde.SERIAL_NUMBER)),
            device_type=_clean(node.get("type")) or _clean(read(dde.DEVICE_TYPE)),
            fluid=_clean(read(dde.FLUID_NAME)),
            capacity=float(_number(read(dde.CAPACITY)) or 0.0),
            unit=_clean(read(dde.CAPACITY_UNIT)),
            user_tag=_clean(read(dde.USER_TAG)),
            control_mode=_number(read(dde.CONTROL_MODE)),
        )

    def _master_alive(self):
        master = propar._PROPAR_MASTERS.get(self.port)
        return master is not None and master.msg_handler_thread.is_alive()

    def _reconnect(self):
        """Reopens the port, e.g. after propar's message thread died or the cable was replugged."""
        self.reconnects += 1
        close_port(self.port)
        try:
            self._instruments = {c.address: propar.instrument(self.port, c.address) for c in self.channels}
        except Exception:
            pass    # port still gone, the next failures trigger another attempt

    # --- polling ----------------------------------------------------------------------------

    def _chained_read(self, inst, ddes):
        """Reads several parameters in one message. Returns {dde: value} or None on failure."""
        params = [dict(inst.db.get_parameter(nr)) for nr in ddes]
        result = inst.read_parameters(params)
        if not result or len(result) != len(ddes):
            return None
        if any(r.get("status", 0) != 0 or r.get("data") is None for r in result):
            return None
        return {nr: r["data"] for nr, r in zip(ddes, result)}

    def _read_state(self, info):
        inst = self._instruments.get(info.address)
        now = time.time()
        if inst is None:
            return ChannelState(info.address, now, ok=False, error="not connected")

        temp_ok = self._temperature_ok.get(info.address)
        ddes = POLL_DDES + ([dde.TEMPERATURE] if temp_ok is not False else [])
        values = self._chained_read(inst, ddes)
        if values is None and temp_ok is None:
            # Not every instrument has a temperature sensor: try once without it.
            values = self._chained_read(inst, POLL_DDES)
            if values is not None:
                self._temperature_ok[info.address] = False
        elif values is not None and temp_ok is None:
            self._temperature_ok[info.address] = True
        if values is None:
            return ChannelState(info.address, now, ok=False, error="no answer (timeout)")

        raw_measure = _number(values[dde.MEASURE])
        raw_setpoint = _number(values[dde.SETPOINT])
        raw_valve = _number(values[dde.VALVE_OUTPUT])
        temperature = _number(values.get(dde.TEMPERATURE))
        return ChannelState(
            address=info.address,
            t=now,
            measure=_number(values[dde.FMEASURE]),
            setpoint=_number(values[dde.FSETPOINT]),
            measure_pct=None if raw_measure is None else raw_measure / dde.FULL_SCALE * 100,
            setpoint_pct=None if raw_setpoint is None else raw_setpoint / dde.FULL_SCALE * 100,
            valve_pct=None if raw_valve is None else raw_valve / dde.VALVE_FULL_SCALE * 100,
            temperature=None if temperature is None else round(temperature, 2),
        )

    def read_states(self):
        """Polls every instrument once. Never raises for communication errors."""
        states = [self._read_state(info) for info in self.channels]
        if states and not any(s.ok for s in states):
            self._failures += 1
        else:
            self._failures = 0
        if self.channels and (self._failures >= self.max_failures or not self._master_alive()):
            self._failures = 0
            self._reconnect()
        return states

    # --- commands ---------------------------------------------------------------------------

    def _channel(self, address):
        for info in self.channels:
            if info.address == address:
                return info
        raise KeyError(f"No instrument with address {address}")

    def set_setpoint(self, address, value):
        """Sets the flow setpoint in capacity units, clamped to [0, capacity]. Returns the value sent."""
        info = self._channel(address)
        if info.capacity <= 0:
            raise ValueError(f"Capacity of instrument {address} is unknown, cannot set a flow.")
        value = min(max(float(value), 0.0), info.capacity)
        inst = self._instruments[address]
        if inst.writeParameter(dde.FSETPOINT, value):
            return value
        # Some instruments refuse fSetpoint: fall back to the 0..32000 setpoint.
        if inst.writeParameter(dde.SETPOINT, round(value / info.capacity * dde.FULL_SCALE)):
            return value
        raise RuntimeError(f"Instrument {address} did not accept the setpoint.")

    def zero_all(self):
        """Sets every setpoint to 0. Tries all instruments even if one fails."""
        errors = []
        for info in self.channels:
            try:
                self.set_setpoint(info.address, 0.0)
            except Exception as e:
                errors.append(f"{info.address}: {e}")
        if errors:
            raise RuntimeError("Could not zero: " + "; ".join(errors))

    def wink(self, address, seconds=5):
        """Blinks the instrument's LEDs so it can be found on the gas panel."""
        self._channel(address)
        return self._instruments[address].wink(seconds)
