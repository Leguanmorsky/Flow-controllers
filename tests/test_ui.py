"""The main window driven against the simulator (offscreen, nothing is sent to hardware)."""

import csv
import json
import sys
import threading

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from flowapp.config import ASSETS_DIR, CardConfig, Settings, save_local
from flowapp.core.simulator import SimBus
from flowapp.ui import dialogs
from flowapp.ui import main_window as main_window_module
from flowapp.ui.bridge import SIM_PORT
from flowapp.ui.main_window import MainWindow


def no_dialog(*args, **kwargs):
    raise AssertionError("unexpected dialog")


def make_window(qtbot, tmp_path, factory, make_shortcut=None, **settings):
    qsettings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    w = MainWindow(Settings(poll_hz=20, history_minutes=1, **settings), bus_factory=factory,
                   channels_path=tmp_path / "channels.json", qsettings=qsettings, make_shortcut=make_shortcut,
                   card_config_loader=lambda: CardConfig(),      # never a real card in tests
                   local_saver=lambda updates: save_local(updates, tmp_path))
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", no_dialog)
    monkeypatch.setattr(dialogs, "confirm", no_dialog)
    monkeypatch.setattr(dialogs, "ask_zero_failed", no_dialog)
    buses = []

    def factory(port):
        assert port == SIM_PORT
        bus = SimBus(tau=0.05, noise=0.0)
        buses.append(bus)
        return bus

    w = make_window(qtbot, tmp_path, factory)
    assert w.stack.currentWidget() is w.start and not w.bar.isVisible()
    w.start.test_button.click()
    qtbot.waitUntil(lambda: len(w.cards) == 3 and w.bridge.last_poll is not None)
    qtbot.waitUntil(lambda: w.card.latest is not None)
    w.sim = buses[0]
    yield w
    if w.bridge.is_connected:
        w.bridge.force_disconnect()


def card_ready(window, address):
    return window.cards[address].device_setpoint is not None


def test_connect_shows_cards(window):
    assert sorted(window.cards) == [4, 5, 6]
    assert window.stack.currentWidget() is window.tabs and window.bar.isVisible()
    assert "[TEST MODE]" in window.windowTitle()
    assert window.test_strip.isVisible() and window.zero_action.isEnabled()
    assert window.sim_menu.menuAction().isVisible()
    assert "TEST MODE: 3 simulated instrument(s), no gas flows." in window.log_text()


