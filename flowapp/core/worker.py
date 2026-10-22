"""Background thread that owns the bus: polls the instruments and executes commands.

It is the only thread that talks to the serial port, so the UI never blocks on it.
Commands return a concurrent.futures.Future with the result (or the exception).
"""

import queue
import threading
import time
from collections import deque
from concurrent.futures import Future

from .channel import ChannelState


class InstrumentWorker(threading.Thread):
    def __init__(self, bus, poll_hz=4.0, history_minutes=60.0):
        super().__init__(name="InstrumentWorker", daemon=True)
        self.bus = bus
        self.period = 1.0 / poll_hz
        self.latest = {}    # address -> newest ChannelState
        self.history = deque(maxlen=max(1, int(history_minutes * 60 * poll_hz)))  # (t, [ChannelState])
        self._commands = queue.Queue()
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._listeners = []
        self._ticks = []
        self._error_listeners = []
        self._lock = threading.Lock()

    # --- called from other threads --------------------------------------------------------

    def add_listener(self, callback):
        """`callback(states)` is called from the worker thread after every poll."""
        with self._lock:
            self._listeners.append(callback)

    def add_tick(self, callback):
        """`callback(now)` is called from the worker thread before every poll (now = time.monotonic())."""
        with self._lock:
            self._ticks.append(callback)

    def add_error_listener(self, callback):
        """`callback(message)` is called from the worker thread when a tick callback raises."""
        with self._lock:
            self._error_listeners.append(callback)

    def submit(self, func, *args):
        """Runs `func(*args)` on the worker thread before the next poll."""
        future = Future()
        if self._stop_event.is_set():
            future.set_exception(RuntimeError("Instrument worker is stopped."))
            return future
        self._commands.put((future, func, args))
        self._wake.set()
        return future

    def set_setpoint(self, address, value):
        return self.submit(self.bus.set_setpoint, address, value)

    def zero_all(self):
        return self.submit(self.bus.zero_all)

    def wink(self, address):
        return self.submit(self.bus.wink, address)

    def set_control_mode(self, address, mode):
        return self.submit(self.bus.set_control_mode, address, mode)

    def stop(self, timeout=3.0):
        """Stops polling and closes the bus. Setpoints are left as they are."""
        self._stop_event.set()
        self._wake.set()
        if self.is_alive():
            self.join(timeout)

    # --- worker thread ----------------------------------------------------------------------

    def _run_commands(self):
        while True:
            try:
                future, func, args = self._commands.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(func(*args))
            except Exception as e:
                future.set_exception(e)

    def _run_ticks(self, now):
        with self._lock:
            ticks = list(self._ticks)
            error_listeners = list(self._error_listeners)
        for callback in ticks:
            try:
                callback(now)
            except Exception as e:
                for report in error_listeners:
                    try:
                        report(f"{getattr(callback, '__qualname__', callback)}: {e}")
                    except Exception:
                        pass

    def _poll(self):
        try:
            states = self.bus.read_states()
        except Exception as e:
            now = time.time()
            states =[ChannelState(c.address, now, ok=False, error=str(e)) for c in self.bus.channels]
        for s in states:
            self.latest[s.address] = s
        if states:
            self.history.append((states[0].t, states))
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(states)
            except Exception:
                pass    # a broken listener must not stop the polling

    def run(self):
        next_poll = time.monotonic()
        try:
            while not self._stop_event.is_set():
                self._wake.wait(max(0.0, next_poll - time.monotonic()))
                self._wake.clear()
                if self._stop_event.is_set():
                    break
                self._run_commands()
                now = time.monotonic()
                if now >= next_poll:
                    self._run_ticks(now)
                    self._poll()
                    next_poll += self.period
                    if next_poll < now:     # polling is slower than requested: don't try to catch up
                        next_poll = now + self.period
        finally:
            self._run_commands()
            try:
                self.bus.close()
            except Exception:
                pass
