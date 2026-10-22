"""Setpoint ramps: move a setpoint to a target at a constant rate.

RampManager runs on the instrument worker thread: start/cancel go through
InstrumentWorker.submit() and tick() is registered with InstrumentWorker.add_tick().
"""

import time
from dataclasses import dataclass

from . import dde


@dataclass(frozen=True)
class Ramp:
    address: int
    start: float
    target: float
    rate: float         # capacity units per second
    t0: float           # clock() when the ramp started

    @property
    def duration(self):
        return abs(self.target - self.start) / self.rate if self.rate > 0 else 0.0

    def value(self, t):
        elapsed = max(t - self.t0, 0.0)
        if elapsed >= self.duration:
            return self.target
        step = self.rate * elapsed
        return self.start + step if self.target >= self.start else self.start - step

    def remaining(self, t):
        return max(self.duration - (t - self.t0), 0.0)

    def done(self, t):
        return t - self.t0 >= self.duration


class RampManager:
    """Ramps of several instruments. `on_event(kind, ramp, detail)` reports started/finished/cancelled/failed."""

    def __init__(self, bus, current_setpoint, clock=time.monotonic, on_event=None):
        self.bus = bus
        self.current_setpoint = current_setpoint    # address -> device setpoint (None if unknown)
        self.clock = clock
        self.on_event = on_event or (lambda kind, ramp, detail="": None)
        self.ramps = {}     # address -> Ramp; replaced, never mutated, so other threads may read it
        self._sent = {}     # address -> last value sent

    def _resolution(self, address):
        capacity = self.bus.channel(address).capacity
        return capacity / dde.FULL_SCALE

    def start(self, address, target, rate=None, duration=None, start=None):
        """Starts a ramp from the current device setpoint. Give `rate` (units/s) or `duration` (s)."""
        self.bus.channel(address)
        if start is None:
            start = self.current_setpoint(address)
            if start is None:
                raise ValueError(f"Current setpoint of instrument {address} is unknown.")
        if duration is not None:
            rate = abs(target - start) / duration if duration > 0 and target != start else float("inf")
        if rate is None or rate <= 0:
            raise ValueError("The ramp rate must be greater than 0.")
        self.cancel(address)
        ramp = Ramp(address, float(start), float(target), float(rate), self.clock())
        self.ramps[address] = ramp
        self._sent[address] = ramp.start
        self.on_event("started", ramp)
        return ramp

    def cancel(self, address):
        ramp = self.ramps.pop(address, None)
        self._sent.pop(address, None)
        if ramp:
            self.on_event("cancelled", ramp)
        return ramp is not None

    def cancel_all(self):
        cancelled = list(self.ramps)
        for address in cancelled:
            self.cancel(address)
        return cancelled

    def tick(self, now=None):
        """Sends the next setpoint of every ramp; only when it moved by at least the instrument's resolution."""
        now = self.clock() if now is None else now
        for address, ramp in list(self.ramps.items()):
            finished = ramp.done(now)
            value = ramp.value(now)
            if not finished and abs(value - self._sent[address]) < self._resolution(address):
                continue
            try:
                self.bus.set_setpoint(address, value)
            except Exception as e:
                self.ramps.pop(address, None)
                self._sent.pop(address, None)
                self.on_event("failed", ramp, str(e))
                continue
            self._sent[address] = value
            if finished:
                self.ramps.pop(address, None)
                self._sent.pop(address, None)
                self.on_event("finished", ramp)