def test_start_page_connects_to_the_chosen_port(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", no_dialog)
    opened = []

    def factory(port):
        opened.append(port)
        raise ConnectionError(f"No Bronkhorst device answered on {port}.")

    w = make_window(qtbot, tmp_path, factory)
    combo = w.start.port_combo
    assert combo.itemData(0) == "auto" and SIM_PORT not in [combo.itemData(i) for i in range(combo.count())]
    assert w.start.connect_button.isEnabled() and w.test_strip.isHidden()
    w.start.connect_button.click()
    assert opened == ["auto"]
    qtbot.waitUntil(lambda: "Connection failed" in w.start.status_label.text())
    assert w.stack.currentWidget() is w.start and w.start.connect_button.isEnabled()


def test_test_session_cannot_reach_real_instruments(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", no_dialog)
    opened = []
    w = make_window(qtbot, tmp_path, lambda port: opened.append(port) or SimBus(noise=0.0), simulate=True)
    assert not w.start.connect_button.isEnabled() and not w.start.test_only_note.isHidden()
    assert w.test_strip.isVisible() and "[TEST MODE]" in w.windowTitle()
    w.bridge.connect_to("COM9")                  # refused before any port is opened
    assert opened == [] and not w.bridge.is_connected
    assert "real instruments are disabled" in w.log_text()
    w.start.test_button.click()
    qtbot.waitUntil(lambda: w.bridge.is_connected)
    assert opened == [SIM_PORT]
    w.close()


def test_command_line_mode_skips_the_start_page(qtbot, tmp_path):
    w = make_window(qtbot, tmp_path, lambda port: SimBus(noise=0.0), simulate=True, auto_connect=True)
    qtbot.waitUntil(lambda: w.bridge.is_connected and w.stack.currentWidget() is w.tabs)
    w.close()


def test_desktop_shortcut_is_created_once(qtbot, tmp_path):
    calls = []
    w = make_window(qtbot, tmp_path, lambda port: SimBus(), make_shortcut=lambda: calls.append(1) or "X.lnk")
    qtbot.waitUntil(lambda: "Desktop shortcut created: X.lnk" in w.log_text(), timeout=4000)
    w.close()
    w2 = make_window(qtbot, tmp_path, lambda port: SimBus(), make_shortcut=lambda: calls.append(2) or "X.lnk")
    qtbot.wait(1500)
    assert calls == [1]
    w2.create_shortcut()                         # Help > Create desktop shortcut
    qtbot.waitUntil(lambda: calls == [1, 2])
    w2.close()


def test_instrument_report(window, qtbot, monkeypatch, tmp_path):
    shown = []
    monkeypatch.setattr(dialogs, "show_text", lambda parent, title, text, path: shown.append((text, path)))
    monkeypatch.setattr(main_window_module, "save_report", lambda lines: tmp_path / "report.txt")
    window.report_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1)
    text, path = shown[0]
    assert text.startswith("TEST MODE") and "Fluid name (DDE 25)" in text and path == tmp_path / "report.txt"


def test_logo_files():
    from PySide6.QtGui import QIcon
    sizes = [s.width() for s in QIcon(str(ASSETS_DIR / "logo.ico")).availableSizes()]
    assert 16 in sizes and 256 in sizes
    assert (ASSETS_DIR / "logo.png").stat().st_size > 1000


def test_enter_in_spinbox_sends_setpoint(window, qtbot):
    card = window.cards[4]
    card.spin.setFocus()
    card.spin.setValue(2.5)
    qtbot.keyClick(card.spin, Qt.Key_Return)
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == 2.5)
    qtbot.waitUntil(lambda: "O2 setpoint → 2.500 mln/min (user)" in window.log_text())


def test_slider_release_sends_once(window, qtbot):
    card = window.cards[5]
    sent = []
    card.setpoint_requested.connect(lambda a, v: sent.append(v))
    card.slider.setSliderDown(True)
    for position in (100, 300, 500):
        card.slider.setSliderPosition(position)
    card.slider.setSliderDown(False)
    assert sent == [5.0]
    qtbot.waitUntil(lambda: window.sim._setpoint[5] == 5.0)


def test_plus_minus_buttons_step_from_device_setpoint(window, qtbot):
    window.bridge.set_setpoint(6, 1.0)
    qtbot.waitUntil(lambda: window.cards[6].device_setpoint == 1.0)
    window.cards[6].plus_button.click()
    qtbot.waitUntil(lambda: window.sim._setpoint[6] == pytest.approx(1.1))
    qtbot.waitUntil(lambda: window.cards[6].device_setpoint == pytest.approx(1.1))
    window.cards[6].minus_button.click()
    qtbot.waitUntil(lambda: window.sim._setpoint[6] == pytest.approx(1.0))


def test_all_to_zero_cancels_ramps(window, qtbot):
    window.bridge.set_setpoint(4, 3.0)
    window.bridge.start_ramp(5, 10.0, rate_per_min=1.0)
    qtbot.waitUntil(lambda: window.bridge.ramp(5) is not None)
    window.bar.zero_button.click()
    qtbot.waitUntil(lambda: window.bridge.ramp(5) is None and all(v == 0 for v in window.sim._setpoint.values()))
    qtbot.waitUntil(lambda: "ALL TO 0: ramps cancelled, every flow set to 0." in window.log_text())


def test_ramp_from_card_finishes(window, qtbot):
    card = window.cards[4]
    qtbot.waitUntil(lambda: card_ready(window, 4))
    card.ramp_toggle.click()
    card.ramp_target.setValue(1.0)
    card.ramp_rate.setValue(120.0)          # 2 mln/min per second
    card.ramp_start.click()
    qtbot.waitUntil(lambda: window.bridge.ramp(4) is not None)
    qtbot.waitUntil(lambda: window.bridge.ramp(4) is None and window.sim._setpoint[4] == 1.0, timeout=3000)
    qtbot.waitUntil(lambda: "O2: ramp finished at 1.000 mln/min." in window.log_text())


