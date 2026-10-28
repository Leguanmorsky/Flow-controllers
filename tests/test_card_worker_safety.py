"""Card worker thread and gas-safety supervisor (simulated card and hand-made states only)."""

import threading
import time

import pytest

from flowapp.config import CardConfig, load_card_config, save_local
from flowapp.core.card import CardClient
from flowapp.core.card_sim import SimCard
from flowapp.core.card_worker import CardWorker
from flowapp.core.safety import GasBlocked, GasSupervisor
from flowapp.core.vacuum import VALVE_BY_NAME, VacuumState, parse_register

PATH = ("V16", "V17", "V04", "FV1")


def reg(*names):
    return sum(1 << VALVE_BY_NAME[n].bit for n in names)


def wait_for(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


# --- worker -----------------------------------------------------------------------------------------

def test_worker_polls_and_marks_stale_data():
    card = SimCard(seed=3)
    worker = CardWorker(CardClient(card), poll_hz=20, stale_s=0.3)
    states = []
    worker.add_listener(states.append)
    worker.start()
    try:
        assert wait_for(lambda: len(states) >= 3)
        assert states[-1].ok and states[-1].pressures["chamber_frg"] > 0 and states[-1].valves["V17"]
        assert wait_for(lambda: states[-1].chamber_status == "ready")
        card.set_fault("unreachable")
        assert wait_for(lambda: not states[-1].ok)
        assert not states[-1].stale or states[-1].age_s > 0.3
        assert wait_for(lambda: states[-1].stale)
        card.set_fault("unreachable", False)
        assert wait_for(lambda: states[-1].ok and not states[-1].stale)
    finally:
        worker.stop()
    assert not worker.is_alive()


def test_worker_opens_a_valve_then_drops_to_12_volt():
    card = SimCard(seed=3)
    worker = CardWorker(CardClient(card, allow_control=True), poll_hz=20)
    worker.start()
    try:
        register = worker.open_valve("V05").result(timeout=2)
        assert parse_register(register)["V05"] and card.supply_24v
        assert wait_for(lambda: not card.supply_24v, timeout=3)
        assert parse_register(card.register)["V05"]
        assert parse_register(worker.close_valve("V05").result(timeout=2))["V05"] is False
    finally:
        worker.stop()


def test_worker_stop_finishes_a_pending_power_save():
    card = SimCard(seed=3)
    worker = CardWorker(CardClient(card, allow_control=True), poll_hz=20)
    worker.start()
    worker.open_valve("V05").result(timeout=2)
    worker.stop()
    assert not card.supply_24v


# --- supervisor ---------------------------------------------------------------------------------------

class Harness:
    def __init__(self, card_present=True, **config):
        self.zeros = []
        self.events = []
        self.gas = False
        self.supervisor = GasSupervisor(CardConfig(**config), self.zeros.append, lambda: self.gas,
                                        on_event=lambda level, msg: self.events.append((level, msg)),
                                        card_present=card_present)

    def state(self, p=1e-5, valves=PATH, ok=True, stale=False):
        state = VacuumState(t=time.time(), ok=ok, error="" if ok else "timeout", stale=stale, age_s=3.0 if stale else 0,
                            pressures={"chamber_frg": p} if ok else {}, register=reg(*valves) if ok else None)
        self.supervisor.on_state(state)
        return state


def test_without_a_card_the_vacuum_rules_are_off():
    h = Harness(card_present=False)
    status = h.supervisor.status()
    assert status.allowed and status.level == "warning" and "off" in status.reason
    h.supervisor.check_setpoint(0.5)
    h.gas = True
    h.state(p=10.0, valves=())
    assert h.zeros == [] and not h.supervisor.before_vent("vent the chamber")


def test_gas_allowed_only_while_pumped():
    h = Harness()
    with pytest.raises(GasBlocked, match="no pressure data yet"):
        h.supervisor.check_setpoint(0.1)
    h.state()
    assert h.supervisor.status().allowed
    h.supervisor.check_setpoint(0.1)
    h.supervisor.check_setpoint(0)              # 0 is always allowed
    h.state(valves=("V16", "V17", "FV1"))
    with pytest.raises(GasBlocked, match="V04") as blocked:
        h.supervisor.check_setpoint(0.1)
    assert blocked.value.overridable
    h.state(p=0.5)
    with pytest.raises(GasBlocked, match="not pumped"):
        h.supervisor.check_setpoint(0.1)
    h.gas = True                                # the pressure of our own gas does not block changes
    h.supervisor.check_setpoint(0.1)
    h.gas = False
    h.supervisor.set_override("block_unpumped")
    h.supervisor.check_setpoint(0.1)
    assert h.supervisor.status().level == "warning"
    assert any("overridden" in msg for _, msg in h.events)


def test_closing_the_pump_path_zeroes_the_flows_once():
    h = Harness()
    h.gas = True
    h.state()
    h.state(valves=("V16", "V17", "FV1"))
    assert h.zeros == ["pumping path closed (V04)"]
    h.state(valves=("V16", "V17", "FV1"))
    assert len(h.zeros) == 1
    h.state()
    h.supervisor.set_override("path_zero")
    h.state(valves=("V17",))
    assert len(h.zeros) == 1


def test_pressure_trip_latches_until_acknowledged():
    h = Harness(p_max_pa=1.0)
    h.gas = True
    h.state()
    h.state(p=2.0)
    assert len(h.zeros) == 1 and "above the limit" in h.zeros[0]
    h.state(p=3.0)
    assert len(h.zeros) == 1
    h.state(p=1e-5)
    with pytest.raises(GasBlocked) as blocked:
        h.supervisor.check_setpoint(0.1)
    assert blocked.value.rule == "trip" and not blocked.value.overridable
    h.supervisor.acknowledge_trip()
    h.supervisor.check_setpoint(0.1)


def test_stale_data_zeroes_once_per_outage():
    h = Harness()
    h.gas = True
    h.state()
    h.state(ok=False)
    assert h.zeros == []
    h.state(ok=False, stale=True)
    h.state(ok=False, stale=True)
    assert len(h.zeros) == 1 and "no pressure data" in h.zeros[0]
    h.state()
    h.state(ok=False, stale=True)
    assert len(h.zeros) == 2


def test_vent_and_valve_rules():
    h = Harness()
    h.state()
    assert not h.supervisor.before_vent("vent the chamber") and not h.supervisor.valve_needs_confirmation()
    h.gas = True
    assert h.supervisor.valve_needs_confirmation()
    assert h.supervisor.before_vent("vent the chamber") and h.zeros == ["before you vent the chamber"]
    assert not h.supervisor.before_vent("vent the chamber", override=True)
    h.supervisor.set_override("confirm_valves")
    assert not h.supervisor.valve_needs_confirmation()
    h.supervisor.reset()
    assert h.supervisor.valve_needs_confirmation() and not h.supervisor.overrides


def test_card_config_local_overrides(tmp_path):
    (tmp_path / "card.json").write_text('{"_help": "x", "p_max_pa": 0.5, "pump_path": ["V17"]}')
    save_local({"port": "COM7"}, tmp_path)
    assert load_card_config(tmp_path).address == ""
    save_local({"card_address": "10.0.0.5", "card_control_enabled": True}, tmp_path)
    config = load_card_config(tmp_path)
    assert (config.address, config.control_enabled, config.p_max_pa, config.pump_path) == \
        ("10.0.0.5", True, 0.5, ["V17"])
    assert '"port": "COM7"' in (tmp_path / "local.json").read_text()
