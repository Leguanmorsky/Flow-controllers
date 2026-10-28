"""Vacuum model, card client (catalog guard, HTTP) and the simulated card. Never the real card."""

import socket
import threading
import time

import pytest

from flowapp.core import card as rpc
from flowapp.core.card import CardClient, CardCommandError, CardError, CardLocked, CardReplyError, InterlockError
from flowapp.core.card_sim import SimCard
from flowapp.core.http_mock import MockCardServer
from flowapp.core.vacuum import (VALVE_BY_NAME, VacuumState, chamber_pressure, interlock_reason, parse_register,
                                 pump_path_open, to_sccm, valid_pressure)


def reg(*names, supply=False):
    return sum(1 << VALVE_BY_NAME[n].bit for n in names) | (1 << 31 if supply else 0)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SpyTransport:
    def __init__(self):
        self.posts = []

    def post(self, payload):
        self.posts.append(payload)
        return [{"jsonrpc": "2.0", "id": item["id"], "result": True} for item in payload]

    def close(self):
        pass


# --- model --------------------------------------------------------------------------------------

def test_parse_register_and_supply_bit():
    valves = parse_register(f"{reg('FV1', 'V04', 'V19', supply=True):08x}")
    assert valves["FV1"] and valves["V04"] and valves["V19"] and not valves["V06"]
    state = VacuumState(t=0, register=reg("V17", supply=True))
    assert state.valves["V17"] and state.supply_24v


@pytest.mark.parametrize("open_valves, valve, blocked", [
    ((), "V06", False),
    (("FV1",), "V06", True),
    (("V14",), "V06", True),
    (("V06",), "FV1", True),
    (("V06",), "V10", True),
    (("V06",), "V05", True),
    (("V14",), "V05", True),
    (("V05",), "V14", True),
    (("V15", "V16"), "V14", True),
    (("V15",), "V14", False),
    (("V14", "V15"), "V16", True),
    (("V14", "V16"), "V15", True),
    (("V14",), "V15", False),
    (("V06",), "V06", False),           # already open: closing is always allowed
    (("V06", "FV1"), "FV1", False),
])
def test_interlocks_follow_the_web_page(open_valves, valve, blocked):
    valves = parse_register(reg(*open_valves))
    assert (interlock_reason(valves, valve) is not None) == blocked


def test_pressure_helpers():
    assert valid_pressure(2e-6) == 2e-6 and valid_pressure({"value": 3e-5}) == 3e-5
    assert valid_pressure(None) is None and valid_pressure(0) is None and valid_pressure(float("nan")) is None
    assert valid_pressure(True) is None and valid_pressure("1e-5") is None
    state = VacuumState(t=0, pressures={"chamber_frg": None, "chamber_img": 4e-7})
    assert chamber_pressure(state) == 4e-7
    assert to_sccm(0.5, "ln/min") == 500 and to_sccm(2.0, "mln/min") == 2.0 and to_sccm(0.3, "sccm") == 0.3
    assert pump_path_open(parse_register(reg("V16", "V17", "V04", "FV1")), ["V16", "V17", "V04", "FV1"])
    assert not pump_path_open({}, ["V17"])


# --- catalog guard --------------------------------------------------------------------------------

@pytest.mark.parametrize("method, params", [
    ("chbr.prs?", {"value": 0}), ("chbr.prs?", {"value": 3}), ("sem.prs?", {"value": 1}),
    ("chbr.stat?", None), ("sem.stat?", None), ("tsc.wrd", ["40", "", "4"]), ("tsc.wrd", ["64", "", "2"]),
])
def test_read_commands_are_allowed(method, params):
    assert rpc.classify(method, params) == rpc.READ


@pytest.mark.parametrize("request_", [
    rpc.valve_open("V17"), rpc.valve_close("FV1"), rpc.power_save(), rpc.valve_unlock("VV1"),
    rpc.decontaminator(True), rpc.chamber("vent"), rpc.gun("ions"), rpc.gun_pump(2.5), rpc.beam(False),
])
def test_control_commands_are_in_the_catalog(request_):
    assert rpc.classify(request_.method, request_.params) == rpc.CONTROL


@pytest.mark.parametrize("method, params", [
    ("chbr.prs?", {"value": 4}), ("sem.prs?", {"value": "0"}), ("chbr.stat?", {"value": 1}),
    ("tsc.wrd", ["40", "", "2"]), ("tsc.wrd", ["2", "", "2"]), ("tsc.wrd", ["32", "80000080", "4"]),   # V07
    ("tsc.wrd", ["32", "ffffffff", "4"]), ("tsc.wrd", [40, "", 4]), ("chbr.reboot", None),
    ("sem.pump", {"value": 25 * 3600}), ("sem.pump", {"value": -1}), ("sem.beam", {"value": 1}),
    ("adc.get", [0]), ("chbr.cmd", ["x", 0]), ("chbr.vent", {"value": 1}),
])
def test_anything_else_is_refused(method, params):
    with pytest.raises(CardCommandError):
        rpc.classify(method, params)


def test_nothing_is_sent_when_a_request_is_refused():
    spy = SpyTransport()
    client = CardClient(spy, allow_control=False)
    with pytest.raises(CardLocked):
        client.call([rpc.pressure("chamber_frg"), rpc.chamber("vent")])
    with pytest.raises(CardCommandError):
        client.call([rpc.Request("tsc.wrd", ["36", "80000080", "4"])])
    with pytest.raises(CardLocked):
        client.open_valve("V17")
    assert spy.posts == []
    client.call([rpc.pressure("gun")])
    assert len(spy.posts) == 1


