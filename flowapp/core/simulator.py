"""Simulated instruments with the same interface as BronkhorstBus (no hardware needed)."""

import math
import random
import time

from .channel import ChannelInfo, ChannelState

DEFAULT_CHANNELS = [
    # address, gas, capacity, unit
    (4, "O2", 10.0, "mln/min"),
    (5, "Ar", 10.0, "mln/min"),
    (6, "He", 10.0, "mln/min"),
]


class SimBus:
    """Each channel follows its setpoint with a first-order lag (time constant `tau`) plus noise."""

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
        self._last_t = None
        self._fail_reads = 0
        self.winked = []

    def open(self):
        self.channels = [
            ChannelInfo(address=a, serial=f"SIM-{gas}", device_type="DMFC (simulated)", fluid=gas,
                        capacity=cap, unit=unit, user_tag="", control_mode=0)
            for a, gas, cap, unit in self._spec
        ]
        self._setpoint = {c.address: 0.0 for c in self.channels}
        self._measure = {c.address: 0.0 for c in self.channels}
        self._last_t = self.clock()
        return self.channels

    def close(self):
        pass

    def fail_next_reads(self, count):
        """Makes the next `count` polls time out (for testing error handling)."""
        self._fail_reads = count

    def _advance(self):
        now = self.clock()
        dt = max(now - self._last_t, 0.0)
        self._last_t = now
        k = 1.0 - math.exp(-dt / self.tau) if self.tau > 0 else 1.0
        for info in self.channels:
            m = self._measure[info.address]
            m += (self._setpoint[info.address] - m) * k
            m += self._random.gauss(0.0, self.noise * info.capacity) if self.noise else 0.0
            self._measure[info.address] = max(m, 0.0)

    def read_states(self):
        self._advance()
        now = time.time()
        if self._fail_reads > 0:
            self._fail_reads -= 1
            return [ChannelState(c.address, now, ok=False, error="no answer (timeout)") for c in self.channels]
        states = []
        for info in self.channels:
            measure = self._measure[info.address]
            setpoint = self._setpoint[info.address]
            states.append(ChannelState(
                address=info.address,
                t=now,
                measure=measure,
                setpoint=setpoint,
                measure_pct=measure / info.capacity * 100,
                setpoint_pct=setpoint / info.capacity * 100,
                valve_pct=min(100.0, 30.0 + 0.6 * measure / info.capacity * 100) if setpoint > 0 else 0.0,
                temperature=round(22.0 + self._random.gauss(0.0, 0.05), 2),
            ))
        return states

    def _channel(self, address):
        for info in self.channels:
            if info.address == address:
                return info
        raise KeyError(f"No instrument with address {address}")

    def set_setpoint(self, address, value):
        info = self._channel(address)
        self._advance()
        value = min(max(float(value), 0.0), info.capacity)
        self._setpoint[address] = value
        return value

    def zero_all(self):
        for info in self.channels:
            self.set_setpoint(info.address, 0.0)

    def wink(self, address, seconds=5):
        self._channel(address)
        self.winked.append(address)
        return True
