"""BronkhorstBus against a fake propar (no hardware, nothing is sent to a real port)."""

import pytest

from flowapp.core import bronkhorst, dde


class FakeMaster:
    def __init__(self):
        self.alive = True
        self.msg_handler_thread = self

    def is_alive(self):
        return self.alive

    def stop(self):
        self.alive = False


class FakeDevice:
    def __init__(self, serial, has_temperature=True, accepts_fsetpoint=True):
        self.has_temperature = has_temperature
        self.accepts_fsetpoint = accepts_fsetpoint
        self.online = True
        self.accepts_setpoint = True
        self.reads = []
        self.writes = []
        self.values = {
            dde.FMEASURE: 2.5, dde.FSETPOINT: 2.5, dde.MEASURE: 8000, dde.SETPOINT: 8000,
            dde.VALVE_OUTPUT: 8388608, dde.TEMPERATURE: 23.456, dde.FLUID_NAME: "O2      ",
            dde.CAPACITY: 10.0, dde.CAPACITY_UNIT: "mln/min ", dde.USER_TAG: "", dde.CONTROL_MODE: 0,
            dde.SERIAL_NUMBER: serial, dde.DEVICE_TYPE: "DMFC",
        }


class FakeDB:
    def get_parameter(self, nr):
        return {"dde_nr": nr, "proc_nr": 0, "parm_nr": 0, "parm_type": 0}


class FakeInstrument:
    def __init__(self, device):
        self.device = device
        self.db = FakeDB()

    def readParameter(self, nr):
        return self.device.values.get(nr) if self.device.online else None

    def read_parameters(self, params):
        ddes = [p["dde_nr"] for p in params]
        self.device.reads.append(ddes)
        if not self.device.online:
            return [{"status": 25, "data": None}]
        if dde.TEMPERATURE in ddes and not self.device.has_temperature:
            return [{"status": 0x83, "data": None}]
        return [{"status": 0, "data": self.device.values[nr]} for nr in ddes]

    def writeParameter(self, nr, data):
        if not self.device.accepts_setpoint or (nr == dde.FSETPOINT and not self.device.accepts_fsetpoint):
            return False
        self.device.writes.append((nr, data))
        self.device.values[nr] = data
        return True

    def wink(self, seconds):
        self.device.winked = seconds
        return True


@pytest.fixture
def devices(monkeypatch):
    devs = {4: FakeDevice("M24207457D"), 5: FakeDevice("M24207457B")}
    masters = {}

    def instrument(port, address=0x80):
        masters.setdefault(port, FakeMaster())
        return FakeInstrument(devs[address])

    nodes = [{"address": a, "serial": d.values[dde.SERIAL_NUMBER], "type": "DMFC"} for a, d in devs.items()]
    monkeypatch.setattr(bronkhorst.propar, "instrument", instrument)
    monkeypatch.setattr(bronkhorst.propar, "_PROPAR_MASTERS", masters)
    monkeypatch.setattr(bronkhorst, "get_nodes", lambda port: nodes if port == "COM7" else [])
    monkeypatch.setattr(bronkhorst, "find_port", lambda: ("COM7", nodes))
    devs["masters"] = masters
    return devs


@pytest.fixture
def bus(devices):
    b = bronkhorst.BronkhorstBus("COM7", max_failures=3)
    b.open()
    return b


def test_open_reads_static_info(bus):
    c = bus.channels[0]
    assert (c.address, c.serial, c.device_type) == (4, "M24207457D", "DMFC")
    assert (c.fluid, c.capacity, c.unit, c.control_mode) == ("O2", 10.0, "mln/min", 0)
    assert c.accepts_bus_setpoint


def test_auto_port_uses_find_port(devices):
    b = bronkhorst.BronkhorstBus("auto")
    b.open()
    assert b.port == "COM7" and len(b.channels) == 2


def test_explicit_port_without_instruments_fails(devices):
    with pytest.raises(ConnectionError, match="COM1"):
        bronkhorst.BronkhorstBus("COM1").open()


def test_read_states_converts_units(bus):
    s = bus.read_states()[0]
    assert s.ok
    assert (s.measure, s.setpoint) == (2.5, 2.5)
    assert s.measure_pct == pytest.approx(25.0)
    assert s.valve_pct == pytest.approx(50.0, abs=0.01)
    assert s.temperature == 23.46