def test_open_valve_checks_the_interlocks_before_sending():
    card = SimCard(seed=1)
    client = CardClient(card, allow_control=True)
    with pytest.raises(InterlockError, match="V06"):
        client.open_valve("V06")        # FV1 and V10 are open
    assert not any(m == "tsc.wrd" and p[0] == "32" for m, p in card.requests)


# --- simulated card -------------------------------------------------------------------------------

def test_sim_flow_gives_the_lab_pressure():
    clock = FakeClock()
    card = SimCard(seed=1, clock=clock)
    client = CardClient(card)
    base = client.read_all().pressures["chamber_frg"]
    assert 3e-6 < base < 3e-5
    card.set_flow(0.01)         # 1 % of a 1 sccm MFC
    clock.t += 60
    p = client.read_all().pressures["chamber_frg"]
    assert 5e-4 < p < 1.5e-3


def test_sim_closing_the_pump_path_makes_the_pressure_rise():
    clock = FakeClock()
    card = SimCard(seed=1, clock=clock)
    client = CardClient(card, allow_control=True)
    card.set_flow(0.01)
    clock.t += 60
    before = client.read_all().pressures["chamber_frg"]
    client.close_valve("V17")
    client.close_valve("V19")       # else the ion pumps take over part of the gas
    clock.t += 30
    after = client.read_all().pressures["chamber_frg"]
    assert after > 3 * before


def test_sim_vent_and_gauge_ranges():
    clock = FakeClock()
    card = SimCard(seed=1, clock=clock)
    client = CardClient(card, allow_control=True)
    client.chamber("vent")
    clock.t += 20
    state = client.read_all(with_status=True)
    assert state.pressures["chamber_frg"] > 5e4
    assert state.pressures["chamber_img"] is None and state.pressures["chamber_hfig"] is None
    assert state.chamber_status == "vented"


def test_sim_valve_supply_and_power_save():
    card = SimCard(seed=1)
    client = CardClient(card, allow_control=True)
    register = client.open_valve("V05")
    assert parse_register(register)["V05"] and register >> 31 & 1
    assert not client.power_save() >> 31 & 1
    assert parse_register(client.read_register())["V05"]


def test_sim_faults_and_errors():
    clock = FakeClock()
    card = SimCard(seed=1, clock=clock)
    client = CardClient(card, allow_control=True)
    card.set_fault("valves_ignored")
    assert parse_register(client.close_valve("V17"))["V17"]        # the card did not take it
    card.set_fault("valves_ignored", False)
    card.set_fault("gauge_off")
    assert client.read_all().pressures["chamber_frg"] is None
    client.gun("vent")
    clock.t += 20
    with pytest.raises(CardReplyError, match="beam interlock"):
        client.beam(True)
    card.set_fault("unreachable")
    with pytest.raises(ConnectionError):
        client.read_all()
    card.set_fault("unreachable", False)
    assert client.ups() == (True, True)
    assert client.decontaminator(True) is True and client.decontaminator(False) is False


# --- HTTP transport against the localhost mock ------------------------------------------------------

@pytest.fixture
def mock_server():
    servers = []

    def start(**options):
        server = MockCardServer(SimCard(seed=2), **options).start()
        servers.append(server)
        return server
    yield start
    for server in servers:
        server.stop()


def test_http_batch_replies_are_matched_by_id(mock_server):
    server = mock_server(shuffle=True)
    client = CardClient(rpc.HttpTransport(server.address))
    for _ in range(5):
        state = client.read_all(with_status=True)
        assert 1e-6 < state.pressures["chamber_frg"] < 1e-4
        assert state.pressures["gun"] < 1e-7 and state.pressures["column"] > 1e-7
        assert state.valves["V17"] and state.chamber_status == "ready"
    client.close()


def test_http_object_results_and_reconnect(mock_server):
    server = mock_server(objects=True, close_every=1)
    client = CardClient(rpc.HttpTransport(server.address))
    for _ in range(4):
        assert client.read_all().pressures["chamber_frg"] > 0
    assert server.connections >= 4
    client.close()


def test_http_unreachable_and_timeout(mock_server):
    server = mock_server()
    address = server.address
    server.stop()
    with pytest.raises(CardError):
        CardClient(rpc.HttpTransport(address, timeout=0.5)).read_all()

    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(1)
    accepted = []
    threading.Thread(target=lambda: accepted.append(silent.accept()), daemon=True).start()
    started = time.monotonic()
    with pytest.raises(CardError, match="No answer"):
        CardClient(rpc.HttpTransport(f"127.0.0.1:{silent.getsockname()[1]}", timeout=0.3)).read_all()
    assert time.monotonic() - started < 2
    silent.close()


@pytest.mark.parametrize("address, expected", [
    ("10.0.0.5", ("10.0.0.5", 80, "/jsonrpc")),
    ("10.0.0.5:8080", ("10.0.0.5", 8080, "/jsonrpc")),
    ("http://10.0.0.5/indexsvg.html", ("10.0.0.5", 80, "/jsonrpc")),
    ("http://card.lab/ui/", ("card.lab", 80, "/ui/jsonrpc")),
])
def test_parse_address(address, expected):
    assert rpc.parse_address(address) == expected


def test_parse_address_rejects_empty():
    with pytest.raises(CardError):
        rpc.parse_address("  ")


def test_cli_card_probe_on_the_simulated_card(capsys):
    from flowapp import __main__ as cli
    assert cli.main(["--card-probe", "--sim"]) == 0
    out = capsys.readouterr().out
    assert "read-only" in out and "Open valves: FV1" in out and "Latency" in out