def test_manual_setpoint_cancels_ramp(window, qtbot):
    window.bridge.start_ramp(4, 10.0, rate_per_min=1.0)
    qtbot.waitUntil(lambda: window.bridge.ramp(4) is not None)
    window.bridge.set_setpoint(4, 2.0)
    qtbot.waitUntil(lambda: window.bridge.ramp(4) is None and window.sim._setpoint[4] == 2.0)


def test_analog_mode_banner_and_switch(window, qtbot, monkeypatch):
    asked = []
    monkeypatch.setattr(dialogs, "confirm", lambda *args: asked.append(args) or True)
    card = window.cards[5]
    window.sim.set_fault("analog_mode", 5)
    qtbot.waitUntil(lambda: not card.mode_banner.isHidden())
    assert "Analog input" in card.mode_banner.label.text()
    qtbot.waitUntil(lambda: "switched to “Analog input” mode" in window.log_text())
    card.mode_banner.button.click()
    assert len(asked) == 1
    qtbot.waitUntil(lambda: card.mode_banner.isHidden() and window.sim._mode[5] == 0)


def test_unplugged_cable_shows_errors_without_dialogs(window, qtbot):
    window.sim.set_fault("unplugged")
    qtbot.waitUntil(lambda: all(not c.error_banner.isHidden() for c in window.cards.values()))
    assert "O2: no answer (timeout)" in window.log_text()
    window.sim.set_fault("unplugged", on=False)
    qtbot.waitUntil(lambda: all(c.error_banner.isHidden() for c in window.cards.values()))
    assert "O2 is answering again." in window.log_text()


def test_deviation_warning(window, qtbot):
    for watch in window.bridge._watches.values():
        watch.delay_s = 0.2
    window.sim.set_fault("no_gas", 6)
    window.bridge.set_setpoint(6, 5.0)
    qtbot.waitUntil(lambda: not window.cards[6].deviation_banner.isHidden())
    assert "He: flow stays below the setpoint (gas supply closed?)." in window.log_text()


def test_max_flow_limit_from_settings_dialog(window, qtbot, monkeypatch, tmp_path):
    def fill_in(dialog):
        dialog.alias_edit.setText("Oxygen line")
        dialog.limit_check.setChecked(True)
        dialog.limit_spin.setValue(5.0)
        return QDialog.Accepted

    monkeypatch.setattr(dialogs.ChannelSettingsDialog, "exec", fill_in)
    window.cards[4].settings_button.click()
    saved = json.loads((tmp_path / "channels.json").read_text(encoding="utf-8"))
    assert saved["SIM-4-O2"]["alias"] == "Oxygen line" and saved["SIM-4-O2"]["max_flow"] == 5.0
    assert window.cards[4].name_label.text() == "Oxygen line"
    window.bridge.set_setpoint(4, 8.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == 5.0)
    assert "Oxygen line: 8.000 mln/min limited to 5.000 mln/min (max flow)." in window.log_text()


def test_percent_mode(window, qtbot):
    window.bridge.set_setpoint(4, 5.0)
    qtbot.waitUntil(lambda: window.cards[4].device_setpoint == 5.0)
    window.pct_action.setChecked(True)
    card = window.cards[4]
    assert card.spin.suffix() == " %"
    qtbot.waitUntil(lambda: card.setpoint_label.text() == "SP 50.00")
    card.spin.setFocus()
    card.spin.setValue(25.0)
    qtbot.keyClick(card.spin, Qt.Key_Return)
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == pytest.approx(2.5))


def test_close_sets_all_flows_to_zero(window, qtbot):
    window.bridge.set_setpoint(4, 3.0)
    window.bridge.set_setpoint(6, 1.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[6] == 1.0)
    worker = window.bridge.worker
    window.close()
    assert all(v == 0 for v in window.sim._setpoint.values())
    assert not window.bridge.is_connected and not worker.is_alive()


