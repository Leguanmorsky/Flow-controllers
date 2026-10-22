import pytest

from flowapp.core.simulator import SimBus


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def sim():
    clock = FakeClock()
    bus = SimBus(tau=1.0, noise=0.0, clock=clock)
    bus.open()
    bus.clock_ref = clock
    return bus


def test_open_lists_three_channels(sim):
    assert [c.fluid for c in sim.channels] == ["O2", "Ar", "He"]
    assert all(c.capacity > 0 and c.accepts_bus_setpoint for c in sim.channels)


def test_measure_follows_setpoint(sim):
    sim.set_setpoint(4, 5.0)
    sim.clock_ref.t += 10.0         # 10 time constants
    state = {s.address: s for s in sim.read_states()}[4]
    assert state.ok
    assert state.setpoint == 5.0
    assert state.measure == pytest.approx(5.0, abs=1e-3)
    assert state.setpoint_pct == pytest.approx(50.0)


def test_setpoint_is_clamped_to_capacity(sim):
    assert sim.set_setpoint(4, 1e6) == 10.0
    assert sim.set_setpoint(4, -3) == 0.0


def test_unknown_address_raises(sim):
    with pytest.raises(KeyError):
        sim.set_setpoint(99, 1.0)


def test_injected_timeouts(sim):
    sim.fail_next_reads(2)
    assert not any(s.ok for s in sim.read_states())
    assert not any(s.ok for s in sim.read_states())
    assert all(s.ok for s in sim.read_states())


def test_zero_all(sim):
    sim.set_setpoint(4, 3.0)
    sim.set_setpoint(5, 2.0)
    sim.zero_all()
    assert all(s.setpoint == 0.0 for s in sim.read_states())


def test_fault_unplugged(sim):
    sim.set_fault("unplugged")
    assert not any(s.ok for s in sim.read_states())
    with pytest.raises(RuntimeError):
        sim.set_setpoint(4, 1.0)
    with pytest.raises(RuntimeError):
        sim.zero_all()
    sim.set_fault("unplugged", on=False)
    assert all(s.ok for s in sim.read_states())


def test_fault_offline_affects_one_instrument(sim):
    sim.set_fault("offline", 5)
    ok = {s.address: s.ok for s in sim.read_states()}
    assert ok == {4: True, 5: False, 6: True}


def test_fault_analog_mode_ignores_bus_setpoints(sim):
    sim.set_fault("analog_mode", 4)
    sim.set_setpoint(4, 5.0)
    sim.clock_ref.t += 10.0
    s = {s.address: s for s in sim.read_states()}[4]
    assert (s.control_mode, s.setpoint, s.measure) == (1, 0.0, 0.0)
    assert sim.set_control_mode(4) == 0
    sim.clock_ref.t += 10.0
    s = {s.address: s for s in sim.read_states()}[4]
    assert s.control_mode == 0 and s.measure == pytest.approx(5.0, abs=1e-3)
    assert not sim.has_fault("analog_mode", 4)


def test_fault_no_gas(sim):
    sim.set_fault("no_gas", 6)
    sim.set_setpoint(6, 5.0)
    sim.clock_ref.t += 10.0
    s = {s.address: s for s in sim.read_states()}[6]
    assert (s.setpoint, s.measure, s.valve_pct) == (5.0, 0.0, 100.0)


def test_fault_validation(sim):
    with pytest.raises(KeyError):
        sim.set_fault("smoke")
    with pytest.raises(KeyError):
        sim.set_fault("offline", 99)
    with pytest.raises(ValueError):
        sim.set_control_mode(4, 8)
