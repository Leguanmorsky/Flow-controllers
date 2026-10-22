"""Simulated instruments with the same interface as BronkhorstBus (no hardware needed)."""

import math
import random
import time

from . import dde
from .channel import ChannelInfo, ChannelState

DEFAULT_CHANNELS = [
    # address, gas, capacity, unit (addresses as on the lab bus)
    (4, "O2", 10.0, "mln/min"),
    (5, "Ar", 10.0, "mln/min"),
    (6, "He", 10.0, "mln/min"),
]

# Faults that can be switched on to try the app's error handling (Simulator menu, tests).
FAULTS = {
    "unplugged": "Cable unplugged (nothing answers)",
    "offline": "Instrument not answering",
    "analog_mode": "In analog mode (ignores PC setpoints)",
    "no_gas": "Gas supply closed",
    "noisy": "Noisy signal",
}
CHANNEL_FAULTS = ("offline", "analog_mode", "no_gas")
ANALOG_MODE = 1


class SimBus:
    """Each channel follows its setpoint with a first-order lag (time constant `tau`) plus noise.

    `set_fault` may be called from any thread; everything else from the worker thread only.
    """

    port = "SIM"

    def __init__(self, channels=DEFAULT_CHANNELS, tau=1.0, noise=0.002, seed=None, clock=time.monotonic):
        self.tau = tau
        self.noise = noise
        self.clock = clock
        self.reconnects = 0
        self._random = random.Random(seed)
        self._spec = list(channels)
        self.channels = []
        self._setpoint = {}
        self._measure = {}
        self._mode = {}
        self._last_t = None
        self._fail_reads = 0
        self._faults = set()     # (name, address or None)
        self.winked = []

    def open(self):
        self.channels = [
            ChannelInfo(address=a, serial=f"SIM-{gas}", device_type="EL-FLOW Prestige (sim)", fluid=gas,
                        capacity=cap, unit=unit, user_tag="", control_mode=dde.BUS_CONTROL,
                        firmware="sim", setpoint_slope=0)
            for a, gas, cap, unit in self._spec
        ]
        self._setpoint = {c.address: 0.0 for c in self.channels}
        self._measure = {c.address: 0.0 for c in self.channels}
        self._mode = {c.address: dde.BUS_CONTROL for c in self.channels}
        self._last_t = self.clock()
        return self.channels

    def close(self):
        pass

    # --- fault injection --------------------------------------------------------------------

    def fail_next_reads(self, count):
        """Makes the next `count` polls time out (for testing error handling)."""
        self._fail_reads = count

    def set_fault(self, name, address=None, on=True):
        if name not in FAULTS:
            raise KeyError(f"Unknown fault {name!r}")
        if name in CHANNEL_FAULTS:
            self.channel(address)
        key = (name, address if name in CHANNEL_FAULTS else None)
        if on:
            self._faults.add(key)
        else:
            self._faults.discard(key)
        if name == "analog_mode":
            self._mode[address] = ANALOG_MODE if on else dde.BUS_CONTROL

    def has_fault(self, name, address=None):
        return (name, address if name in CHANNEL_FAULTS else None) in self._faults

    def _answers(self, address):
        return not self.has_fault("unplugged") and not self.has_fault("offline", address)

    # --- simulation -------------------------------------------------------------------------

    def _effective_setpoint(self, address):
        # In analog mode the instrument follows its analog input (here: 0 V) instead of the bus.
        return 0.0 if self._mode[address] not in dde.BUS_SETPOINT_MODES else self._setpoint[address]

    def _advance(self):
        now = self.clock()
        dt = max(now - self._last_t, 0.0)
        self._last_t = now
        k = 1.0 - math.exp(-dt / self.tau) if self.tau > 0 else 1.0
        noise = self.noise * (10 if self.has_fault("noisy") else 1)
        for info in self.channels:
            target = 0.0 if self.has_fault("no_gas", info.address) else self._effective_setpoint(info.address)
            m = self._measure[info.address]
            m += (target - m) * k
            m += self._random.gauss(0.0, noise * info.capacity) if noise else 0.0
            self._measure[info.address] = max(m, 0.0)

    def _valve_pct(self, info, setpoint, measure):
        if setpoint <= 0:
            return 0.0
        if self.has_fault("no_gas", info.address):
            return 100.0
        return min(100.0, 30.0 + 0.6 * measure / info.capacity * 100)

    def read_states(self):
        self._advance()
        now = time.time()
        if self._fail_reads > 0:
            self._fail_reads -= 1
            return [ChannelState(c.address, now, ok=False, error="no answer (timeout)") for c in self.channels]
        states = []
        for info in self.channels:
            if not self._answers(info.address):
                states.append(ChannelState(info.address, now, ok=False, error="no answer (timeout)"))
                continue
            measure = self._measure[info.address]
            setpoint = self._effective_setpoint(info.address)
            info.control_mode = self._mode[info.address]
            states.append(ChannelState(
                address=info.address,
                t=now,
                measure=measure,
                setpoint=setpoint,
                measure_pct=measure / info.capacity * 100,
                setpoint_pct=setpoint / info.capacity * 100,
                valve_pct=self._valve_pct(info, setpoint, measure),
                temperature=round(22.0 + self._random.gauss(0.0, 0.05), 2),
                control_mode=self._mode[info.address],
            ))
        return states

    # --- commands ---------------------------------------------------------------------------

    def channel(self, address):
        for info in self.channels:
            if info.address == address:
                return info
        raise KeyError(f"No instrument with address {address}")

    def _check_answers(self, address):
        if not self._answers(address):
            raise RuntimeError(f"Instrument {address} did not accept the setpoint.")

    def set_setpoint(self, address, value):
        info = self.channel(address)
        self._check_answers(address)
        self._advance()
        value = min(max(float(value), 0.0), info.capacity)
        self._setpoint[address] = value
        return value

    def zero_all(self):
        errors = []
        for info in self.channels:
            try:
                self.set_setpoint(info.address, 0.0)
            except Exception as e:
                errors.append(f"{info.address}: {e}")
        if errors:
            raise RuntimeError("Could not zero: " + "; ".join(errors))

    def set_control_mode(self, address, mode=dde.BUS_CONTROL):
        if mode not in dde.BUS_SETPOINT_MODES:
            raise ValueError(f"Control mode {mode} is not allowed from the app.")
        info = self.channel(address)
        self._check_answers(address)
        self._faults.discard(("analog_mode", address))
        self._mode[address] = mode
        info.control_mode = mode
        return mode

    def read_extra(self, address, ddes):
        info = self.channel(address)
        known = {dde.IDENT_STRING: "SIM", dde.FIRMWARE_VERSION: info.firmware, dde.USER_TAG: info.user_tag,
                 dde.FLUIDSET_INDEX: 0, dde.FLUID_NAME: info.fluid, dde.SETPOINT_SLOPE: 0,
                 dde.TEMPERATURE: 22.0}
        return {nr: known.get(nr) for nr in ddes}

    def wink(self, address, seconds=5):
        self.channel(address)
        self.winked.append(address)
        return True