def test_disconnect_zeroes_and_stops_threads(window, qtbot):
    window.bridge.set_setpoint(5, 2.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[5] == 2.0)
    window.bar.disconnect_button.click()
    assert not window.bridge.is_connected and window.cards == {}
    assert window.sim._setpoint[5] == 0.0
    assert not any(t.name == "InstrumentWorker" and t.is_alive() for t in threading.enumerate())
    assert window.stack.currentWidget() is window.start


def test_zero_failure_asks_before_disconnecting(window, qtbot, monkeypatch):
    answers = ["cancel", "anyway"]
    monkeypatch.setattr(dialogs, "ask_zero_failed", lambda parent, error, action: answers.pop(0))
    window.sim.set_fault("unplugged")
    window.bar.disconnect_button.click()
    assert window.bridge.is_connected        # the user cancelled
    window.bar.disconnect_button.click()
    assert not window.bridge.is_connected
    assert "Disconnected without confirming that all flows are 0." in window.log_text()


def test_exports(window, qtbot, tmp_path):
    qtbot.waitUntil(lambda: window.graph.sample_count() >= 5)
    window.graph.export_csv(tmp_path / "data.csv")
    rows = list(csv.reader(open(tmp_path / "data.csv", encoding="utf-8")))
    assert rows[0][2] == "O2 measure [mln/min]" and len(rows) >= 6
    assert window.graph.export_png(tmp_path / "graph.png")
    assert (tmp_path / "graph.png").stat().st_size > 1000


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console handler")
def test_closing_the_console_window_zeroes_flows(window, qtbot):
    from flowapp.ui.app import _zero_when_console_closes
    window.bridge.set_setpoint(4, 3.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == 3.0)
    _zero_when_console_closes(window)
    assert window._console_handler(0) == 0          # Ctrl+C is left alone
    assert window.sim._setpoint[4] == 3.0
    window._console_handler(2)                      # CTRL_CLOSE_EVENT
    assert all(v == 0 for v in window.sim._setpoint.values())
    import ctypes
    ctypes.windll.kernel32.SetConsoleCtrlHandler(window._console_handler, False)


def test_theme_switch_keeps_working(window, qtbot):
    window.apply_theme("dark")
    assert window.theme.dark
    window.apply_theme("light")
    assert not window.theme.dark
    window.bridge.set_setpoint(4, 1.0)
    qtbot.waitUntil(lambda: window.cards[4].device_setpoint == 1.0)


# --- vacuum card in the Flows tab (simulated card) ----------------------------------------------------

def test_pressure_panel_and_strip(window, qtbot):
    assert window.card.mode == "sim" and window.card.control_allowed
    assert "TEST MODE: simulated vacuum card and chamber." in window.log_text()
    qtbot.waitUntil(lambda: window.graph.pressures is not None and len(window.graph.pressures) >= 3)
    qtbot.waitUntil(lambda: window.graph._curve("pressure", "chamber_frg").isVisible())
    assert window.graph.pressure_plot.isVisible() and window.graph.mix_plot.isVisible()
    assert "Simulated vacuum card" in window.strip.card_label.text()
    assert "Pa" in window.strip.values["chamber_frg"][1].text()
    assert "Gas allowed" in window.strip.gas_label.text()
    window.graph.set_slots(("valve", "off"))
    assert window.graph.valve_plot.isVisible() and not window.graph.pressure_plot.isVisible()
    assert not window.graph.gauge_checks["chamber_frg"].isVisible()
    window.graph.set_slots(("pressure", "valve"))
    assert window.graph.pressure_plot.isVisible() and not window.graph.mix_plot.isVisible()


def test_simulated_chamber_sees_the_flows(window, qtbot):
    qtbot.waitUntil(lambda: window.card.latest.pressures["chamber_frg"] is not None)
    base = window.card.latest.pressures["chamber_frg"]
    window._request_setpoint(4, 2.0)
    qtbot.waitUntil(lambda: window.card.latest.pressures["chamber_frg"] > 100 * base, timeout=10000)


