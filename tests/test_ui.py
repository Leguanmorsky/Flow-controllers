"""The main window driven against the simulator (offscreen, nothing is sent to hardware)."""

import csv
import json
import sys
import threading

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from flowapp.config import Settings
from flowapp.core.simulator import SimBus
from flowapp.ui import dialogs
from flowapp.ui.bridge import SIM_PORT
from flowapp.ui.main_window import MainWindow


def no_dialog(*args, **kwargs):
    raise AssertionError("unexpected dialog")


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

    settings = Settings(poll_hz=20, history_minutes=1, auto_connect=False)
    qsettings = QSettings(str(tmp_path / "ui.ini"), QSettings.IniFormat)
    w = MainWindow(settings, bus_factory=factory, channels_path=tmp_path / "channels.json", qsettings=qsettings)
    qtbot.addWidget(w)
    w.show()
    w._connect_port(SIM_PORT)
    qtbot.waitUntil(lambda: len(w.cards) == 3 and w.bridge.last_poll is not None)
    w.sim = buses[0]
    yield w
    if w.bridge.is_connected:
        w.bridge.force_disconnect()


def card_ready(window, address):
    return window.cards[address].device_setpoint is not None


def test_connect_shows_cards(window):
    assert sorted(window.cards) == [4, 5, 6]
    assert "[SIMULATOR]" in window.windowTitle()
    assert window.bar.sim_badge.isVisible() and window.zero_action.isEnabled()
    assert window.sim_menu.menuAction().isVisible()
    assert "Connected to SIM: 3 instrument(s)." in window.log_text()


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
    assert saved["SIM-O2"]["alias"] == "Oxygen line" and saved["SIM-O2"]["max_flow"] == 5.0
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
    window.bar.connect_button.click()       # "Disconnect"
    assert not window.bridge.is_connected and window.cards == {}
    assert window.sim._setpoint[5] == 0.0
    assert not any(t.name == "InstrumentWorker" and t.is_alive() for t in threading.enumerate())
    assert window.bar.connect_button.text() == "Connect"


def test_zero_failure_asks_before_disconnecting(window, qtbot, monkeypatch):
    answers = ["cancel", "anyway"]
    monkeypatch.setattr(dialogs, "ask_zero_failed", lambda parent, error, action: answers.pop(0))
    window.sim.set_fault("unplugged")
    window.bar.connect_button.click()
    assert window.bridge.is_connected        # the user cancelled
    window.bar.connect_button.click()
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