def test_instrument_without_temperature_sensor(bus, devices):
    devices[4].has_temperature = False
    s = bus.read_states()[0]
    assert s.ok and s.temperature is None
    devices[4].reads.clear()
    bus.read_states()
    assert devices[4].reads == [bronkhorst.POLL_DDES]   # temperature no longer requested


def test_offline_instrument_reports_error_then_reconnects(bus, devices):
    for d in (devices[4], devices[5]):
        d.online = False
    for _ in range(2):
        assert not any(s.ok for s in bus.read_states())
    assert bus.reconnects == 0
    bus.read_states()       # third failure in a row
    assert bus.reconnects == 1
    for d in (devices[4], devices[5]):
        d.online = True
    assert all(s.ok for s in bus.read_states())


def test_dead_propar_thread_triggers_reconnect(bus, devices):
    devices["masters"]["COM7"].alive = False
    bus.read_states()
    assert bus.reconnects == 1
    assert devices["masters"]["COM7"].alive     # a fresh master was created


def test_set_setpoint_writes_fsetpoint_clamped(bus, devices):
    assert bus.set_setpoint(4, 12.0) == 10.0
    assert devices[4].writes[-1] == (dde.FSETPOINT, 10.0)


def test_set_setpoint_falls_back_to_raw_setpoint(bus, devices):
    devices[4].accepts_fsetpoint = False
    assert bus.set_setpoint(4, 5.0) == 5.0
    assert devices[4].writes[-1] == (dde.SETPOINT, 16000)


def test_set_setpoint_refused(bus, devices):
    devices[4].accepts_setpoint = False
    with pytest.raises(RuntimeError):
        bus.set_setpoint(4, 1.0)


def test_unknown_capacity_refuses_setpoint(bus):
    bus.channels[0].capacity = 0.0
    with pytest.raises(ValueError):
        bus.set_setpoint(4, 1.0)


def test_zero_all_tries_every_instrument(bus, devices):
    devices[4].accepts_setpoint = False
    with pytest.raises(RuntimeError, match="4:"):
        bus.zero_all()
    assert devices[5].writes[-1] == (dde.FSETPOINT, 0.0)


def test_wink(bus, devices):
    assert bus.wink(5)
    assert devices[5].winked == 5


def test_control_mode_is_polled(bus, devices):
    assert bus.read_states()[0].control_mode == 0
    devices[4].values[dde.CONTROL_MODE] = 1       # someone switched the instrument to analog input
    s = bus.read_states()[0]
    assert s.control_mode == 1
    assert not bus.channels[0].accepts_bus_setpoint


def test_set_control_mode_writes_and_verifies(bus, devices):
    devices[4].values[dde.CONTROL_MODE] = 1
    assert bus.set_control_mode(4) == 0
    assert devices[4].writes[-1] == (dde.CONTROL_MODE, 0)
    assert bus.channels[0].accepts_bus_setpoint


def test_only_bus_control_modes_can_be_written(bus, devices):
    for mode in (1, 3, 8, 9, 20):      # analog, valve closed, valve fully open, calibration, valve steering
        with pytest.raises(ValueError):
            bus.set_control_mode(4, mode)
    assert devices[4].writes == []


def test_control_mode_readback_mismatch(bus, devices):
    original = FakeInstrument.writeParameter

    def ignore_mode(self, nr, data):
        return True if nr == dde.CONTROL_MODE else original(self, nr, data)

    FakeInstrument.writeParameter = ignore_mode
    try:
        devices[4].values[dde.CONTROL_MODE] = 1
        with pytest.raises(RuntimeError, match="reports control mode 1"):
            bus.set_control_mode(4)
    finally:
        FakeInstrument.writeParameter = original


def test_read_extra_and_static_info(bus, devices):
    devices[4].values[dde.FIRMWARE_VERSION] = "V8.21 "
    devices[4].values[dde.SETPOINT_SLOPE] = 0
    values = bus.read_extra(4, [dde.FIRMWARE_VERSION, dde.PRESSURE_INLET])
    assert values == {dde.FIRMWARE_VERSION: "V8.21 ", dde.PRESSURE_INLET: None}
    assert devices[4].writes == []
    b = bronkhorst.BronkhorstBus("COM7")
    b.open()
    assert (b.channels[0].firmware, b.channels[0].setpoint_slope) == ("V8.21", 0)