def test_closing_the_pump_path_zeroes_the_flows(window, qtbot):
    window._request_setpoint(4, 2.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == 2.0)
    qtbot.waitUntil(lambda: window.bridge.gas_flowing())
    window.card.close_valve("V04")
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == 0, timeout=5000)
    qtbot.waitUntil(lambda: "Gas safety: every flow set to 0, pumping path closed (V04)." in window.log_text())
    qtbot.waitUntil(lambda: "pumping path closed (V04)" in window.strip.gas_label.text())


def test_gas_blocked_asks_and_override_sends(window, qtbot, monkeypatch):
    window.card.close_valve("V17")
    qtbot.waitUntil(lambda: not window.card.gas_status().allowed)
    answers = [None, "override"]
    asked = []
    monkeypatch.setattr(dialogs, "gas_blocked", lambda parent, blocked: (asked.append(blocked), answers.pop(0))[1])
    window._request_setpoint(5, 1.0)
    assert len(asked) == 1 and "V17" in asked[0].reason and window.sim._setpoint[5] == 0
    window._request_setpoint(5, 1.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[5] == 1.0)
    assert "block_unpumped" in window.card.supervisor.overrides
    assert "overridden" in window.strip.gas_label.text()
    window._request_setpoint(5, 0.5)            # lowering never asks
    qtbot.waitUntil(lambda: window.sim._setpoint[5] == 0.5)


def test_pressure_trip_zeroes_and_needs_acknowledging(window, qtbot, monkeypatch):
    window.card.supervisor.config.p_max_pa = 0.02
    window._request_setpoint(4, 3.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == 0 and window.strip.ack_button.isVisible(), timeout=10000)
    qtbot.waitUntil(lambda: "above the limit" in window.log_text())
    seen = []
    monkeypatch.setattr(dialogs, "gas_blocked", lambda parent, blocked: (seen.append(blocked.rule), "acknowledge")[1])
    window._request_setpoint(4, 0.001)          # right after the zero: must not pass as "lowering"
    assert seen == ["trip"] and window.sim._setpoint[4] == 0
    window.card.supervisor.config.p_max_pa = 1.0
    window.card.acknowledge_trip()
    assert window.card.gas_status().rule != "trip" and not window.strip.ack_button.isVisible()
    qtbot.waitUntil(lambda: window.card.gas_status().allowed, timeout=10000)     # once the chamber recovered


def test_card_outage_in_test_mode(window, qtbot):
    window._request_setpoint(6, 1.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[6] == 1.0 and window.bridge.gas_flowing())
    window.card.set_sim_fault("unreachable", True)
    qtbot.waitUntil(lambda: "no data" in window.strip.card_label.text())
    qtbot.waitUntil(lambda: window.sim._setpoint[6] == 0, timeout=6000)
    qtbot.waitUntil(lambda: "no pressure data" in window.log_text())
    window.card.set_sim_fault("unreachable", False)
    qtbot.waitUntil(lambda: "Vacuum card answering again." in window.log_text())


def test_csv_export_has_pressures(window, qtbot, tmp_path):
    qtbot.waitUntil(lambda: window.graph.sample_count() >= 5 and len(window.graph.pressures) >= 3)
    window.graph.export_csv(tmp_path / "data.csv")
    rows = list(csv.reader(open(tmp_path / "data.csv", encoding="utf-8")))
    assert "Chamber FRG [Pa]" in rows[0]
    column = rows[0].index("Chamber FRG [Pa]")
    assert any(row[column] for row in rows[1:])


