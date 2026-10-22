import json
from types import SimpleNamespace

import pytest

from flowapp import config
from flowapp.core import ports
from flowapp.core.simulator import SimBus


def port(device, description="USB Serial Port", hwid="USB VID:PID=0403:6001"):
    return SimpleNamespace(device=device, description=description, hwid=hwid)


@pytest.fixture
def fake_ports(monkeypatch):
    available = [
        port("COM3", "Standard Serial over Bluetooth link (COM3)", r"BTHENUM\{00001101}"),
        port("COM5"),
        port("COM9"),
    ]
    monkeypatch.setattr(ports.serial.tools.list_ports, "comports", lambda: available)
    return available


def test_candidates_skip_bluetooth_and_try_com9_first(fake_ports):
    candidates, available = ports.candidate_ports()
    assert candidates == ["COM9", "COM5"]
    assert available == ["COM3", "COM5", "COM9"]


def test_find_port_returns_first_port_with_nodes(fake_ports, monkeypatch):
    opened = []

    def get_nodes(name):
        opened.append(name)
        return [{"address": 4}] if name == "COM5" else []

    monkeypatch.setattr(ports, "get_nodes", get_nodes)
    assert ports.find_port() == ("COM5", [{"address": 4}])
    assert "COM3" not in opened


def test_find_port_error_lists_ports(fake_ports, monkeypatch):
    monkeypatch.setattr(ports, "get_nodes", lambda name: [])
    with pytest.raises(ConnectionError, match="COM9, COM5"):
        ports.find_port()


def test_settings_merge_order(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"port": "COM1", "poll_hz": 2, "unknown": 1}))
    (tmp_path / "local.json").write_text(json.dumps({"port": "COM9"}))

    assert config.load_settings(config_dir=tmp_path, env={}).port == "COM9"
    assert config.load_settings(config_dir=tmp_path, env={"FLOW_COM_PORT": "COM5"}).port == "COM5"
    s = config.load_settings({"port": "COM7", "simulate": None}, config_dir=tmp_path, env={"FLOW_COM_PORT": "COM5"})
    assert (s.port, s.poll_hz, s.simulate) == ("COM7", 2, False)


def test_settings_defaults_without_files(tmp_path):
    assert config.load_settings(config_dir=tmp_path, env={}) == config.Settings()


def test_simulator_config(tmp_path):
    path = tmp_path / "simulator.json"
    path.write_text(json.dumps({"tau_s": 0.5, "channels": [
        {"address": 4, "gas": "O2", "capacity": 10, "unit": "mln/min", "serial": "M24207457D"},
        {"address": 7, "gas": "H2", "capacity": 5}]}))
    options = config.load_simulator(path)
    assert options["tau"] == 0.5 and "noise" not in options
    bus = SimBus(**options)
    channels = bus.open()
    assert [(c.address, c.fluid, c.capacity, c.unit, c.serial) for c in channels] == [
        (4, "O2", 10.0, "mln/min", "M24207457D"), (7, "H2", 5.0, "mln/min", "SIM-7-H2")]
    assert config.load_simulator(tmp_path / "missing.json") == {}


def test_simulator_config_rejects_duplicate_addresses(tmp_path):
    path = tmp_path / "simulator.json"
    path.write_text(json.dumps({"channels": [{"address": 4, "gas": "O2", "capacity": 10},
                                             {"address": 4, "gas": "Ar", "capacity": 10}]}))
    with pytest.raises(ValueError):
        config.load_simulator(path)


def test_shipped_simulator_config_matches_the_lab_bus():
    channels = SimBus(**config.load_simulator()).open()
    assert [c.address for c in channels] == [4, 5, 6]


def test_channels_roundtrip(tmp_path):
    path = tmp_path / "channels.json"
    channels = {"M24207457D": config.ChannelConfig(alias="O2 line", gas="O2", color="#1f77b4", max_flow=5.0)}
    config.save_channels(channels, path)
    assert config.load_channels(path) == channels
