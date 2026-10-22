import pytest

from flowapp.core.ramp import Ramp, RampManager
from flowapp.core.simulator import SimBus


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_ramp_values_up_and_down():
    up = Ramp(4, start=1.0, target=3.0, rate=0.5, t0=10.0)
    assert up.duration == 4.0
    assert up.value(10.0) == 1.0
    assert up.value(12.0) == 2.0
    assert up.value(99.0) == 3.0
    assert up.remaining(11.0) == 3.0 and not up.done(13.9) and up.done(14.0)
    down = Ramp(4, start=3.0, target=1.0, rate=1.0, t0=0.0)
    assert down.value(1.5) == 1.5


@pytest.fixture
def setup():
    clock = Clock()
    bus = SimBus(noise=0.0, clock=clock)
    bus.open()
    events = []
    current = {4: 0.0, 5: 0.0, 6: 0.0}
    manager = RampManager(bus, current.get, clock=clock, on_event=lambda kind, ramp, detail="": events.append(kind))
    return clock, bus, manager, events, current


def test_ramp_reaches_target_and_finishes(setup):
    clock, bus, manager, events, _ = setup
    manager.start(4, 2.0, rate=1.0)
    for t in (0.5, 1.0, 1.5):
        clock.t = t
        manager.tick()
        assert bus._setpoint[4] == pytest.approx(t)
    clock.t = 5.0
    manager.tick()
    assert bus._setpoint[4] == 2.0
    assert 4 not in manager.ramps
    assert events == ["started", "finished"]


def test_ramp_starts_from_device_setpoint(setup):
    clock, bus, manager, _, current = setup
    current[5] = 6.0
    ramp = manager.start(5, 2.0, duration=8.0)
    assert (ramp.start, ramp.rate) == (6.0, 0.5)
    clock.t = 2.0
    manager.tick()
    assert bus._setpoint[5] == pytest.approx(5.0)


def test_small_changes_are_not_sent(setup):
    clock, bus, manager, _, _ = setup
    sent = []
    original = bus.set_setpoint
    bus.set_setpoint = lambda a, v: sent.append(v) or original(a, v)
    manager.start(4, 10.0, rate=10.0 / 32000 / 10)    # one resolution step every 10 s
    for i in range(1, 30):
        clock.t = i
        manager.tick()
    assert len(sent) == 2                              # at 10 s and 20 s


def test_cancel_and_failure(setup):
    clock, bus, manager, events, _ = setup
    manager.start(4, 5.0, rate=1.0)
    manager.start(5, 5.0, rate=1.0)
    assert manager.cancel(4) and not manager.cancel(4)
    bus.set_fault("offline", 5)
    clock.t = 1.0
    manager.tick()
    assert manager.ramps == {}
    assert events == ["started", "started", "cancelled", "failed"]


def test_invalid_ramps(setup):
    _, _, manager, _, current = setup
    with pytest.raises(ValueError):
        manager.start(4, 5.0, rate=0.0)
    current[4] = None
    with pytest.raises(ValueError):
        manager.start(4, 5.0, rate=1.0)
    with pytest.raises(KeyError):
        manager.start(99, 5.0, rate=1.0)


def test_duration_ramp_to_same_value_is_a_step(setup):
    clock, bus, manager, events, _ = setup
    manager.start(4, 0.0, duration=10.0)
    manager.tick()
    assert events == ["started", "finished"]