def test_without_card_the_strip_says_so(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", no_dialog)

    class RealLikeBus(SimBus):     # a "real" bus: the bridge does not treat it as test mode
        pass

    from flowapp.ui import bridge as bridge_module
    monkeypatch.setattr(bridge_module, "SimBus", type("NotThis", (), {}))
    w = make_window(qtbot, tmp_path, lambda port: RealLikeBus(tau=0.05, noise=0.0), port="COM7", auto_connect=True)
    qtbot.waitUntil(lambda: len(w.cards) == 3)
    assert w.card.mode == "none" and not w.card.running
    assert "No vacuum card" in w.strip.card_label.text() and "protections are off" in w.strip.gas_label.text()
    w._request_setpoint(4, 1.0)
    qtbot.waitUntil(lambda: w.bridge.bus._setpoint[4] == 1.0)
    w.bridge.force_disconnect()


# --- Vacuum tab ----------------------------------------------------------------------------------------

def yes(*args, **kwargs):
    return True


def test_vacuum_tab_shows_the_valve_register(window, qtbot):
    window.tabs.setCurrentWidget(window.vacuum)
    v = window.vacuum
    qtbot.waitUntil(lambda: "open" in v.valve_rows["V17"][0].text())
    assert "closed" in v.valve_rows["V06"][0].text() and not v.valve_rows["V06"][1].isEnabled()   # interlock
    assert "V06" in v.diagram.valves["V06"].toolTip() and "Blocked" in v.diagram.valves["V06"].toolTip()
    assert v.diagram.path_items, "the pumping path is highlighted"
    assert "Pa" in v.pressure_labels["chamber_frg"][1].text() and v.lock_banner.isHidden()
    qtbot.waitUntil(lambda: "ready" in v.chamber_status.text())


def test_blocked_valve_is_not_sent(window, qtbot):
    window._valve_requested("V06")          # FV1 and V10 are open: no dialog, nothing sent
    assert "V06 not opened: To open V06" in window.log_text()
    assert not any(m == "tsc.wrd" and p[0] == "32" for m, p in window.card.sim_card.requests)


def test_open_and_close_a_valve(window, qtbot, monkeypatch):
    monkeypatch.setattr(dialogs, "confirm", yes)
    window.vacuum.valve_rows["V05"][1].click()
    qtbot.waitUntil(lambda: window.card.latest.valves.get("V05"))
    qtbot.waitUntil(lambda: "open" in window.vacuum.valve_rows["V05"][0].text())
    qtbot.waitUntil(lambda: "Vacuum card: V05 opened." in window.log_text())
    qtbot.waitUntil(lambda: window.card.latest.supply_24v is False, timeout=3000)    # back to 12 V
    window.vacuum.valve_rows["V05"][1].click()
    qtbot.waitUntil(lambda: window.card.latest.valves.get("V05") is False)


def test_vent_valve_while_gas_flows(window, qtbot, monkeypatch):
    asked = []
    monkeypatch.setattr(dialogs, "confirm", lambda parent, title, text: (asked.append(title), True)[1])
    window._request_setpoint(4, 1.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[4] == 1.0 and window.bridge.gas_flowing())
    window._valve_requested("V05")
    assert asked == ["Open valve", "Gas is flowing"]
    assert window.sim._setpoint[4] == 0          # zeroed (and confirmed) before the vent valve was sent
    qtbot.waitUntil(lambda: "before you open the vent valve V05" in window.log_text())
    qtbot.waitUntil(lambda: window.card.latest.valves.get("V05"))


def test_advanced_vent_needs_typing_and_zeroes_first(window, qtbot, monkeypatch):
    typed = []
    monkeypatch.setattr(dialogs, "confirm_typed", lambda parent, title, text, word: (typed.append(word), False)[1])
    window._request_setpoint(5, 1.0)
    qtbot.waitUntil(lambda: window.sim._setpoint[5] == 1.0 and window.bridge.gas_flowing())
    window._card_command("chamber", "vent")
    assert typed == ["VENT"] and window.sim._setpoint[5] == 1.0 and window.card.sim_card.chamber_state == "ready"
    monkeypatch.setattr(dialogs, "confirm_typed", lambda *args: True)
    window._card_command("chamber", "vent")
    assert window.sim._setpoint[5] == 0
    qtbot.waitUntil(lambda: window.card.sim_card.chamber_state == "vented")
    qtbot.waitUntil(lambda: "vent the chamber → True" in window.log_text())
    qtbot.waitUntil(lambda: not window.card.gas_status().allowed, timeout=8000)    # vented: no gas


def test_advanced_commands_and_ups(window, qtbot, monkeypatch):
    monkeypatch.setattr(dialogs, "confirm", yes)
    monkeypatch.setattr(dialogs, "confirm_typed", yes)
    window.vacuum.show_advanced()
    assert not window.vacuum.advanced.isHidden()
    window._card_command("ups", None)
    qtbot.waitUntil(lambda: "UPS: AC OK, battery OK." in window.log_text())
    window._card_command("decontaminator", True)
    qtbot.waitUntil(lambda: "decontaminator ON" in window.log_text())
    window._card_command("gun", "vent")
    qtbot.waitUntil(lambda: window.card.sim_card.gun_state == "vented")
    window._card_command("beam", True)       # the simulated card refuses: gun pressure too high
    qtbot.waitUntil(lambda: "beam interlock" in window.log_text(), timeout=5000)


def test_gas_protection_switches(window, qtbot, monkeypatch):
    monkeypatch.setattr(dialogs, "confirm", lambda *args: False)
    window.vacuum.rule_checks["vent_zero"].click()
    assert window.vacuum.rule_checks["vent_zero"].isChecked() and not window.card.supervisor.overrides
    monkeypatch.setattr(dialogs, "confirm", yes)
    window.vacuum.rule_checks["vent_zero"].click()
    assert window.card.supervisor.overrides == {"vent_zero"} and not window.vacuum.rule_checks["vent_zero"].isChecked()
    window.vacuum.rule_checks["vent_zero"].click()
    assert not window.card.supervisor.overrides


def test_real_card_is_read_only_until_enabled(qtbot, tmp_path, monkeypatch):
    from flowapp.config import load_card_config
    from flowapp.core.card_sim import SimCard
    from flowapp.core.http_mock import MockCardServer
    from flowapp.ui import bridge as bridge_module
    monkeypatch.setattr(QMessageBox, "exec", no_dialog)
    monkeypatch.setattr(dialogs, "confirm", no_dialog)
    server = MockCardServer(SimCard(seed=4)).start()
    try:
        save_local({"card_address": server.address}, tmp_path)
        monkeypatch.setattr(bridge_module, "SimBus", type("NotThis", (), {}))     # treat the bus as real
        qsettings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
        w = MainWindow(Settings(poll_hz=20, history_minutes=1, port="COM7", auto_connect=True),
                       bus_factory=lambda port: SimBus(tau=0.05, noise=0.0),
                       channels_path=tmp_path / "channels.json", qsettings=qsettings, make_shortcut=None,
                       card_config_loader=lambda: load_card_config(tmp_path),
                       local_saver=lambda updates: save_local(updates, tmp_path))
        qtbot.addWidget(w)
        w.show()
        qtbot.waitUntil(lambda: w.card.mode == "real" and w.card.latest is not None and w.card.latest.ok)
        assert not w.card.control_allowed and not w.vacuum.lock_banner.isHidden()
        assert "read-only" in w.log_text()
        assert not w.vacuum.valve_rows["V05"][1].isEnabled()
        w._valve_requested("V05")
        assert "card control is locked" in w.log_text()
        w._card_command("chamber", "vent")
        assert server.card.chamber_state == "ready"
        w._card_command("ups", None)            # reads still work
        qtbot.waitUntil(lambda: "UPS: AC OK" in w.log_text())
        assert all(m in ("chbr.prs?", "sem.prs?", "chbr.stat?", "sem.stat?") or p in (["40", "", "4"], ["64", "", "2"])
                   for m, p in server.card.requests)

        monkeypatch.setattr(dialogs, "confirm_typed", lambda *args: True)
        w.vacuum.control_check.click()
        qtbot.waitUntil(lambda: w.card.control_allowed and w.card.latest is not None)
        assert '"card_control_enabled": true' in (tmp_path / "local.json").read_text()
        monkeypatch.setattr(dialogs, "confirm", yes)
        w._valve_requested("V05")
        qtbot.waitUntil(lambda: server.card.register >> 5 & 1)
        w.close()
        assert not w.card.running and not w.bridge.is_connected
    finally:
        server.stop()
