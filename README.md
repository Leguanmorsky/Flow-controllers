# Flow controllers

Tkinter GUI for Bronkhorst mass flow controllers (`laboratory_gas_control/final_controller.py`).

## Setup (once per computer, and again after a pull that changes `requirements.txt`)
1. Install Python 3.11 from python.org (keep the "py launcher" option checked).
2. Install the Bronkhorst USB/RS232 driver so the device shows up as a COM port.
3. Double-click `setup_env.bat`. It creates a local `.venv` and installs `requirements.txt`.

The `.venv` folder is not synced through git. Each computer builds its own.

## Run
- Double-click `run.bat`. The COM port is detected automatically (COM9 is tried first).
- To force a port: `run.bat COM5` (or set the `FLOW_COM_PORT` environment variable).
- In VS Code, the interpreter is preset to `.venv` (`.vscode/settings.json`). Run `final_controller.py` from inside `laboratory_gas_control`.

## Note
The Bronkhorst library on PyPI is `bronkhorst-propar`. The package named just `propar` is unrelated and breaks `import propar`.
