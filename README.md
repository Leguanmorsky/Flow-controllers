# Flow controllers

Control software for Bronkhorst mass flow controllers.

> **Refactor in progress.** The new app (`flowapp/`) is being built in blocks. Until its UI is ready, `run.bat` still starts the current Tkinter GUI (`laboratory_gas_control/final_controller.py`).

## Setup (once per computer, and again after a pull that changes `requirements.txt`)
1. Install Python 3.11 from python.org (keep the "py launcher" option checked).
2. Install the Bronkhorst USB/RS232 driver so the device shows up as a COM port.
3. Double-click `setup_env.bat`. It creates a local `.venv` and installs `requirements.txt`.

The `.venv` folder is not synced through git. Each computer builds its own.

## Run
- Double-click `run.bat`. The COM port is detected automatically (COM9 is tried first, Bluetooth ports are skipped).
- To force a port: `run.bat COM5` (or set the `FLOW_COM_PORT` environment variable).
- In VS Code, the interpreter is preset to `.venv` (`.vscode/settings.json`).

## Tools
- `probe.bat` lists the connected instruments: address, serial number, gas, capacity and unit, control mode, and the current flow. Use `probe.bat COM9` for a specific port, or `probe.bat --sim` for simulated instruments.
- `.venv\Scripts\python -m flowapp --monitor [COM9] [--sim]` shows live values in the console.

## Configuration
- `config/settings.json`: shared defaults (port `auto`, poll rate, graph history). Synced through git.
- `config/local.json`: settings for this computer only, e.g. `{"port": "COM9"}`. Not synced.
- `config/channels.json`: alias, gas and colour per instrument serial number.

## Project layout
| Path | Content |
|---|---|
| `flowapp/core/` | Instrument layer: Bronkhorst driver (`bronkhorst.py`), simulator, background worker |
| `flowapp/config.py` | Settings loading |
| `tests/` | `python -m pytest`, runs on the simulator and a fake propar, never on hardware |
| `docs/` | Pressure-control integration brief and the UHV SEM card web page |
| `laboratory_gas_control/` | Current GUI, replaced by the new UI in the next block |

## Note
The Bronkhorst library on PyPI is `bronkhorst-propar`. The package named just `propar` is unrelated and breaks `import propar`.

## Credits
Ideas were taken from these open-source projects:
[AutoFlow](https://github.com/EthanGYoung/AutoFlow),
[project-Anemoi](https://github.com/thithibaud/project-Anemoi),
[coldplasmas-unimib/flowcontroller](https://github.com/coldplasmas-unimib/flowcontroller).
