"""Background thread that owns the card client: polls pressures + valves and executes card commands.

Same pattern as InstrumentWorker: the only thread that talks to the card, commands return a Future.
"""

import queue
import threading
import time
from concurrent.futures import Future

from .vacuum import VacuumState

POWER_SAVE_DELAY_S = 1.0    # the web page drops the valve supply back to 12 V 1 s after opening a valve


def _error_text(exc):
    return str(exc) or type(exc).__name__


class CardWorker(threading.Thread):
    def __init__(self, client, poll_hz=5.0, stale_s=2.0, status_period_s=1.0, clock=time.monotonic):
        super().__init__(name="CardWorker", daemon=True)
        self.client = client
        self.period = 1.0 / poll_hz
        self.stale_s = stale_s
        self.status_period_s = status_period_s
        self.clock = clock
        self.latest = None          # newest VacuumState (good or failed)
        self.latest_good = None     # newest VacuumState with data
        self._last_good_t = None
        self._started_t = None
        self._next_status = 0.0
        self._commands = queue.Queue()
        self._later = []            # (due, func, description) commands scheduled by the worker itself
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._listeners = []
        self._error_listeners = []
        self._lock = threading.Lock()

    # --- called from other threads --------------------------------------------------------

    def add_listener(self, callback):
        """`callback(state)` is called from the worker thread after every poll."""
        with self._lock:
            self._listeners.append(callback)

    def add_error_listener(self, callback):
        """`callback(message)` is called from the worker thread when a scheduled command fails."""
        with self._lock:
            self._error_listeners.append(callback)

    def submit(self, func, *args):
        """Runs `func(*args)` on the worker thread; the card is polled right after it."""
        future = Future()
        if self._stop_event.is_set():
            future.set_exception(RuntimeError("Card worker is stopped."))
            return future
        self._commands.put((future, func, args))
        self._wake.set()
        return future

    def open_valve(self, name):
        def run():
            register = self.client.open_valve(name)
            self._later.append((self.clock() + POWER_SAVE_DELAY_S, self.client.power_save,
                                "valve supply back to 12 V"))
            return register
        return self.submit(run)

    def close_valve(self, name):
        return self.submit(self.client.close_valve, name)

    def stop(self, timeout=3.0):
        self._stop_event.set()
        self._wake.set()
        if self.is_alive():
            self.join(timeout)

    # --- worker thread ----------------------------------------------------------------------

    def _report_error(self, message):
        with self._lock:
            listeners = list(self._error_listeners)
        for callback in listeners:
            try:
                callback(message)
            except Exception:
                pass

    def _run_commands(self):
        ran = False
        now = self.clock()
        for item in [i for i in self._later if i[0] <= now]:
            self._later.remove(item)
            try:
                item[1]()
            except Exception as e:
                self._report_error(f"Card: {item[2]} failed: {_error_text(e)}")
            ran = True
        while True:
            try:
                future, func, args = self._commands.get_nowait()
            except queue.Empty:
                return ran
            ran = True
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(func(*args))
            except Exception as e:
                future.set_exception(e)

    def _poll(self):
        now = self.clock()
        with_status = now >= self._next_status
        try:
            state = self.client.read_all(with_status=with_status)
        except Exception as e:
            age = now - (self._last_good_t if self._last_good_t is not None else self._started_t)
            state = VacuumState(t=time.time(), ok=False, error=_error_text(e), age_s=age, stale=age > self.stale_s)
        else:
            self._last_good_t = now
            if with_status:
                self._next_status = now + self.status_period_s
            elif self.latest_good is not None:      # keep the last status between status reads
                state.chamber_status = self.latest_good.chamber_status
                state.gun_status = self.latest_good.gun_status
            self.latest_good = state
        self.latest = state
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(state)
            except Exception:
                pass    # a broken listener must not stop the polling

    def run(self):
        self._started_t = self.clock()
        next_poll = self.clock()
        try:
            while not self._stop_event.is_set():
                waits = [next_poll] + [due for due, *_ in self._later]
                self._wake.wait(max(0.0, min(waits) - self.clock()))
                self._wake.clear()
                if self._stop_event.is_set():
                    break
                if self._run_commands():
                    next_poll = min(next_poll, self.clock())      # show the result of a command at once
                now = self.clock()
                if now >= next_poll:
                    self._poll()
                    next_poll += self.period
                    if next_poll < now:
                        next_poll = now + self.period
        finally:
            for due, func, description in self._later:     # e.g. the 12 V drop of a just opened valve
                try:
                    func()
                except Exception:
                    pass
            self._later = []
            self._run_commands()
            self.client.close()
