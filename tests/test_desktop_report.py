from pathlib import Path
from types import SimpleNamespace

import pytest

from flowapp import __main__ as cli
from flowapp import desktop
from flowapp.core.report import full_report, probe_table, save_report
from flowapp.core.simulator import SimBus


def test_shortcut_script_quotes_paths():
    script = desktop.shortcut_script(target=Path(r"C:\Lab's PC\Flow controllers\run.bat"),
                                     icon=Path(r"C:\Lab's PC\Flow controllers\flowapp\assets\logo.ico"))
    assert r"$link.TargetPath = 'C:\Lab''s PC\Flow controllers\run.bat'" in script
    assert r"$link.WorkingDirectory = 'C:\Lab''s PC\Flow controllers'" in script
    assert r"logo.ico,0'" in script and "GetFolderPath('Desktop')" in script


@pytest.mark.skipif(desktop.sys.platform != "win32", reason="Windows only")
def test_create_shortcut_runs_powershell_and_reports_errors():
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="C:\\Users\\x\\Desktop\\Flow controllers.lnk\n", stderr="")

    assert desktop.create_desktop_shortcut(run=fake_run).endswith("Flow controllers.lnk")
    assert calls[0][0] == "powershell" and "-Command" in calls[0]
    with pytest.raises(OSError, match="denied"):
        desktop.create_desktop_shortcut(run=lambda args, **kw: SimpleNamespace(returncode=1, stdout="",
                                                                               stderr="access denied"))


def test_report_is_read_only_and_complete(tmp_path):
    bus = SimBus(noise=0.0)
    channels = bus.open()
    writes = []
    bus.set_setpoint = lambda *a: writes.append(a)
    lines = full_report(bus, channels, bus.read_states())
    text = "\n".join(lines)
    assert "Port SIM: 3 instrument(s)" in text and "Fluid name (DDE 25)" in text
    assert writes == []
    path = save_report(lines, folder=tmp_path)
    assert path.read_text(encoding="utf-8").startswith("Instrument report")


def test_probe_table_warns_about_local_mode():
    bus = SimBus(noise=0.0)
    channels = bus.open()
    bus.set_fault("analog_mode", 5)
    lines = probe_table(bus.port, channels, bus.read_states())
    assert any("ignores setpoints" in line for line in lines)


def test_cli_probe_in_test_mode(capsys):
    assert cli.main(["--probe", "--sim"]) == 0
    out = capsys.readouterr().out
    assert "Port SIM: 3 instrument(s)" in out and "O2" in out
