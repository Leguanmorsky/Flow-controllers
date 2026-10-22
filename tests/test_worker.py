import threading
import time

import pytest

from flowapp.core.simulator import SimBus
from flowapp.core.worker import InstrumentWorker


def wait_for(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def worker():
    bus = SimBus(tau=0.05, noise=0.0)
    bus.open()
    w = InstrumentWorker(bus, poll_hz=50, history_minutes=1)
    w.start()
    yield w
    w.stop()


def test_polls_and_keeps_history(worker):
    assert wait_for(lambda: len(worker.history) >= 5)
    times = [t for t, _ in worker.history]
    assert times == sorted(times)
    assert set(worker.latest) == {4, 5, 6}


def test_commands_run_in_order(worker):
    futures = [worker.set_setpoint(4, v) for v in (1.0, 2.0, 3.0)]
    assert [f.result(timeout=2) for f in futures] == [1.0, 2.0, 3.0]
    assert wait_for(lambda: abs(worker.latest[4].measure - 3.0) < 0.01)
    assert worker.latest[4].setpoint == 3.0


def test_command_error_is_returned_not_raised(worker):
    future = worker.set_setpoint(99, 1.0)
    with pytest.raises(KeyError):
        future.result(timeout=2)
    assert worker.is_alive()


def test_timeouts_mark_states_and_recover(worker):
    seen = []
    worker.add_listener(lambda states: seen.append(all(s.ok for s in states)))
    worker.bus.fail_next_reads(3)
    assert wait_for(lambda: False in seen and seen[-1] is True)
    assert worker.is_alive()


def test_bus_exception_and_broken_listener_do_not_stop_polling(worker):
    original = worker.bus.read_states
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("cable unplugged")
        return original()

    def broken_listener(states):
        raise ValueError("listener bug")

    worker.bus.read_states = flaky
    worker.add_listener(broken_listener)
    assert wait_for(lambda: calls["n"] >= 3)
    assert worker.is_alive()
    assert all(s.ok for s in worker.latest.values())


def test_stop_closes_bus_and_rejects_new_commands():
    bus = SimBus(noise=0.0)
    bus.open()
    closed = threading.Event()
    bus.close = closed.set
    w = InstrumentWorker(bus, poll_hz=20)
    w.start()
    w.stop()
    assert not w.is_alive()
    assert closed.is_set()
    with pytest.raises(RuntimeError):
        w.set_setpoint(4, 1.0).result(timeout=1)


def test_ticks_run_on_worker_thread_and_errors_are_reported(worker):
    threads, errors = set(), []

    def tick(now):
        threads.add(threading.current_thread().name)

    def broken_tick(now):
        raise ValueError("tick bug")

    worker.add_error_listener(errors.append)
    worker.add_tick(broken_tick)
    worker.add_tick(tick)
    assert wait_for(lambda: threads and errors)
    assert threads == {"InstrumentWorker"}
    assert "tick bug" in errors[0]
    assert worker.is_alive()


def test_control_mode_command(worker):
    worker.bus.set_fault("analog_mode", 5)
    assert worker.set_control_mode(5, 0).result(timeout=2) == 0
    assert wait_for(lambda: worker.latest[5].control_mode == 0)
